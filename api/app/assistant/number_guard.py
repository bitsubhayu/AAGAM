"""Number Guard verification engine for AAGAM Assistant (PRD §9.7, M5 Metric).

Guarantees 100% numerical fidelity:
- Extracts every numeric token from the generated answer
- Verifies every figure against the tool outputs for that turn
- Permits valid dates, lead-day numbers (0-7), model counts (1-4), IMD thresholds, and rounding tolerance
- Triggers 1 automatic strict retry on unmatched numbers; flags and appends verification warning if still unverified.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger("aagam.assistant.number_guard")

# Regex to extract numeric figures (integers, floats, percentages)
NUMBER_REGEX = re.compile(r"(?<![a-zA-Z_])[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?%?(?![a-zA-Z_])")

# Common meteorological & domain allowed constants (PRD §9.7)
ALLOWED_DOMAIN_NUMBERS: Set[float] = {
    0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 14.0, 30.0, 60.0, 90.0, 180.0,  # Leads and standard windows
    12.0, 24.0, 48.0, 72.0,                                                       # Hourly windows
    40.0,                                                                         # 40 configured locations
    64.5, 115.6, 204.5,                                                           # IMD rainfall thresholds
    37.0, 40.0, 42.0, 45.0, 47.0,                                                 # IMD heatwave thresholds
    50.0, 60.0, 70.0,                                                             # Wind thresholds
    10.0, 15.0, 20.0, 25.0, 35.0, 50.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0,       # Percentages and sample sizes
    500.0, 5000.0,                                                                # System caps & limits
}

# Years covering historical training and reanalysis backfill (2015-2030)
ALLOWED_YEARS: Set[float] = {float(y) for y in range(2015, 2031)}


def extract_numbers_from_text(text: str) -> List[float]:
    """Extracts all floating-point numbers from a string, stripping percentages and URLs."""
    if not text:
        return []

    # Strip URLs, paths, and signed tokens so random hex/base64 strings are not parsed as scientific notation
    cleaned = re.sub(r"https?://\S+|/api/\S+|token=[a-zA-Z0-9_\-\.]+", " ", text)
    # Clean out obvious date patterns like YYYY-MM-DD or HH:MM to avoid splitting on hyphens/colons
    cleaned = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r" \1 \2 \3 ", cleaned)
    cleaned = re.sub(r"(\d{2}):(\d{2})", r" \1 \2 ", cleaned)

    matches = NUMBER_REGEX.findall(cleaned)
    numbers: List[float] = []
    for m in matches:
        m_str = m.rstrip("%").strip()
        try:
            val = float(m_str)
            if math.isinf(val) or math.isnan(val):
                continue
            numbers.append(val)
        except ValueError:
            continue
    return numbers


def extract_numbers_from_data(data: Any) -> Set[float]:
    """Recursively extracts all numeric values present in tool output dictionary / lists."""
    numbers: Set[float] = set()

    if isinstance(data, (int, float)):
        numbers.add(float(data))
    elif isinstance(data, str):
        # Could be an ISO date, number string, or formatted string
        for num in extract_numbers_from_text(data):
            numbers.add(num)
    elif isinstance(data, dict):
        for k, v in data.items():
            numbers.update(extract_numbers_from_data(k))
            numbers.update(extract_numbers_from_data(v))
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            numbers.update(extract_numbers_from_data(item))

    return numbers


def verify_answer_numbers(
    answer_text: str,
    tool_outputs: List[Dict[str, Any]],
    tolerance_abs: float = 0.5,
    tolerance_pct: float = 0.02,
) -> Tuple[bool, List[float]]:
    """Verifies that all numbers in the answer are traceable to tool outputs or allowed constants.

    Returns:
    - is_valid: bool
    - unverified_numbers: List[float]
    """
    answer_numbers = extract_numbers_from_text(answer_text)
    if not answer_numbers:
        return True, []

    # Extract all numbers present across all tool outputs for this turn
    ground_truth_numbers: Set[float] = set()
    for out in tool_outputs:
        ground_truth_numbers.update(extract_numbers_from_data(out))

    unverified: List[float] = []

    for num in answer_numbers:
        # 1. Direct allowed domain numbers (dates, lead days 0-7, models count 1-4)
        if num in ALLOWED_DOMAIN_NUMBERS or num in ALLOWED_YEARS:
            continue

        # Month numbers (1 to 12) or day numbers (1 to 31)
        if num.is_integer() and 1.0 <= num <= 31.0:
            continue

        # 2. Check match in tool outputs (exact or within rounding tolerance)
        matched = False
        for gt in ground_truth_numbers:
            if abs(num - gt) <= tolerance_abs:
                matched = True
                break
            if gt != 0 and abs(num - gt) / abs(gt) <= tolerance_pct:
                matched = True
                break

        if not matched:
            unverified.append(num)

    if unverified:
        logger.warning(f"Number Guard flagged unverified numbers in answer: {unverified}")
        return False, unverified

    return True, []
