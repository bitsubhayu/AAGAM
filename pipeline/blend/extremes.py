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

import pandas as pd
import yaml

from pipeline.blend.climatology import HEATWAVE_DISCLAIMER, TmaxClimatologyEngine, load_or_build_climatology
from pipeline.blend.uncertainty import HighUncertaintyEngine, load_or_build_uncertainty_engine

logger = logging.getLogger("aagam.pipeline.blend.extremes")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

SEVERITY_TEXT_LABELS = {
    "advisory": "Advisory (Notice)",
    "watch": "Watch (Be Prepared)",
    "alert": "Alert (Take Action)",
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
    hazard: str  # 'heavy_rain' | 'heatwave' | 'high_wind' | 'high_uncertainty'
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


class ExtremeGuidanceEngine:
    """Evaluates multi-hazard extreme weather rules on blended forecasts."""

    def __init__(
        self,
        thresholds_cfg: Optional[dict] = None,
        locations_meta: Optional[Dict[int, dict]] = None,
        climatology_engine: Optional[TmaxClimatologyEngine] = None,
        uncertainty_engine: Optional[HighUncertaintyEngine] = None,
    ) -> None:
        self.cfg = thresholds_cfg or load_thresholds_config()
        self.locations_meta = locations_meta or load_locations_metadata()
        self.climatology = climatology_engine or load_or_build_climatology()
        self.uncertainty = uncertainty_engine or load_or_build_uncertainty_engine()

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

        exp_time = f"{valid_date_str}T23:59:59Z"
        rule_details = {
            "threshold_mm": thresh_heavy,
            "condition_met": condition_met,
            "intensity_label": intensity_label,
            "models_over_64_5": models_over_64_5,
            "blended_mm": round(blended, 2),
            "ratio_of_threshold": round(blended / thresh_heavy, 3),
        }

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

        exp_time = f"{valid_date_str}T23:59:59Z"
        rule_details = {
            "applied_threshold_kmh": applied_threshold,
            "condition_met": condition_met,
            "blended_kmh": round(blended, 2),
            "models_over_50kmh": models_over_advisory,
            "scale": "Beaufort scale gale thresholds (IMD/NDMA guidance)",
        }

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

            rule_details = dict(curr["info"])
            rule_details["consecutive_days_status"] = consec_desc

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
            "spread": round(spread, 3),
            "p90_threshold": round(p90, 3),
            "bucket_used": bucket_desc,
            "condition_met": f"model spread ({spread:.2f}) exceeds historical P90 ({p90:.2f})",
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

        return alerts
