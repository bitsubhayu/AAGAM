"""Token budget calculator and history trimmer for AAGAM Assistant (PRD §9.6, Tech Stack §8.2).

Guarantees requests stay strictly within the Groq token limits:
- System prompt: ~250-600 tokens
- Tool schemas (6 tools): <= 900 tokens total
- Conversation history: trimmed to <= 500 tokens
- Each tool result: <= 700 tokens
- Completion reserve: 400 tokens
- Max model calls per question: <= 3
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger("aagam.assistant.token_budgeter")

# Budget constants
MAX_SYSTEM_TOKENS = 600
MAX_SCHEMAS_TOKENS = 900
MAX_HISTORY_TOKENS = 500
MAX_TOOL_RESULT_TOKENS = 700
MAX_COMPLETION_TOKENS = 400
MAX_TOTAL_REQUEST_TOKENS = 3500  # Well below the 8,000 TPM limit to allow 2-3 turn calls


def estimate_tokens(obj: Any) -> int:
    """Conservative token estimator (~3.8 characters per token)."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        text = obj
    elif isinstance(obj, (dict, list)):
        text = json.dumps(obj, separators=(",", ":"))
    else:
        text = str(obj)
    # 1 token is approximately 3.8 characters in technical English / JSON
    return max(1, int(len(text) / 3.8) + 1)


def trim_history(
    messages: List[Dict[str, Any]],
    max_tokens: int = MAX_HISTORY_TOKENS,
) -> List[Dict[str, Any]]:
    """Trims conversation history to the most recent turns fitting within max_tokens."""
    if not messages:
        return []

    # Iterate backwards from newest messages
    accumulated: List[Dict[str, Any]] = []
    current_tokens = 0

    for msg in reversed(messages):
        # Don't trim the latest user message
        msg_tokens = estimate_tokens(msg.get("content", "")) + 10
        if current_tokens + msg_tokens > max_tokens and accumulated:
            break
        accumulated.append(msg)
        current_tokens += msg_tokens

    # Restore chronological order
    accumulated.reverse()
    return accumulated


def compact_tool_result(result_dict: Dict[str, Any], max_tokens: int = MAX_TOOL_RESULT_TOKENS) -> Dict[str, Any]:
    """Ensures a tool result summary does not exceed the target tool token budget."""
    tokens = estimate_tokens(result_dict)
    if tokens <= max_tokens:
        return result_dict

    # Compact preview rows if over budget
    compacted = dict(result_dict)
    if "preview" in compacted and isinstance(compacted["preview"], list):
        # Reduce preview to 2 rows or 1 row
        if len(compacted["preview"]) > 2:
            compacted["preview"] = compacted["preview"][:2]
        elif len(compacted["preview"]) > 1:
            compacted["preview"] = compacted["preview"][:1]

    # If still over, strip non-essential stats
    if estimate_tokens(compacted) > max_tokens and "stats" in compacted:
        compacted["stats"] = {"summary": "detailed in artifact"}

    return compacted


def check_request_budget(
    system_prompt: str,
    tools: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    completion_reserve: int = MAX_COMPLETION_TOKENS,
) -> Dict[str, Any]:
    """Deterministic budget check before making an LLM call.

    Returns:
    - allowed: bool
    - total_estimated_tokens: int
    - breakdown: Dict[str, int]
    - trimmed_messages: List[Dict[str, Any]]
    """
    sys_tokens = estimate_tokens(system_prompt)
    tools_tokens = estimate_tokens(tools)

    # Trim messages to fit history budget
    trimmed = trim_history(messages, max_tokens=MAX_HISTORY_TOKENS)
    msg_tokens = sum(estimate_tokens(m.get("content", "")) + 10 for m in trimmed)

    total = sys_tokens + tools_tokens + msg_tokens + completion_reserve
    allowed = total <= MAX_TOTAL_REQUEST_TOKENS

    breakdown = {
        "system": sys_tokens,
        "tools": tools_tokens,
        "messages": msg_tokens,
        "completion_reserve": completion_reserve,
        "total": total,
    }

    if not allowed:
        logger.warning(f"Request token budget exceeded: {breakdown}")

    return {
        "allowed": allowed,
        "total_estimated_tokens": total,
        "breakdown": breakdown,
        "trimmed_messages": trimmed,
    }
