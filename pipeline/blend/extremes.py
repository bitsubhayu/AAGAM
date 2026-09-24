"""Extreme Weather Guidance & Alert Rules Engine for AAGAM (Phase 4, PRD §6.5, §8.4).

Evaluates extreme weather hazards for every location and forecast lead (0–7):
  1. Rainfall (FR-EXT-1): Advisory, Watch, Alert + intensity labels (heavy, very heavy, extremely heavy).
  2. Heat Wave (FR-EXT-1): Terrain-aware thresholds (plains 40°C, coastal 37°C, hills 30°C),
     departure from normal (>= 4.5°C, severe > 6.4°C), standalone criteria (>= 45°C, severe >= 47°C),
     and 2-consecutive-day requirement. Includes mandatory disclaimer.
  3. High Wind (FR-EXT-1): Configurable Beaufort defaults (Advisory >= 50, Watch >= 62, Alert >= 75 km/h).
  4. High Uncertainty (FR-EXT-3): Flags when model spread > historical P90.
  5. Alert Object Schema (FR-EXT-2): Accessible, multi-attribute alert representation with
     auto-expiration, agreement counts, model inputs, and audit details.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from pipeline.blend.climatology import HEATWAVE_DISCLAIMER, TmaxClimatologyEngine, load_or_build_climatology
from pipeline.blend.uncertainty import HighUncertaintyEngine, load_or_build_uncertainty_engine
from pipeline.climatology.percentiles import get_rarity_label

logger = logging.getLogger("aagam.pipeline.blend.extremes")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

SEVERITY_TEXT_LABELS = {
    "advisory": "Advisory (Notice)",
    "watch": "Watch (Be Prepared)",
    "alert": "Alert (Take Action)",
}

SEVERITY_RANKS = {
    "advisory": 1,
    "watch": 2,
    "alert": 3,
}


@dataclass
class Alert:
    """Standardized operational alert representation matching PRD §6.5 & database schema."""

    id: Optional[str]
    created_at: str
    valid_date: str
    lead_days: int
    location_id: int
    location_slug: str
    location_name: str
    terrain: str
    region: str
    hazard: str  # 'heavy_rain' | 'heatwave' | 'high_wind' | 'high_uncertainty' | 'heavy_rain_3day'
    severity: str  # 'advisory' | 'watch' | 'alert'
    severity_label: str  # Accessible text label (no color-only reliance)
    value: float  # Forecasted value (mm, °C, km/h, spread)
    agreement: int  # Number of models exceeding threshold (k of 4)
    spread: float  # Forecast spread (standard deviation across models)
    rule: Dict[str, Any]  # Audit details ("why flagged", inputs, thresholds, departure)
    source_models: Dict[str, Optional[float]]  # Raw NWP model forecasts
    degraded: bool  # True if any NWP model input was missing
    status: str  # 'active' | 'expired'
    expires_at: str
    rarity_label: Optional[str] = None
    event_id: Optional[int] = None
    lifecycle_state: Optional[str] = "new"
    previous_severity: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def load_locations_metadata() -> Dict[int, dict]:
    """Loads location metadata (name, slug, region, terrain) mapped by 1-based ID."""
    loc_path = CONFIG_DIR / "locations.yaml"
    with open(loc_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    locations = data.get("locations", [])
    meta = {}
    for idx, loc in enumerate(locations, 1):
        meta[idx] = {
            "id": idx,
            "slug": loc["slug"],
            "name": loc["name"],
            "region": loc["region"],
            "terrain": loc.get("terrain", "plains"),
        }
    return meta


def load_thresholds_config() -> dict:
    """Loads operational thresholds from config/thresholds.yaml."""
    t_path = CONFIG_DIR / "thresholds.yaml"
    with open(t_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_climatology_percentiles_lookup(db_url: Optional[str] = None) -> Dict[Tuple[int, str, str, int], Dict[str, Any]]:
    """Loads all climatology percentiles from PostgreSQL into memory cache.

    Maps (location_id, variable, metric, doy_window) -> percentile dict.
    """
    from core.config import settings

    target_db = db_url or settings.DATABASE_URL
    if not target_db:
        return {}

    try:
        import psycopg2

        conn = psycopg2.connect(target_db)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT location_id, variable, metric, doy_window, mean, p90, p95, p99, n_years
                FROM climatology_percentiles;
            """)
            rows = cur.fetchall()
        conn.close()

        lookup = {}
        for r in rows:
            lookup[(r[0], r[1], r[2], r[3])] = {
                "location_id": r[0],
                "variable": r[1],
                "metric": r[2],
                "doy_window": r[3],
                "mean": float(r[4]) if r[4] is not None else None,
                "p90": float(r[5]) if r[5] is not None else None,
                "p95": float(r[6]) if r[6] is not None else None,
                "p99": float(r[7]) if r[7] is not None else None,
                "n_years": int(r[8]),
            }
        return lookup
    except Exception as e:
        logger.debug(f"Could not load climatology percentiles from DB ({e}); defaulting to empty lookup.")
        return {}


