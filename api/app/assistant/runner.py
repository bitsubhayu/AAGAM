"""Main Assistant agent runner and SSE event generator (PRD §9.3, §9.8).

Orchestrates:
1. Injection detection
2. Rate-limiting check (hourly user quota & Groq throttle)
3. 10-minute response cache check
4. Bounded tool loop (<= 3 calls) with parameter-validated execution
5. Raw data delivered to browser via `data_table` event; compact summaries to LLM
6. Token streaming
7. Mode enforcement (RAW <= 1 sentence, EXPLAIN, BOTH)
8. Number Guard check with 1x strict retry on unverified numbers
9. Audit logging into PostgreSQL `chat_audit`
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

import asyncpg

from api.app.assistant.audit import record_chat_audit
from api.app.assistant.cache import get_cached_response, set_cached_response
from api.app.assistant.client import call_groq_completion
from api.app.assistant.number_guard import verify_answer_numbers
from api.app.assistant.prompt_injection import detect_injection_attempt, sanitize_output, wrap_tool_output_as_data
from api.app.assistant.rate_limiter import check_user_rate_limit, record_user_request
from api.app.assistant.schemas import ChatRequest, ToolEnvelope
from api.app.assistant.system_prompt import get_system_prompt
from api.app.assistant.token_budgeter import check_request_budget, compact_tool_result
from api.app.assistant.tools import get_openai_tools_schema, get_tool
from api.app.assistant.tools.base import ToolContext
from api.app.auth.dependencies import CurrentUser
from api.app.routers.artifacts import _ARTIFACT_STORE

logger = logging.getLogger("aagam.assistant.runner")


def enforce_mode_constraints(text: str, mode: str) -> str:
    """Enforces server-side constraints per mode (PRD §9.2, §10)."""
    if mode == "raw":
        # Server strictly enforces at most 1 caption sentence
        cleaned = text.strip()
        # Find the end of the first sentence (. ? !)
        match = re.search(r"([.?!])(?:\s|$)", cleaned)
        if match:
            first_sentence = cleaned[: match.end()].strip()
            return first_sentence
        # Fallback if no period
        return cleaned.split("\n")[0].strip()

    return text.strip()


async def run_assistant_stream(
    request: ChatRequest,
    current_user: CurrentUser,
    conn: Optional[asyncpg.Connection] = None,
) -> AsyncGenerator[str, None]:
    """Generates the full Server-Sent Events stream for the assistant query."""
    start_time = time.time()
    user_id = current_user.user_id if current_user else "anonymous"
    mode = request.mode or "both"
    active_model_version = "v2026-09-14"

    # 1. Prompt injection guard
    if detect_injection_attempt(request.message):
        logger.warning(f"Potential injection attempt detected from user {user_id}: {request.message[:50]}")
        yield f"event: meta\ndata: {json.dumps({'model': 'aagam-shield', 'cached': False})}\n\n"
        await asyncio.sleep(0.01)
        refusal = "I cannot process queries that attempt to override system instructions or manipulate internal settings. Please ask a weather or forecast-related question."
        yield f"event: token\ndata: {json.dumps({'content': refusal})}\n\n"
        await asyncio.sleep(0.01)
        yield f"event: done\ndata: {json.dumps({'status': 'completed', 'latency_ms': 50, 'tokens_used': 20})}\n\n"
        yield f"event: end\ndata: {json.dumps({'status': 'completed'})}\n\n"
        return

    # 2. User rate limit check (15/hr)
    allowed, retry_after = check_user_rate_limit(user_id)
    if not allowed:
        yield f"event: error\ndata: {json.dumps({'code': 'RATE_LIMITED', 'message': f'Hourly limit of 15 questions reached. Try again in {retry_after}s.', 'retry_after': retry_after})}\n\n"
        return

    # 3. Response cache check
    cached = get_cached_response(request.message, mode, active_model_version)
    if cached:
        logger.info("Serving assistant response from 10-minute cache.")
        yield f"event: meta\ndata: {json.dumps({'model': cached['model'], 'cached': True})}\n\n"
        for tc in cached.get("tool_calls", []):
            yield f"event: tool_call\ndata: {json.dumps(tc)}\n\n"
        for dt in cached.get("data_tables", []):
            yield f"event: data_table\ndata: {json.dumps(dt)}\n\n"
        # Stream cached answer in chunks for natural UI experience
        words = cached["text"].split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i : i + 3]) + (" " if i + 3 < len(words) else "")
            yield f"event: token\ndata: {json.dumps({'content': chunk})}\n\n"
            await asyncio.sleep(0.01)
        if cached.get("citations"):
            yield f"event: citations\ndata: {json.dumps(cached['citations'])}\n\n"
        if cached.get("warning"):
            yield f"event: warning\ndata: {json.dumps({'message': cached['warning']})}\n\n"
        latency_ms = int((time.time() - start_time) * 1000)
        yield f"event: done\ndata: {json.dumps({'status': 'completed', 'latency_ms': latency_ms, 'tokens_used': cached.get('tokens_used', 50)})}\n\n"
        yield f"event: end\ndata: {json.dumps({'status': 'completed'})}\n\n"
        return

    # 4. Initialize agent execution context
    tool_context = ToolContext(conn=conn, current_user=current_user)
    system_prompt = get_system_prompt(mode)
    tools_schema = get_openai_tools_schema()

    # Build initial message list
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request.message},
    ]

    # Token budget verification
    budget = check_request_budget(system_prompt, tools_schema, messages)
    if not budget["allowed"]:
        logger.warning(f"Initial budget tight; using trimmed context: {budget['breakdown']}")
        messages = [{"role": "system", "content": system_prompt}] + budget["trimmed_messages"]

    # Announce start and meta events
    yield f"event: start\ndata: {json.dumps({'status': 'connected'})}\n\n"
    model_name = "openai/gpt-oss-120b"
    yield f"event: meta\ndata: {json.dumps({'model': model_name, 'cached': False})}\n\n"
    await asyncio.sleep(0.01)

    tools_used: List[Dict[str, Any]] = []
    data_tables_emitted: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    collected_tool_envelopes: List[ToolEnvelope] = []
    total_tokens_in = 0
    total_tokens_out = 0
    flagged = False

    # 5. Bounded Tool Loop (<= 3 calls per PRD §9.6)
    max_loops = 3
    final_text = ""

    for loop_idx in range(max_loops):
        try:
            resp, used_model, metrics = await call_groq_completion(
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                model=model_name,
            )
            model_name = used_model
            total_tokens_in += metrics.get("tokens_in", 0)
            total_tokens_out += metrics.get("tokens_out", 0)

            choice = resp.choices[0]
            message_obj = choice.message

            # Check if model requested tool calls
            tool_calls = getattr(message_obj, "tool_calls", None)

            if tool_calls:
                # Add clean assistant message with tool calls to history (omit unsupported properties like annotations)
                clean_assistant_msg = {
                    "role": "assistant",
                    "content": message_obj.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(clean_assistant_msg)

                for tc in tool_calls:
                    fn_name = tc.function.name
                    fn_args_str = tc.function.arguments

                    try:
                        fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                    except Exception:
                        fn_args = {}

                    tool = get_tool(fn_name)
                    if not tool:
                        logger.error(f"Model attempted to call unauthorized tool: {fn_name}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({"error": f"Tool '{fn_name}' is not allowed."}),
                        })
                        continue

                    # Yield tool_call event
                    tc_payload = {"name": fn_name, "arguments": fn_args}
                    tools_used.append(tc_payload)
                    yield f"event: tool_call\ndata: {json.dumps(tc_payload)}\n\n"
                    await asyncio.sleep(0.01)

                    # Execute tool
                    envelope = await tool.execute(fn_args, tool_context)
                    collected_tool_envelopes.append(envelope)

                    # Retrieve raw records for data_table event
                    artifact_data = _ARTIFACT_STORE.get(envelope.artifact_id, {}).get("data", [])
                    dt_payload = envelope.to_data_table_dict(artifact_data)
                    data_tables_emitted.append(dt_payload)

                    # Yield data_table event to browser (raw data never in LLM prompt!)
                    yield f"event: data_table\ndata: {json.dumps(dt_payload)}\n\n"
                    await asyncio.sleep(0.01)

                    # Add compact summary to LLM messages
                    compact_summary = compact_tool_result(envelope.to_llm_dict())
                    wrapped_data = wrap_tool_output_as_data(fn_name, compact_summary)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": wrapped_data,
                    })

                    # Add citation
                    citations.append({
                        "tool": fn_name,
                        "issue_time": envelope.meta.get("issue_time", datetime.now(timezone.utc).isoformat()),
                        "model_version": envelope.meta.get("model_version", active_model_version),
                    })

                # Loop continues to allow model to synthesize or make another call
                continue

            else:
                # Model produced final textual answer
                final_text = message_obj.content or ""
                break

        except Exception as e:
            logger.error(f"Error during assistant agent loop: {e}", exc_info=True)
            # Check for rate limit error
            if "rate_limit" in str(e).lower() or "429" in str(e) or "ratelimit" in type(e).__name__.lower():
                yield f"event: error\ndata: {json.dumps({'code': 'RATE_LIMITED', 'message': 'Assistant busy — try again in 15 seconds.', 'retry_after': 15})}\n\n"
                yield f"event: end\ndata: {json.dumps({'status': 'error'})}\n\n"
                return
            yield f"event: error\ndata: {json.dumps({'code': 'ASSISTANT_ERROR', 'message': f'Assistant error: {str(e)}', 'retry_after': None})}\n\n"
            yield f"event: end\ndata: {json.dumps({'status': 'error'})}\n\n"
            return

    # If loop ended without text (e.g. after max tools), do a final generation call
    if not final_text:
        try:
            resp, used_model, metrics = await call_groq_completion(
                messages=messages,
                tools=None,
                model=model_name,
            )
            total_tokens_in += metrics.get("tokens_in", 0)
            total_tokens_out += metrics.get("tokens_out", 0)
            final_text = resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Error during final text generation: {e}")
            final_text = "Forecast data retrieved. See the table above."

    # 6. Mode enforcement on generated text
    final_text = enforce_mode_constraints(final_text, mode)

    # 7. Number Guard Verification (PRD §9.7, M5 Metric)
    tool_dicts = [env.to_llm_dict() for env in collected_tool_envelopes]
    if collected_tool_envelopes:
        is_verified, unverified = verify_answer_numbers(final_text, tool_dicts)
        if not is_verified:
            logger.warning(f"Number Guard: answer contains unverified numbers: {unverified}; executing 1x strict retry")
            # Trigger 1x strict retry
            retry_messages = list(messages)
            retry_messages.append({"role": "assistant", "content": final_text})
            retry_messages.append({
                "role": "user",
                "content": f"CRITICAL REQUIREMENT: In your previous reply you used numbers not found in the tool results: {unverified}. Rewrite your response using ONLY exact numbers traceable to the tool data above. Do not estimate or add unverified numbers.",
            })

            try:
                retry_resp, _, r_metrics = await call_groq_completion(
                    messages=retry_messages,
                    tools=None,
                    model=model_name,
                )
                total_tokens_in += r_metrics.get("tokens_in", 0)
                total_tokens_out += r_metrics.get("tokens_out", 0)
                retry_text = enforce_mode_constraints(retry_resp.choices[0].message.content or "", mode)

                # Cross-check retry
                r_verified, r_unverified = verify_answer_numbers(retry_text, tool_dicts)
                if r_verified:
                    final_text = retry_text
                else:
                    # Still unverified: flag and append warning
                    flagged = True
                    final_text = retry_text + "\n\n*(Note: Some figures could not be verified against tool outputs)*"
            except Exception as e:
                logger.error(f"Retry failed: {e}")
                flagged = True
                final_text += "\n\n*(Note: Some figures could not be verified against tool outputs)*"

    # Sanitize final output
    final_text = sanitize_output(final_text)

    # 8. Stream final tokens to client
    words = final_text.split(" ")
    for i in range(0, len(words), 2):
        chunk = " ".join(words[i : i + 2]) + (" " if i + 2 < len(words) else "")
        yield f"event: token\ndata: {json.dumps({'content': chunk})}\n\n"
        await asyncio.sleep(0.01)

    # 9. Citations event
    if citations:
        yield f"event: citations\ndata: {json.dumps(citations)}\n\n"
        await asyncio.sleep(0.01)

    # 10. Warning event (if flagged)
    if flagged:
        yield f"event: warning\ndata: {json.dumps({'message': 'Some figures could not be verified'})}\n\n"
        await asyncio.sleep(0.01)

    # 11. Done & End events
    latency_ms = int((time.time() - start_time) * 1000)
    total_tokens = total_tokens_in + total_tokens_out
    yield f"event: done\ndata: {json.dumps({'status': 'completed', 'latency_ms': latency_ms, 'tokens_used': total_tokens, 'model': model_name})}\n\n"
    yield f"event: end\ndata: {json.dumps({'status': 'completed'})}\n\n"

    # Record user usage & chat_audit
    record_user_request(user_id)
    await record_chat_audit(
        question=request.message,
        mode=mode,
        tools_used=tools_used,
        model=model_name,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        latency_ms=latency_ms,
        cached=False,
        flagged=flagged,
        user_id=user_id if user_id != "anonymous" else None,
        conn=conn,
    )

    # Cache successful answer
    set_cached_response(
        request.message,
        mode,
        active_model_version,
        {
            "model": model_name,
            "text": final_text,
            "tool_calls": tools_used,
            "data_tables": data_tables_emitted,
            "citations": citations,
            "warning": "Some figures could not be verified" if flagged else None,
            "tokens_used": total_tokens,
        },
    )
