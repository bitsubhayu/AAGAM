"""Unit tests for the Number Guard verification engine (PRD §9.7, M5 Metric)."""

from api.app.assistant.number_guard import extract_numbers_from_text, verify_answer_numbers


def test_extract_numbers_from_text():
    """Extracts integers, floats, percentages, and handles ISO dates cleanly."""
    text = "On 2026-09-20 at 08:30 IST, rainfall was 42.5 mm, an increase of 15%."
    numbers = extract_numbers_from_text(text)
    # 2026, 9, 20, 8, 30, 42.5, 15
    assert 42.5 in numbers
    assert 15.0 in numbers


def test_verify_numbers_exact_match():
    """Passes when all figures in answer are present in tool output."""
    answer = "The blended forecast for Bhubaneswar is 78.4 mm on Day+1 (2026-09-20)."
    tool_outputs = [{
        "columns": ["valid_date", "blended"],
        "preview": [["2026-09-20", 78.4]],
        "stats": {"blended": {"max": 78.4}},
    }]

    is_valid, unverified = verify_answer_numbers(answer, tool_outputs)
    assert is_valid is True
    assert len(unverified) == 0


def test_verify_numbers_rounding_tolerance():
    """Passes when numbers in answer are rounded versions of tool numbers."""
    answer = "Rainfall is expected to be 42 mm."
    tool_outputs = [{
        "stats": {"blended": {"mean": 42.12}},
    }]

    is_valid, unverified = verify_answer_numbers(answer, tool_outputs, tolerance_abs=0.5)
    assert is_valid is True
    assert len(unverified) == 0


def test_verify_numbers_domain_allowlist():
    """Permits dates, lead days 0-7, model counts 1-4, and IMD thresholds."""
    answer = "3 of 4 models predict rain above 64.5 mm threshold for Day+2."
    tool_outputs = [{
        "columns": ["lead_days"],
        "preview": [[2]],
    }]

    is_valid, unverified = verify_answer_numbers(answer, tool_outputs)
    assert is_valid is True
    assert len(unverified) == 0


def test_verify_numbers_detects_untraceable_hallucination():
    """Flags answers containing invented numbers not present in tool output."""
    answer = "The maximum temperature will reach 54.8 °C in Delhi."  # 54.8 is not in tool data
    tool_outputs = [{
        "stats": {"blended": {"max": 38.2, "min": 31.0}},
    }]

    is_valid, unverified = verify_answer_numbers(answer, tool_outputs)
    assert is_valid is False
    assert 54.8 in unverified
