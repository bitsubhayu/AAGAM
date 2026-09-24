"""Evidence and sample floor checks for model version evaluation (Design Doc §I).

Mandatory floors checked before any evaluation window is eligible to support promotion:
1. Minimum verified forecasts per stratum: >= 30
2. Minimum qualifying strata: >= 5
3. Full regional representation: All 5 configured AAGAM regions (EAST_NE, SOUTH, CENTRAL, NW, HIMALAYAN)
4. Minimum lead times: >= 4 distinct lead days (out of 0-7)
5. CSI threshold event floor: >= 10 events (otherwise CSI dropped from that stratum)
6. Minimum total sample floor: >= 150 verified forecasts across qualifying strata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from pipeline.versioning.config import FloorsConfig, MarginConfig


@dataclass
class WindowFloorsResult:
    floors_met: bool
    qualifying_strata_count: int
    excluded_strata_count: int
    total_samples: int
    regions_represented: List[str]
    missing_regions: List[str]
    lead_days_represented: List[int]
    failure_reasons: List[str] = field(default_factory=list)

    @property
    def primary_failure_reason(self) -> Optional[str]:
        return "; ".join(self.failure_reasons) if self.failure_reasons else None


def check_min_samples_per_stratum(n_samples: int, min_samples: int = 30) -> bool:
    """Checks whether a single stratum has sufficient verified forecasts to be included."""
    return n_samples >= min_samples


def check_min_strata(qualifying_strata_count: int, min_strata: int = 5) -> bool:
    """Checks whether at least the minimum number of qualifying strata contributed."""
    return qualifying_strata_count >= min_strata


def check_min_regions_represented(
    represented_regions: Set[str], required_regions: Optional[List[str]] = None
) -> Tuple[bool, List[str]]:
    """Checks whether all 5 configured AAGAM meteorological regions contributed qualifying strata."""
    req = set(required_regions or ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"])
    missing = sorted(list(req - represented_regions))
    return len(missing) == 0, missing


def check_min_lead_days(represented_lead_days: Set[int], min_leads: int = 4) -> bool:
    """Checks whether at least min_leads distinct lead times are represented."""
    return len(represented_lead_days) >= min_leads


def check_csi_event_floor(event_count: int, min_events: int = 10) -> bool:
    """Checks whether a rainfall threshold stratum has enough verified event occurrences to include CSI."""
    return event_count >= min_events


def validate_evaluation_window_temporal_safety(
    evaluation_window_start: date,
    evaluation_window_end: date,
    as_of_date: date,
    training_window_end: Optional[date] = None,
    validation_window_end: Optional[date] = None,
) -> Tuple[bool, Optional[str]]:
    """Enforces strict temporal safety and data-leakage prevention (Design Doc §D, §F).

    Invariants:
    1. evaluation_window_end <= as_of_date: Evaluation cannot use future unobserved data.
    2. evaluation_window_start <= evaluation_window_end: Start date must precede or equal end date.
    3. If training_window_end is given: evaluation_window_start > training_window_end.
       Evaluation data cannot overlap candidate's training partition.
    4. If validation_window_end is given: evaluation_window_start > validation_window_end.
       Evaluation data cannot overlap candidate's validation partition.
    """
    if evaluation_window_start > evaluation_window_end:
        return False, f"Invalid window bounds: start ({evaluation_window_start}) > end ({evaluation_window_end})"

    if evaluation_window_end > as_of_date:
        return False, f"Temporal leakage: evaluation window end ({evaluation_window_end}) is after as_of_date ({as_of_date})"

    if training_window_end and evaluation_window_start <= training_window_end:
        return False, f"Data leakage: evaluation window ({evaluation_window_start}) overlaps training partition (ended {training_window_end})"

    if validation_window_end and evaluation_window_start <= validation_window_end:
        return False, f"Data leakage: evaluation window ({evaluation_window_start}) overlaps validation partition (ended {validation_window_end})"

    return True, None


def evaluate_window_floors(
    strata: List[Dict[str, Any]],
    floors_config: Optional[FloorsConfig] = None,
    margin_config: Optional[MarginConfig] = None,
    required_regions: Optional[List[str]] = None,
) -> WindowFloorsResult:
    """Evaluates all sample and evidence floors across a collection of candidate strata rows.

    Each stratum dict is expected to contain:
    - n: int (verified sample count)
    - region: str
    - lead_days: int
    - variable: str
    - outcome: Optional[str] (e.g. 'pending', 'unverifiable' - excluded if present)
    - degraded: Optional[bool] (excluded if True)
    """
    cfg_f = floors_config or FloorsConfig()
    cfg_m = margin_config or MarginConfig()
    req_regions = required_regions or ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]

    qualifying_strata = []
    excluded_strata = []
    failure_reasons = []

    for s in strata:
        # Exclude rows where outcome is pending or unverifiable, or degraded is True
        if s.get("outcome") in ("pending", "unverifiable") or s.get("degraded") is True:
            excluded_strata.append(s)
            continue

        n_samples = s.get("n", 0)
        if check_min_samples_per_stratum(n_samples, cfg_f.min_samples_per_stratum):
            qualifying_strata.append(s)
        else:
            excluded_strata.append(s)

    qualifying_count = len(qualifying_strata)
    total_samples = sum(s.get("n", 0) for s in qualifying_strata)
    represented_regions = {s.get("region") for s in qualifying_strata if s.get("region")}
    represented_leads = {int(s.get("lead_days")) for s in qualifying_strata if s.get("lead_days") is not None}

    # Floor 1: Min strata count
    if not check_min_strata(qualifying_count, cfg_f.min_strata):
        failure_reasons.append(
            f"INSUFFICIENT_DATA: Qualifying strata count ({qualifying_count}) below minimum floor ({cfg_f.min_strata})"
        )

    # Floor 2: Total sample floor
    if total_samples < cfg_m.min_total_sample_floor:
        failure_reasons.append(
            f"INSUFFICIENT_DATA: Total verified samples ({total_samples}) below minimum floor ({cfg_m.min_total_sample_floor})"
        )

    # Floor 3: Regional coverage (all 5 regions)
    all_regions_present, missing_regions = check_min_regions_represented(represented_regions, req_regions)
    if not all_regions_present:
        failure_reasons.append(
            f"INSUFFICIENT_DATA: Missing required regions in qualifying strata: {missing_regions}"
        )

    # Floor 4: Lead-day coverage
    if not check_min_lead_days(represented_leads, cfg_f.min_lead_days):
        failure_reasons.append(
            f"INSUFFICIENT_DATA: Distinct lead days ({len(represented_leads)}) below minimum floor ({cfg_f.min_lead_days})"
        )

    floors_met = len(failure_reasons) == 0

    return WindowFloorsResult(
        floors_met=floors_met,
        qualifying_strata_count=qualifying_count,
        excluded_strata_count=len(excluded_strata),
        total_samples=total_samples,
        regions_represented=sorted(list(represented_regions)),
        missing_regions=missing_regions,
        lead_days_represented=sorted(list(represented_leads)),
        failure_reasons=failure_reasons,
    )
