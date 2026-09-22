"""Unit tests for token budget calculation and context trimming (PRD §9.6)."""

from api.app.assistant.system_prompt import get_system_prompt
from api.app.assistant.token_budgeter import (
    MAX_HISTORY_TOKENS,
    MAX_SCHEMAS_TOKENS,
    MAX_SYSTEM_TOKENS,
    MAX_TOOL_RESULT_TOKENS,
    check_request_budget,
    compact_tool_result,
    estimate_tokens,
    trim_history,
)
from api.app.assistant.tools import get_openai_tools_schema


def test_system_prompt_budget():
    """System prompt must stay between ~250 and 600 tokens."""
    prompt = get_system_prompt("both")
    tokens = estimate_tokens(prompt)
    assert 100 <= tokens <= MAX_SYSTEM_TOKENS, f"System prompt tokens: {tokens}"


def test_tool_schemas_budget():
    """All 6 tool schemas together must stay under 900 tokens."""
    schemas = get_openai_tools_schema()
    tokens = estimate_tokens(schemas)
    assert tokens <= MAX_SCHEMAS_TOKENS, f"Tool schemas tokens: {tokens}"


def test_history_trimming():
    """Conversation history must be trimmed to <= 500 tokens."""
    long_history = [
        {"role": "user", "content": "Tell me about the weather yesterday " * 30},
        {"role": "assistant", "content": "Yesterday was rainy in many parts " * 30},
        {"role": "user", "content": "What about Delhi today?"},
    ]

    trimmed = trim_history(long_history, max_tokens=MAX_HISTORY_TOKENS)
    tokens = sum(estimate_tokens(m["content"]) for m in trimmed)
    assert tokens <= MAX_HISTORY_TOKENS


def test_compact_tool_result_overflow():
    """Verifies that oversized tool results are compacted to fit under 700 tokens."""
    big_tool_result = {
        "title": "Big data",
        "columns": ["col1", "col2", "col3"],
        "n_rows": 100,
        "preview": [["data" * 50] * 5 for _ in range(10)],
        "stats": {"detail": "very detailed stats " * 100},
    }

    compacted = compact_tool_result(big_tool_result, max_tokens=MAX_TOOL_RESULT_TOKENS)
    tokens = estimate_tokens(compacted)
    assert tokens <= MAX_TOOL_RESULT_TOKENS


def test_deterministic_budget_check():
    """Verifies budget validator passes normal requests and provides accurate breakdown."""
    prompt = get_system_prompt("explain")
    schemas = get_openai_tools_schema()
    messages = [{"role": "user", "content": "Forecast for Nagpur"}]

    budget = check_request_budget(prompt, schemas, messages)
    assert budget["allowed"] is True
    assert "system" in budget["breakdown"]
    assert "tools" in budget["breakdown"]
