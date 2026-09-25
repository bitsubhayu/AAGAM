"""Shared Authoritative Skill Scoring Service (PRD §6, §12).

Provides unified skill evaluation for:
- /api/v1/skill HTTP endpoint
- Assistant `get_skill` tool

Ensures identical metric formulas, pooling semantics, and data-source attribution
for both the live operational window (max 90 days) and the formal held-out 90-day test.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Optional

import asyncpg
import pandas as pd

from core.schemas import SkillQueryResponse, SkillScoreItem

logger = logging.getLogger("aagam.services.skill")

BASELINE_COMPARISONS_PARQUET = Path("data/baseline_comparisons.parquet")

CANDIDATE_MAP = {
    "GFS": "gfs",
    "ECMWF IFS": "ecmwf_ifs",
    "ICON": "icon",
    "AIFS": "aifs",
    "Equal-Weight Mean": "equal_mean",
    "Best-Single Model": "best_single",
    "Inverse-MAE Blend": "blend",
}


def get_maturity_label(verified_days: int) -> str:
    """Returns human-readable maturity state based on verified daily observation count."""
    if verified_days == 0:
        return "NO VERIFICATION DATA"
    elif 1 <= verified_days <= 3:
        return "PRELIMINARY LIVE VERIFICATION"
    elif 4 <= verified_days <= 6:
        return "EARLY LIVE VERIFICATION"
    elif 7 <= verified_days <= 29:
        return "LIVE VERIFICATION"
    elif 30 <= verified_days <= 89:
        return "LIVE VERIFICATION"
    else:
        return "LIVE VERIFICATION · 90-DAY MAX"


def get_truth_source_label(variable: Optional[str] = None) -> str:
    """Returns authoritative description of observation ground-truth source."""
    if variable == "rain_mm":
        return "ERA5 Climatology Fallback (IMD Offline)"
    elif variable in ("tmax_c", "wind_max_kmh"):
        return "ERA5 Historical Reanalysis"
    return "IMD 0.25° Gridded Rainfall & ERA5 Climatology Fallback"


async def fetch_skill_scores(
    conn: Optional[asyncpg.Connection],
    scope: str = "live",
    group_by: str = "model",
    variable: Optional[str] = None,
    window_days: Optional[int] = 90,
    region: Optional[str] = None,
    season: Optional[str] = None,
) -> SkillQueryResponse:
    """Retrieves authoritative skill metrics matching Skill page calculations."""
    eval_scope = "held_out" if scope.lower() == "held_out" else "live"
    target_region = (region or "ALL").strip().upper()
    target_season = (season or "ALL").strip()
    if target_season.upper() in ("ALL", "ALL SEASONS"):
        target_season = "ALL"

    # =========================================================================
    # 1. HELD-OUT 90-DAY TEST BENCHMARK (2026-06-21 to 2026-09-18)
    # =========================================================================
    if eval_scope == "held_out":
        items: List[SkillScoreItem] = []
        if conn is not None:
            try:
                query = """
                    SELECT computed_at, window_days, variable, region, season, lead_days,
                           model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly,
                           evaluation_scope, hits, false_alarms, misses, correct_negatives
                    FROM skill_scores
                    WHERE evaluation_scope = 'held_out'
                """
                params: List[Any] = []
                idx = 1
                if variable:
                    query += f" AND variable = ${idx}"
                    params.append(variable)
                    idx += 1
                if target_region:
                    query += f" AND region = ${idx}"
                    params.append(target_region)
                    idx += 1
                if target_season and target_season != "ALL":
                    query += f" AND season = ${idx}"
                    params.append(target_season)
                    idx += 1

                query += " ORDER BY lead_days ASC, model ASC LIMIT 500"
                rows = await conn.fetch(query, *params)
                if rows:
                    items = [
                        SkillScoreItem(
                            computed_at=r["computed_at"].isoformat() if r["computed_at"] else "",
                            window_days=r["window_days"],
                            variable=r["variable"],
                            region=r["region"],
                            season=r["season"],
                            lead_days=r["lead_days"],
                            model=r["model"],
                            mae=round(float(r["mae"]), 3) if r["mae"] is not None else None,
                            rmse=round(float(r["rmse"]), 3) if r["rmse"] is not None else None,
                            bias=round(float(r["bias"]), 3) if r["bias"] is not None else None,
                            n=r["n"],
                            pod=round(float(r["pod"]), 3) if r["pod"] is not None else None,
                            far=round(float(r["far"]), 3) if r["far"] is not None else None,
                            csi=round(float(r["csi"]), 3) if r["csi"] is not None else None,
                            threshold_mm=float(r["threshold_mm"]) if r["threshold_mm"] is not None else 0.0,
                            is_weekly=r["is_weekly"],
                            evaluation_scope="held_out",
                            hits=r.get("hits"),
                            false_alarms=r.get("false_alarms"),
                            misses=r.get("misses"),
                            correct_negatives=r.get("correct_negatives"),
                        )
                        for r in rows
                    ]
            except Exception as e:
                logger.error(f"Error querying held_out skill_scores: {e}")

        # Fallback to authoritative baseline_comparisons.parquet if table rows empty
        if not items and BASELINE_COMPARISONS_PARQUET.exists():
            try:
                df_base = pd.read_parquet(BASELINE_COMPARISONS_PARQUET)
                if variable:
                    df_base = df_base[df_base["variable"] == variable]

                for _, r in df_base.iterrows():
                    stype = r["slice_type"]
                    sval = r["slice_value"]
                    if stype == "lead_days":
                        row_reg = "ALL"
                        row_seas = "ALL"
                        lead = int(sval)
                    elif stype == "region":
                        row_reg = sval
                        row_seas = "ALL"
                        lead = 1
                    elif stype == "overall":
                        row_reg = "ALL"
                        row_seas = "ALL"
                        lead = 0
                    elif stype == "season":
                        row_reg = "ALL"
                        row_seas = sval
                        lead = 0
                    else:
                        continue

                    if target_region and row_reg != target_region:
                        continue
                    if target_season and target_season != "ALL" and row_seas != target_season:
                        continue

                    cand = CANDIDATE_MAP.get(r["candidate"], r["candidate"].lower())
                    items.append(
                        SkillScoreItem(
                            computed_at="2026-09-19T00:00:00Z",
                            window_days=90,
                            variable=r["variable"],
                            region=row_reg,
                            season=row_seas,
                            lead_days=lead,
                            model=cand,
                            mae=round(float(r["mae"]), 3) if pd.notna(r["mae"]) else None,
                            rmse=round(float(r["rmse"]), 3) if pd.notna(r["rmse"]) else None,
                            bias=round(float(r["bias"]), 3) if pd.notna(r["bias"]) else None,
                            n=int(r["n"]) if pd.notna(r["n"]) else 0,
                            pod=None,
                            far=None,
                            csi=None,
                            threshold_mm=0.0,
                            is_weekly=False,
                            evaluation_scope="held_out",
                        )
                    )
            except Exception as e:
                logger.warning(f"Error reading baseline parquet fallback: {e}")

        return SkillQueryResponse(
            group_by=group_by,
            variable=variable,
            evaluation_scope="held_out",
            effective_window_days=90,
            verified_days_count=90,
            window_start="2026-06-21",
            window_end="2026-09-18",
            latest_verified_date="2026-09-18",
            data_status="HELD-OUT 90-DAY TEST",
            truth_source="IMD 0.25° Gridded Rainfall & ERA5 Climatology (Held-Out Test Block)",
            scores=items,
        )

    # =========================================================================
    # 2. OPERATIONAL LIVE VERIFICATION (max 90 days trailing window)
    # =========================================================================
    if conn is None:
        return SkillQueryResponse(
            group_by=group_by,
            variable=variable,
            evaluation_scope="live",
            effective_window_days=0,
            verified_days_count=0,
            window_start=None,
            window_end=None,
            latest_verified_date=None,
            data_status="NO VERIFICATION DATA",
            truth_source=get_truth_source_label(variable),
            scores=[],
        )

    latest_computed_at_row = await conn.fetchrow(
        "SELECT MAX(computed_at) AS latest FROM skill_scores WHERE evaluation_scope = 'live';"
    )
    latest_computed_at = latest_computed_at_row["latest"] if latest_computed_at_row else None

    if not latest_computed_at:
        return SkillQueryResponse(
            group_by=group_by,
            variable=variable,
            evaluation_scope="live",
            effective_window_days=0,
            verified_days_count=0,
            window_start=None,
            window_end=None,
            latest_verified_date=None,
            data_status="NO VERIFICATION DATA",
            truth_source=get_truth_source_label(variable),
            scores=[],
        )

    query = """
        SELECT computed_at, window_days, variable, region, season, lead_days,
               model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly,
               evaluation_scope, hits, false_alarms, misses, correct_negatives
        FROM skill_scores
        WHERE evaluation_scope = 'live'
          AND computed_at = $1
    """
    params = [latest_computed_at]
    idx = 2

    if variable:
        query += f" AND variable = ${idx}"
        params.append(variable)
        idx += 1

    query += f" AND region = ${idx}"
    params.append(target_region)
    idx += 1

    query += f" AND season = ${idx}"
    params.append(target_season)
    idx += 1

    query += " ORDER BY lead_days ASC, model ASC, threshold_mm ASC LIMIT 500;"

    rows = await conn.fetch(query, *params)

    # If no rows found with season='ALL', try querying without season constraint
    if not rows and target_season == "ALL":
        query_fallback = """
            SELECT computed_at, window_days, variable, region, season, lead_days,
                   model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly,
                   evaluation_scope, hits, false_alarms, misses, correct_negatives
            FROM skill_scores
            WHERE evaluation_scope = 'live'
              AND computed_at = $1
              AND region = $2
        """
        params_fallback = [latest_computed_at, target_region]
        idx_f = 3
        if variable:
            query_fallback += f" AND variable = ${idx_f}"
            params_fallback.append(variable)
            idx_f += 1
        query_fallback += " ORDER BY lead_days ASC, model ASC, threshold_mm ASC LIMIT 500;"
        rows = await conn.fetch(query_fallback, *params_fallback)

    items = [
        SkillScoreItem(
            computed_at=r["computed_at"].isoformat() if r["computed_at"] else "",
            window_days=r["window_days"],
            variable=r["variable"],
            region=r["region"],
            season=r["season"],
            lead_days=r["lead_days"],
            model=r["model"],
            mae=round(float(r["mae"]), 3) if r["mae"] is not None else None,
            rmse=round(float(r["rmse"]), 3) if r["rmse"] is not None else None,
            bias=round(float(r["bias"]), 3) if r["bias"] is not None else None,
            n=r["n"],
            pod=round(float(r["pod"]), 3) if r["pod"] is not None else None,
            far=round(float(r["far"]), 3) if r["far"] is not None else None,
            csi=round(float(r["csi"]), 3) if r["csi"] is not None else None,
            threshold_mm=float(r["threshold_mm"]) if r["threshold_mm"] is not None else 0.0,
            is_weekly=r["is_weekly"],
            evaluation_scope="live",
            hits=r.get("hits"),
            false_alarms=r.get("false_alarms"),
            misses=r.get("misses"),
            correct_negatives=r.get("correct_negatives"),
        )
        for r in rows
    ]

    # Retrieve live window telemetry from pipeline_runs
    effective_window_days = rows[0]["window_days"] if rows else 0
    verified_days_count = effective_window_days
    window_start = None
    window_end = None
    latest_verified_date = None

    run_row = await conn.fetchrow(
        """
        SELECT started_at, message
        FROM pipeline_runs
        WHERE job = 'verify-daily' AND status = 'SUCCESS'
        ORDER BY id DESC
        LIMIT 1;
        """
    )
    if run_row and run_row["message"]:
        msg = run_row["message"]
        m_dates = re.search(r"across (\d+) verified days \((\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2}), effective window: (\d+)d\)", msg)
        if m_dates:
            verified_days_count = int(m_dates.group(1))
            window_start = m_dates.group(2)
            window_end = m_dates.group(3)
            latest_verified_date = m_dates.group(3)
            effective_window_days = int(m_dates.group(4))

    data_status = get_maturity_label(verified_days_count)

    return SkillQueryResponse(
        group_by=group_by,
        variable=variable,
        evaluation_scope="live",
        effective_window_days=effective_window_days,
        verified_days_count=verified_days_count,
        window_start=window_start,
        window_end=window_end,
        latest_verified_date=latest_verified_date,
        data_status=data_status,
        truth_source=get_truth_source_label(variable),
        scores=items,
    )
