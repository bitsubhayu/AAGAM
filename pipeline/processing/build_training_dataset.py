"""Training Dataset Construction Engine for AAGAM (PRD §7.3 & §8).

Joins previous runs forecasts with ground truth observations.
Produces Parquet file adhering to the exact AAGAM design:
Columns:
- valid_date
- location_id
- variable ('rain_mm', 'tmax_c', 'wind_max_kmh')
- lead_days (1..7)
- truth
- truth_source ('imd_gridded', 'era5_historical')
- f_gfs
- f_ifs
- f_icon
- f_aifs
- mean
- std
- max
- min
- doy_sin
- doy_cos
- lat
- lon
- region
- season
- regime
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import psycopg2

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings
from pipeline.processing.aggregation import validate_alignment_keys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.processing.training_dataset")

FORECASTS_PARQUET = Path(__file__).resolve().parent.parent.parent / "data" / "forecasts_backfill.parquet"
TRUTH_PARQUET = Path(__file__).resolve().parent.parent.parent / "data" / "truth.parquet"
TRAINING_PARQUET = Path(__file__).resolve().parent.parent.parent / "data" / "training_dataset.parquet"


def get_season(dt: date) -> str:
    """Classifies Indian meteorological season."""
    m = dt.month
    if m in (1, 2):
        return "winter"
    elif m in (3, 4, 5):
        return "pre_monsoon"
    elif m in (6, 7, 8, 9):
        return "monsoon"
    else:
        return "post_monsoon"


def get_regime(var: str, consensus_mean: float) -> str:
    """Classifies consensus weather regime per PRD §8.1."""
    if pd.isna(consensus_mean):
        return "unknown"

    if var == "rain_mm":
        if consensus_mean < 2.5:
            return "dry_or_very_light"
        elif consensus_mean <= 15.5:
            return "light_rain"
        elif consensus_mean <= 64.4:
            return "moderate_rain"
        else:
            return "heavy_rain"
    elif var == "tmax_c":
        if consensus_mean < 35.0:
            return "normal"
        elif consensus_mean <= 40.0:
            return "warm"
        else:
            return "heat_wave"
    elif var == "wind_max_kmh":
        if consensus_mean < 20.0:
            return "calm_light"
        elif consensus_mean <= 40.0:
            return "moderate"
        else:
            return "high_wind"
    return "unknown"


def build_joined_training_dataset() -> Dict[str, Any]:
    """Loads forecasts and truth, pivots models, computes engineered features, and writes Parquet."""
    if not FORECASTS_PARQUET.exists():
        raise FileNotFoundError(f"Missing forecasts parquet: {FORECASTS_PARQUET}")
    if not TRUTH_PARQUET.exists():
        raise FileNotFoundError(f"Missing truth parquet: {TRUTH_PARQUET}")

    logger.info(f"Loading forecasts from {FORECASTS_PARQUET}...")
    df_fcst = pd.read_parquet(FORECASTS_PARQUET)

    logger.info(f"Loading truth from {TRUTH_PARQUET}...")
    df_truth = pd.read_parquet(TRUTH_PARQUET)

    # Fetch locations metadata
    conn = psycopg2.connect(settings.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT id, region, ST_Y(geog::geometry), ST_X(geog::geometry) FROM locations;")
        loc_rows = cur.fetchall()
    conn.close()

    loc_meta = {
        r[0]: {"region": r[1], "lat": float(r[2]), "lon": float(r[3])}
        for r in loc_rows
    }

    # Reshape forecasts: melt variables to long format
    logger.info("Reshaping forecasts to variable-level granularity...")

    # Columns in df_fcst: location_id, model, valid_date, lead_days, f_rain_mm, f_tmax_c, f_wind_max_kmh
    melted_rain = df_fcst[["location_id", "model", "valid_date", "lead_days", "f_rain_mm"]].rename(
        columns={"f_rain_mm": "fcst_val"}
    )
    melted_rain["variable"] = "rain_mm"

    melted_temp = df_fcst[["location_id", "model", "valid_date", "lead_days", "f_tmax_c"]].rename(
        columns={"f_tmax_c": "fcst_val"}
    )
    melted_temp["variable"] = "tmax_c"

    melted_wind = df_fcst[["location_id", "model", "valid_date", "lead_days", "f_wind_max_kmh"]].rename(
        columns={"f_wind_max_kmh": "fcst_val"}
    )
    melted_wind["variable"] = "wind_max_kmh"

    df_fcst_long = pd.concat([melted_rain, melted_temp, melted_wind], ignore_index=True)

    # Pivot models into separate columns: f_gfs, f_ifs, f_icon, f_aifs
    pivoted = df_fcst_long.pivot_table(
        index=["valid_date", "location_id", "variable", "lead_days"],
        columns="model",
        values="fcst_val",
        aggfunc="first",
    ).reset_index()

    # Ensure all 4 model columns exist
    for m in ["gfs", "ecmwf_ifs", "icon", "aifs"]:
        col_name = f"f_{m}"
        if m in pivoted.columns:
            pivoted[col_name] = pivoted[m]
        else:
            pivoted[col_name] = np.nan

    model_cols = ["f_gfs", "f_ecmwf_ifs", "f_icon", "f_aifs"]

    # Compute consensus statistics across available models
    pivoted["mean"] = pivoted[model_cols].mean(axis=1)
    pivoted["std"] = pivoted[model_cols].std(axis=1).fillna(0.0)
    pivoted["max"] = pivoted[model_cols].max(axis=1)
    pivoted["min"] = pivoted[model_cols].min(axis=1)

    # Reshape truth: melt variables to match
    truth_rain = df_truth[["location_id", "valid_date", "rain_truth", "rain_truth_source"]].rename(
        columns={"rain_truth": "truth", "rain_truth_source": "truth_source"}
    )
    truth_rain["variable"] = "rain_mm"

    truth_temp = df_truth[["location_id", "valid_date", "tmax_truth", "temp_truth_source"]].rename(
        columns={"tmax_truth": "truth", "temp_truth_source": "truth_source"}
    )
    truth_temp["variable"] = "tmax_c"

    truth_wind = df_truth[["location_id", "valid_date", "wind_max_truth", "wind_truth_source"]].rename(
        columns={"wind_max_truth": "truth", "wind_truth_source": "truth_source"}
    )
    truth_wind["variable"] = "wind_max_kmh"

    df_truth_long = pd.concat([truth_rain, truth_temp, truth_wind], ignore_index=True)

    logger.info("Joining forecasts and truth tables...")
    joined = pd.merge(
        pivoted,
        df_truth_long,
        on=["valid_date", "location_id", "variable"],
        how="inner",
    )

    # Add metadata features
    joined["lat"] = joined["location_id"].map(lambda x: loc_meta.get(x, {}).get("lat", np.nan))
    joined["lon"] = joined["location_id"].map(lambda x: loc_meta.get(x, {}).get("lon", np.nan))
    joined["region"] = joined["location_id"].map(lambda x: loc_meta.get(x, {}).get("region", "unknown"))

    # Day of year cyclical encoding
    doy = pd.to_datetime(joined["valid_date"]).dt.dayofyear
    joined["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    joined["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # Season and regime
    joined["season"] = joined["valid_date"].apply(get_season)
    joined["regime"] = joined.apply(lambda r: get_regime(r["variable"], r["mean"]), axis=1)

    # Select and order columns per PRD §7.3
    final_cols = [
        "valid_date", "location_id", "variable", "lead_days",
        "truth", "truth_source",
        "f_gfs", "f_ecmwf_ifs", "f_icon", "f_aifs",
        "mean", "std", "max", "min",
        "doy_sin", "doy_cos", "lat", "lon", "region", "season", "regime"
    ]
    df_training = joined[final_cols].sort_values(
        ["valid_date", "location_id", "variable", "lead_days"]
    ).reset_index(drop=True)

    # Validation
    val_report = validate_alignment_keys(df_training, keys=("location_id", "valid_date", "variable", "lead_days"))

    # Write to Parquet
    TRAINING_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_training.to_parquet(TRAINING_PARQUET, index=False, engine="pyarrow", compression="snappy")
    logger.info(f"Saved completed training Parquet to {TRAINING_PARQUET}")

    # Print comprehensive statistics
    total_rows = len(df_training)
    date_min = df_training["valid_date"].min()
    date_max = df_training["valid_date"].max()
    num_locations = df_training["location_id"].nunique()
    variables = df_training["variable"].unique().tolist()
    lead_days = sorted(df_training["lead_days"].unique().tolist())
    truth_sources = df_training["truth_source"].value_counts().to_dict()

    print("\n" + "=" * 60)
    print("AAGAM PHASE 1 TRAINING PARQUET SUMMARY")
    print("=" * 60)
    print(f"File Path:          {TRAINING_PARQUET}")
    print(f"Total Rows:         {total_rows:,}")
    print(f"Date Range:         {date_min} to {date_max}")
    print(f"Locations Count:    {num_locations} / 40")
    print(f"Variables:          {variables}")
    print(f"Lead Days:          {lead_days}")
    print(f"Duplicate Keys:     {val_report['duplicate_count']}")
    print(f"Anomalies:          {val_report['anomalies']}")
    print(f"Truth Sources:      {truth_sources}")
    print(f"Missing (NaNs):     {val_report['nan_counts']}")
    print("=" * 60 + "\n")

    return {
        "parquet_path": str(TRAINING_PARQUET),
        "total_rows": total_rows,
        "date_range": (str(date_min), str(date_max)),
        "locations_count": num_locations,
        "variables": variables,
        "lead_days": lead_days,
        "truth_sources": truth_sources,
        "duplicate_count": val_report["duplicate_count"],
        "validation_report": val_report,
    }


if __name__ == "__main__":
    build_joined_training_dataset()