class ExtremeGuidanceEngine:
    """Evaluates multi-hazard extreme weather rules on blended forecasts."""

    def __init__(
        self,
        thresholds_cfg: Optional[dict] = None,
        locations_meta: Optional[Dict[int, dict]] = None,
        climatology_engine: Optional[TmaxClimatologyEngine] = None,
        uncertainty_engine: Optional[HighUncertaintyEngine] = None,
        climatology_percentiles_lookup: Optional[Dict[Tuple[int, str, str, int], Dict[str, Any]]] = None,
    ) -> None:
        self.cfg = thresholds_cfg or load_thresholds_config()
        self.locations_meta = locations_meta or load_locations_metadata()
        self.climatology = climatology_engine or load_or_build_climatology()
        self.uncertainty = uncertainty_engine or load_or_build_uncertainty_engine()
        self.percentiles_lookup = (
            climatology_percentiles_lookup
            if climatology_percentiles_lookup is not None
            else load_climatology_percentiles_lookup()
        )

    def evaluate_rain_hazard(
        self,
        row: dict,
        meta: dict,
        creation_time: dt.datetime,
    ) -> Optional[Alert]:
        """Evaluates PRD §8.4 rainfall rules (Advisory, Watch, Alert + intensity labels)."""
        blended = float(row["blended"])
        spread = float(row.get("spread", 0.0))
        degraded = bool(row.get("degraded", False))
        valid_date_str = str(row["valid_date"])
        lead_days = int(row["lead_days"])
        loc_id = int(row["location_id"])

        m_vals = {
            "gfs": row.get("f_gfs"),
            "ecmwf_ifs": row.get("f_ecmwf_ifs"),
            "icon": row.get("f_icon"),
            "aifs": row.get("f_aifs"),
        }
        valid_m = [v for v in m_vals.values() if v is not None and not pd.isna(v)]

        r_cfg = self.cfg.get("rain", {})
        labels_cfg = r_cfg.get("intensity_labels", {})

        thresh_heavy = float(labels_cfg.get("heavy", 64.5))
        thresh_vheavy = float(labels_cfg.get("very_heavy", 115.6))
        thresh_eheavy = float(labels_cfg.get("extremely_heavy", 204.5))

        # Count models >= 64.5 mm
        models_over_64_5 = sum(1 for v in valid_m if v >= thresh_heavy)

        # Intensity label
        if blended >= thresh_eheavy:
            intensity_label = "extremely_heavy"
        elif blended >= thresh_vheavy:
            intensity_label = "very_heavy"
        elif blended >= thresh_heavy:
            intensity_label = "heavy"
        else:
            intensity_label = "moderate_to_heavy"

        # Check Alert Level in order of precedence: Alert > Watch > Advisory
        severity = None
        condition_met = None

        # 1. ALERT: blended >= 64.5 and >= 3 models >= 64.5
        if blended >= thresh_heavy and models_over_64_5 >= 3:
            severity = "alert"
            condition_met = f"blended ({blended:.1f} mm) >= {thresh_heavy} AND {models_over_64_5} of 4 models >= {thresh_heavy}"
        # 2. WATCH: blended >= 64.5 or >= 2 models >= 64.5
        elif blended >= thresh_heavy or models_over_64_5 >= 2:
            severity = "watch"
            if blended >= thresh_heavy:
                condition_met = f"blended ({blended:.1f} mm) >= {thresh_heavy}"
            else:
                condition_met = f"{models_over_64_5} of 4 models >= {thresh_heavy} mm"
        # 3. ADVISORY: any model >= 64.5 or blended >= 0.8 * 64.5 (51.6 mm)
        elif models_over_64_5 >= 1 or blended >= (0.8 * thresh_heavy):
            severity = "advisory"
            if models_over_64_5 >= 1:
                condition_met = f"{models_over_64_5} model(s) >= {thresh_heavy} mm"
            else:
                condition_met = f"blended ({blended:.1f} mm) >= {0.8 * thresh_heavy:.1f} mm (0.8x threshold)"

        if severity is None:
            return None

        # Climatology percentiles lookup for local extremeness (Phase 13)
        doy = dt.date.fromisoformat(valid_date_str.split("T")[0]).timetuple().tm_yday
        climo = self.percentiles_lookup.get((loc_id, "rain_mm", "1day", doy))
        rarity_label = None
        if climo and climo.get("n_years", 0) >= 15:
            rarity_label = get_rarity_label(
                blended, climo.get("p90"), climo.get("p95"), climo.get("p99"), climo["n_years"]
            )

        exp_time = f"{valid_date_str}T23:59:59Z"
        rule_details = {
            "threshold_mm": thresh_heavy,
            "condition_met": condition_met,
            "intensity_label": intensity_label,
            "models_over_64_5": models_over_64_5,
            "blended_mm": round(blended, 2),
            "ratio_of_threshold": round(blended / thresh_heavy, 3),
        }
        if rarity_label:
            rule_details["rarity_label"] = rarity_label

        alert_id = f"ALERT-RAIN-{loc_id}-{valid_date_str}-L{lead_days}"
        return Alert(
            id=alert_id,
            created_at=creation_time.isoformat(),
            valid_date=valid_date_str,
            lead_days=lead_days,
            location_id=loc_id,
            location_slug=meta["slug"],
            location_name=meta["name"],
            terrain=meta["terrain"],
            region=meta["region"],
            hazard="heavy_rain",
            severity=severity,
            severity_label=SEVERITY_TEXT_LABELS[severity],
            value=round(blended, 2),
            agreement=models_over_64_5,
            spread=round(spread, 3),
            rule=rule_details,
            source_models={k: round(v, 2) if v is not None and not pd.isna(v) else None for k, v in m_vals.items()},
            degraded=degraded,
            status="active",
            expires_at=exp_time,
            rarity_label=rarity_label,
        )

    def evaluate_wind_hazard(
        self,
        row: dict,
        meta: dict,
        creation_time: dt.datetime,
    ) -> Optional[Alert]:
        """Evaluates PRD §8.4 high-wind rules based on configurable Beaufort scale."""
        blended = float(row["blended"])
        spread = float(row.get("spread", 0.0))
        degraded = bool(row.get("degraded", False))
        valid_date_str = str(row["valid_date"])
        lead_days = int(row["lead_days"])
        loc_id = int(row["location_id"])

        m_vals = {
            "gfs": row.get("f_gfs"),
            "ecmwf_ifs": row.get("f_ecmwf_ifs"),
            "icon": row.get("f_icon"),
            "aifs": row.get("f_aifs"),
        }
        valid_m = [v for v in m_vals.values() if v is not None and not pd.isna(v)]

        w_cfg = self.cfg.get("wind", {})
        t_alert = float(w_cfg.get("alert", 75.0))
        t_watch = float(w_cfg.get("watch", 62.0))
        t_advisory = float(w_cfg.get("advisory", 50.0))

        models_over_advisory = sum(1 for v in valid_m if v >= t_advisory)

        severity = None
        condition_met = None
        applied_threshold = None

        if blended >= t_alert:
            severity = "alert"
            applied_threshold = t_alert
            condition_met = f"blended wind ({blended:.1f} km/h) >= {t_alert} km/h (Strong Gale)"
        elif blended >= t_watch:
            severity = "watch"
            applied_threshold = t_watch
            condition_met = f"blended wind ({blended:.1f} km/h) >= {t_watch} km/h (Gale)"
        elif blended >= t_advisory:
            severity = "advisory"
            applied_threshold = t_advisory
            condition_met = f"blended wind ({blended:.1f} km/h) >= {t_advisory} km/h (Moderate Gale)"

        if severity is None:
            return None

        # Climatology percentiles lookup for local extremeness (Phase 13)
        doy = dt.date.fromisoformat(valid_date_str.split("T")[0]).timetuple().tm_yday
        climo = self.percentiles_lookup.get((loc_id, "wind_max_kmh", "1day", doy))
        rarity_label = None
        if climo and climo.get("n_years", 0) >= 15:
            rarity_label = get_rarity_label(
                blended, climo.get("p90"), climo.get("p95"), climo.get("p99"), climo["n_years"]
            )

        exp_time = f"{valid_date_str}T23:59:59Z"
        rule_details = {
            "applied_threshold_kmh": applied_threshold,
            "condition_met": condition_met,
            "blended_kmh": round(blended, 2),
            "models_over_50kmh": models_over_advisory,
            "scale": "Beaufort scale gale thresholds (IMD/NDMA guidance)",
        }
        if rarity_label:
            rule_details["rarity_label"] = rarity_label

        alert_id = f"ALERT-WIND-{loc_id}-{valid_date_str}-L{lead_days}"
        return Alert(
            id=alert_id,
            created_at=creation_time.isoformat(),
            valid_date=valid_date_str,
            lead_days=lead_days,
            location_id=loc_id,
            location_slug=meta["slug"],
            location_name=meta["name"],
            terrain=meta["terrain"],
            region=meta["region"],
            hazard="high_wind",
            severity=severity,
            severity_label=SEVERITY_TEXT_LABELS[severity],
            value=round(blended, 2),
            agreement=models_over_advisory,
            spread=round(spread, 3),
            rule=rule_details,
            source_models={k: round(v, 2) if v is not None and not pd.isna(v) else None for k, v in m_vals.items()},
            degraded=degraded,
            status="active",
            expires_at=exp_time,
            rarity_label=rarity_label,
        )

    def check_heatwave_condition_single_day(
        self,
        tmax: float,
        loc_id: int,
        terrain: str,
        doy: int,
    ) -> Tuple[Optional[str], dict]:
        """Checks if a single day satisfies terrain/departure/absolute heatwave criteria.

        Returns:
            Tuple of (qualifying_severity, info_dict).
        """
        hw_cfg = self.cfg.get("heatwave", {})
        t_by_terrain = hw_cfg.get("thresholds_by_terrain", {}).get(terrain, {})
        t_min = float(t_by_terrain.get("absolute_min_tmax", 40.0))
        dep_hw = float(t_by_terrain.get("normal_departure_heatwave", 4.5))
        dep_severe = float(t_by_terrain.get("normal_departure_severe", 6.4))

        standalone_cfg = hw_cfg.get("standalone_criteria", {})
        abs_hw = float(standalone_cfg.get("heatwave_anywhere", 45.0))
        abs_severe = float(standalone_cfg.get("severe_heatwave_anywhere", 47.0))

        normal_tmax = self.climatology.get_normal(loc_id, doy)
        departure = tmax - normal_tmax

        severity = None
        reason = None

        # Check severe heat wave first
        if (tmax >= t_min and departure > dep_severe) or (tmax >= abs_severe):
            severity = "alert"
            if tmax >= abs_severe:
                reason = f"Tmax ({tmax:.1f}°C) >= {abs_severe}°C (Standalone Severe)"
            else:
                reason = f"Tmax ({tmax:.1f}°C) >= {t_min}°C AND departure (+{departure:.1f}°C) > {dep_severe}°C"
        elif (tmax >= t_min and departure >= dep_hw) or (tmax >= abs_hw):
            severity = "watch"
            if tmax >= abs_hw:
                reason = f"Tmax ({tmax:.1f}°C) >= {abs_hw}°C (Standalone Heat Wave)"
            else:
                reason = f"Tmax ({tmax:.1f}°C) >= {t_min}°C AND departure (+{departure:.1f}°C) >= {dep_hw}°C"

        info = {
            "tmax": round(tmax, 2),
            "terrain": terrain,
            "terrain_min_tmax": t_min,
            "normal_tmax": round(normal_tmax, 2),
            "departure": round(departure, 2),
            "condition_met": reason,
            "normal_source": self.climatology.metadata.source,
            "disclaimer": HEATWAVE_DISCLAIMER,
        }
        return severity, info

    def evaluate_heatwave_hazards_for_location(
        self,
        loc_df: pd.DataFrame,
        meta: dict,
        creation_time: dt.datetime,
    ) -> List[Alert]:
        """Evaluates heatwave rules enforcing the 2-consecutive-day requirement.

        Takes a DataFrame of Tmax forecasts for one location across valid dates.
        """
        alerts: List[Alert] = []
        loc_df = loc_df.sort_values("valid_date").reset_index(drop=True)
        n_days = len(loc_df)
        if n_days == 0:
            return alerts

        loc_id = meta["id"]
        terrain = meta["terrain"]

        # Step 1: Evaluate single-day criteria for all dates in sequence
        day_evals = []
        for _, row in loc_df.iterrows():
            tmax = float(row["blended"])
            d_obj = pd.to_datetime(row["valid_date"])
            doy = d_obj.dayofyear
            sev, info = self.check_heatwave_condition_single_day(tmax, loc_id, terrain, doy)
            day_evals.append({"row": row, "severity": sev, "info": info})

        # Step 2: Enforce 2-consecutive-day requirement
        for i in range(n_days):
            curr = day_evals[i]
            curr_sev = curr["severity"]
            if curr_sev is None:
                continue

            # Check if adjacent day also meets condition
            has_prev = (i > 0 and day_evals[i - 1]["severity"] is not None)
            has_next = (i < n_days - 1 and day_evals[i + 1]["severity"] is not None)
            is_two_consecutive = has_prev or has_next

            row = curr["row"]
            valid_date_str = str(row["valid_date"])
            lead_days = int(row["lead_days"])
            spread = float(row.get("spread", 0.0))
            degraded = bool(row.get("degraded", False))

            m_vals = {
                "gfs": row.get("f_gfs"),
                "ecmwf_ifs": row.get("f_ecmwf_ifs"),
                "icon": row.get("f_icon"),
                "aifs": row.get("f_aifs"),
            }
            valid_m = [v for v in m_vals.values() if v is not None and not pd.isna(v)]
            models_over_hw = sum(1 for v in valid_m if v >= curr["info"]["terrain_min_tmax"])

            if is_two_consecutive:
                # Confirmed Heat Wave Watch or Alert
                sev = curr_sev
                consec_desc = "2 consecutive days condition satisfied"
            else:
                # Single day condition met without 2nd consecutive day -> downgraded to Advisory
                sev = "advisory"
                consec_desc = "single day condition met (2nd consecutive day required for Watch/Alert)"

            # Climatology percentiles lookup for local extremeness (Phase 13)
            doy = dt.date.fromisoformat(valid_date_str.split("T")[0]).timetuple().tm_yday
            climo = self.percentiles_lookup.get((loc_id, "tmax_c", "1day", doy))
            rarity_label = None
            if climo and climo.get("n_years", 0) >= 15:
                rarity_label = get_rarity_label(
                    curr["info"]["tmax"], climo.get("p90"), climo.get("p95"), climo.get("p99"), climo["n_years"]
                )

            rule_details = dict(curr["info"])
            rule_details["consecutive_days_status"] = consec_desc
            if rarity_label:
                rule_details["rarity_label"] = rarity_label

            alert_id = f"ALERT-HEAT-{loc_id}-{valid_date_str}-L{lead_days}"
            alerts.append(
                Alert(
                    id=alert_id,
                    created_at=creation_time.isoformat(),
                    valid_date=valid_date_str,
                    lead_days=lead_days,
                    location_id=loc_id,
                    location_slug=meta["slug"],
                    location_name=meta["name"],
                    terrain=terrain,
                    region=meta["region"],
                    hazard="heatwave",
                    severity=sev,
                    severity_label=SEVERITY_TEXT_LABELS[sev],
                    value=curr["info"]["tmax"],
                    agreement=models_over_hw,
                    spread=round(spread, 3),
                    rule=rule_details,
                    source_models={k: round(v, 2) if v is not None and not pd.isna(v) else None for k, v in m_vals.items()},
                    degraded=degraded,
                    status="active",
                    expires_at=f"{valid_date_str}T23:59:59Z",
                    rarity_label=rarity_label,
                )
            )

        return alerts

    def evaluate_uncertainty_hazard(
        self,
        row: dict,
        meta: dict,
        creation_time: dt.datetime,
    ) -> Optional[Alert]:
        """Evaluates FR-EXT-3 high uncertainty flag when spread > historical P90."""
        spread = float(row.get("spread", 0.0))
        if pd.isna(spread) or spread <= 0.0:
            return None

        var = str(row["variable"])
        lead = int(row["lead_days"])
        reg = str(row["region"])
        seas = str(row["season"])
        regime = str(row["regime"])
        loc_id = int(row["location_id"])
        valid_date_str = str(row["valid_date"])
        degraded = bool(row.get("degraded", False))

        is_high, p90, bucket_desc = self.uncertainty.evaluate_uncertainty(
            var, lead, reg, seas, regime, spread
        )

        if not is_high:
            return None

        m_vals = {
            "gfs": row.get("f_gfs"),
            "ecmwf_ifs": row.get("f_ecmwf_ifs"),
            "icon": row.get("f_icon"),
            "aifs": row.get("f_aifs"),
        }

        rule_details = {
            "variable": var,
            "spread": round(spread, 3),
            "p90_threshold": round(p90, 3),
            "bucket_used": bucket_desc,
            "condition_met": f"model spread ({spread:.2f}) exceeds historical P90 ({p90:.2f}) for {var}",
        }

        alert_id = f"ALERT-UNCERT-{var}-{loc_id}-{valid_date_str}-L{lead}"
        return Alert(
            id=alert_id,
            created_at=creation_time.isoformat(),
            valid_date=valid_date_str,
            lead_days=lead,
            location_id=loc_id,
            location_slug=meta["slug"],
            location_name=meta["name"],
            terrain=meta["terrain"],
            region=meta["region"],
            hazard="high_uncertainty",
            severity="advisory",
            severity_label=SEVERITY_TEXT_LABELS["advisory"],
            value=round(spread, 3),
            agreement=0,
            spread=round(spread, 3),
            rule=rule_details,
            source_models={k: round(v, 2) if v is not None and not pd.isna(v) else None for k, v in m_vals.items()},
            degraded=degraded,
            status="active",
            expires_at=f"{valid_date_str}T23:59:59Z",
        )

    def evaluate_heavy_rain_3day_hazards_for_location(
        self,
        loc_df: pd.DataFrame,
        meta: dict,
        creation_time: dt.datetime,
    ) -> List[Alert]:
        """Evaluates PRD §6.11 FR-CLIMO-3 rolling 3-day rainfall sums across forecast horizon.

        Rolling 3-day blended-rain sums across the 7-day horizon (yielding up to 5 overlapping windows)
        are compared to (location, 'rain_mm', '3day_sum', doy_window).
        Severity (PRD §8.4):
          - Alert: 3-day sum >= p99
          - Watch: 3-day sum >= p95
          - Advisory: 3-day sum >= p90
        If climatology is missing or n_years < 15, alerts are suppressed (FR-CLIMO-4).
        """
        alerts: List[Alert] = []
        if loc_df.empty:
            return alerts

        df_sorted = loc_df.sort_values("valid_date").reset_index(drop=True)
        n_days = len(df_sorted)
        if n_days < 3:
            return alerts

        loc_id = int(meta["id"])
        dates = [dt.date.fromisoformat(str(d).split("T")[0]) for d in df_sorted["valid_date"]]
        blended_vals = df_sorted["blended"].to_numpy(dtype=float)
        leads = df_sorted["lead_days"].to_numpy(dtype=int)

        # Pre-extract model series
        gfs_vals = df_sorted.get("f_gfs", pd.Series([None] * n_days)).to_numpy(dtype=float)
        ifs_vals = df_sorted.get("f_ecmwf_ifs", pd.Series([None] * n_days)).to_numpy(dtype=float)
        icon_vals = df_sorted.get("f_icon", pd.Series([None] * n_days)).to_numpy(dtype=float)
        aifs_vals = df_sorted.get("f_aifs", pd.Series([None] * n_days)).to_numpy(dtype=float)

        for i in range(n_days - 2):
            d_start = dates[i]
            d_end = dates[i + 2]

            # Verify contiguous 3 days
            if (d_end - d_start).days != 2:
                continue

            sum_3d = float(blended_vals[i] + blended_vals[i + 1] + blended_vals[i + 2])
            lead_end = int(leads[i + 2])
            valid_date_str = str(d_end)
            doy_end = d_end.timetuple().tm_yday

            # Lookup climatology for 3-day sum
            climo = self.percentiles_lookup.get((loc_id, "rain_mm", "3day_sum", doy_end))
            if not climo or climo.get("n_years", 0) < 15 or climo.get("p90") is None:
                # Suppress alert if insufficient history
                continue

            p90 = climo["p90"]
            p95 = climo["p95"]
            p99 = climo["p99"]
            n_years = climo["n_years"]

            severity = None
            if p99 is not None and sum_3d >= p99:
                severity = "alert"
            elif p95 is not None and sum_3d >= p95:
                severity = "watch"
            elif p90 is not None and sum_3d >= p90:
                severity = "advisory"

            if severity is None:
                continue

            rarity_label = get_rarity_label(sum_3d, p90, p95, p99, n_years)

            # Model consensus on 3-day sum
            m_sums: Dict[str, Optional[float]] = {}
            for m_name, m_arr in [("gfs", gfs_vals), ("ecmwf_ifs", ifs_vals), ("icon", icon_vals), ("aifs", aifs_vals)]:
                if not np.isnan(m_arr[i]) and not np.isnan(m_arr[i + 1]) and not np.isnan(m_arr[i + 2]):
                    m_sums[m_name] = float(m_arr[i] + m_arr[i + 1] + m_arr[i + 2])
                else:
                    m_sums[m_name] = None

            valid_m_sums = [v for v in m_sums.values() if v is not None]
            models_over = sum(1 for v in valid_m_sums if p90 is not None and v >= p90)
            spread = float(np.std(valid_m_sums)) if len(valid_m_sums) > 1 else 0.0

            thresh_applied = p99 if severity == "alert" else (p95 if severity == "watch" else p90)
            rule_details = {
                "window_days": 3,
                "start_date": str(d_start),
                "end_date": str(d_end),
                "sum_3day_mm": round(sum_3d, 2),
                "p90": p90,
                "p95": p95,
                "p99": p99,
                "n_years": n_years,
                "threshold_applied": thresh_applied,
                "condition_met": f"3-day accumulated rainfall ({sum_3d:.1f} mm) >= {severity} threshold ({thresh_applied} mm)",
            }
            if rarity_label:
                rule_details["rarity_label"] = rarity_label

            alert_id = f"ALERT-RAIN3D-{loc_id}-{valid_date_str}-L{lead_end}"
            alerts.append(
                Alert(
                    id=alert_id,
                    created_at=creation_time.isoformat(),
                    valid_date=valid_date_str,
                    lead_days=lead_end,
                    location_id=loc_id,
                    location_slug=meta["slug"],
                    location_name=meta["name"],
                    terrain=meta["terrain"],
                    region=meta["region"],
                    hazard="heavy_rain_3day",
                    severity=severity,
                    severity_label=SEVERITY_TEXT_LABELS[severity],
                    value=round(sum_3d, 2),
                    agreement=models_over,
                    spread=round(spread, 3),
                    rule=rule_details,
                    source_models={k: round(v, 2) if v is not None else None for k, v in m_sums.items()},
                    degraded=len(valid_m_sums) < 4,
                    status="active",
                    expires_at=f"{valid_date_str}T23:59:59Z",
                    rarity_label=rarity_label,
                )
            )

        return alerts

    def evaluate_all(
        self,
        df: pd.DataFrame,
        creation_time: Optional[dt.datetime] = None,
    ) -> List[Alert]:
        """Runs multi-hazard evaluation across entire forecast dataset.

        Returns list of all generated Alert objects.
        """
        c_time = creation_time or dt.datetime.now(dt.timezone.utc)
        alerts: List[Alert] = []

        # 1. Rain hazards & uncertainty on rain rows
        df_rain = df[df["variable"] == "rain_mm"]
        for _, row in df_rain.iterrows():
            loc_id = int(row["location_id"])
            meta = self.locations_meta.get(loc_id, {"id": loc_id, "slug": f"loc_{loc_id}", "name": f"Location {loc_id}", "terrain": "plains", "region": row.get("region", "CENTRAL")})
            a_rain = self.evaluate_rain_hazard(row.to_dict(), meta, c_time)
            if a_rain:
                alerts.append(a_rain)
            a_unc = self.evaluate_uncertainty_hazard(row.to_dict(), meta, c_time)
            if a_unc:
                alerts.append(a_unc)

        # 2. Wind hazards & uncertainty on wind rows
        df_wind = df[df["variable"] == "wind_max_kmh"]
        for _, row in df_wind.iterrows():
            loc_id = int(row["location_id"])
            meta = self.locations_meta.get(loc_id, {"id": loc_id, "slug": f"loc_{loc_id}", "name": f"Location {loc_id}", "terrain": "plains", "region": row.get("region", "CENTRAL")})
            a_wind = self.evaluate_wind_hazard(row.to_dict(), meta, c_time)
            if a_wind:
                alerts.append(a_wind)
            a_unc = self.evaluate_uncertainty_hazard(row.to_dict(), meta, c_time)
            if a_unc:
                alerts.append(a_unc)

        # 3. Heatwave hazards (evaluated per location sequence for 2-consecutive-day rule)
        df_tmax = df[df["variable"] == "tmax_c"]
        for loc_id, loc_df in df_tmax.groupby("location_id"):
            meta = self.locations_meta.get(int(loc_id), {"id": int(loc_id), "slug": f"loc_{loc_id}", "name": f"Location {loc_id}", "terrain": "plains", "region": "CENTRAL"})
            hw_alerts = self.evaluate_heatwave_hazards_for_location(loc_df, meta, c_time)
            alerts.extend(hw_alerts)

            # Also check uncertainty on tmax
            for _, row in loc_df.iterrows():
                a_unc = self.evaluate_uncertainty_hazard(row.to_dict(), meta, c_time)
                if a_unc:
                    alerts.append(a_unc)

        # 4. 3-Day Heavy Rainfall hazards evaluated across location sequences (PRD §6.11 FR-CLIMO-3)
        for loc_id, loc_df in df_rain.groupby("location_id"):
            meta = self.locations_meta.get(int(loc_id), {"id": int(loc_id), "slug": f"loc_{loc_id}", "name": f"Location {loc_id}", "terrain": "plains", "region": "CENTRAL"})
            h3_alerts = self.evaluate_heavy_rain_3day_hazards_for_location(loc_df, meta, c_time)
            alerts.extend(h3_alerts)

        # Deduplicate and merge alerts by unique occurrence key (location_id, hazard, valid_date, lead_days)
        # to ensure compatibility with database unique constraint
        deduped: Dict[Tuple[int, str, str, int], Alert] = {}
        for a in alerts:
            key = (int(a.location_id), str(a.hazard), str(a.valid_date), int(a.lead_days))
            if key not in deduped:
                deduped[key] = a
            else:
                existing = deduped[key]
                if a.hazard == "high_uncertainty":
                    if (a.spread or 0) > (existing.spread or 0):
                        if isinstance(existing.rule, dict) and isinstance(a.rule, dict):
                            prev_vars = existing.rule.get("variables", [existing.rule.get("variable")])
                            a.rule["variables"] = list(dict.fromkeys(prev_vars + [a.rule.get("variable")]))
                        deduped[key] = a
                    else:
                        if isinstance(existing.rule, dict) and isinstance(a.rule, dict):
                            curr_vars = a.rule.get("variables", [a.rule.get("variable")])
                            existing.rule["variables"] = list(dict.fromkeys(existing.rule.get("variables", [existing.rule.get("variable")]) + curr_vars))
                else:
                    rank_new = SEVERITY_RANKS.get(str(a.severity).lower(), 0)
                    rank_old = SEVERITY_RANKS.get(str(existing.severity).lower(), 0)
                    if rank_new > rank_old or (rank_new == rank_old and (a.value or 0) > (existing.value or 0)):
                        deduped[key] = a

        return list(deduped.values())


