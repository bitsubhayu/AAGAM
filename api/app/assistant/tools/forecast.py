"""get_forecast tool implementation (PRD §9.4).

Retrieves latest blended and per-model forecasts for a location:
- Resolves location server-side against 40 authoritative locations
- Returns latest blended + each model (GFS, ECMWF IFS, ICON, AIFS), spread, and models over threshold
- Formats into standard ToolEnvelope with compact preview and stats
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from api.app.assistant.location_resolver import resolve_location
from api.app.assistant.schemas import GetForecastArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact
from api.app.db.model_versions import get_active_model_version_cached

logger = logging.getLogger("aagam.assistant.tools.forecast")


class GetForecastTool(BaseTool):
    name = "get_forecast"
    description = (
        "Latest blended forecast and per-model values for one location (rain_mm, tmax_c, wind_max_kmh). "
        "Use whenever querying the weather forecast, rain likelihood, or temperature/wind values for a specific city or station."
    )
    args_model = GetForecastArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = GetForecastArgs(**raw_args)

        # 1. Resolve location server-side
        loc_res = resolve_location(args.location)
        if not loc_res["resolved"]:
            # Ambiguous or out of scope
            return ToolEnvelope(
                ok=False,
                artifact_id="none",
                title=f"Location resolution failed for '{args.location}'",
                columns=["status", "message", "candidates"],
                n_rows=1,
                preview=[["error", loc_res["message"], loc_res.get("candidates", [])]],
                stats={},
                meta={"resolved": False, "query": args.location},
            )

        location = loc_res["location"]
        location_id = location["id"]
        location_name = location["name"]

        active_version = "active"
        if context.conn is not None:
            v = await get_active_model_version_cached(context.conn)
            if v:
                active_version = v.get("name") or v.get("storage_path") or f"version-{v.get('id', 1)}"

        # 2. Query database for blended and per-model forecasts
        columns = [
            "valid_date",
            "blended",
            "gfs",
            "ecmwf_ifs",
            "icon",
            "aifs",
            "spread",
            "models_over_threshold",
        ]
        full_rows: List[Dict[str, Any]] = []

        if context.conn is not None:
            try:
                # Fetch blended forecasts
                q_blend = """
                    SELECT valid_date, lead_days, issue_time, blended, spread, models_over_threshold
                    FROM blended_forecasts
                    WHERE location_id = $1 AND variable = $2 AND lead_days <= $3
                    ORDER BY valid_date ASC
                """
                blend_rows = await context.conn.fetch(q_blend, location_id, args.variable, args.lead_days_max)

                # Fetch model forecasts
                q_models = """
                    SELECT valid_date, model, value
                    FROM model_forecasts
                    WHERE location_id = $1 AND variable = $2 AND lead_days <= $3
                """
                model_rows = await context.conn.fetch(q_models, location_id, args.variable, args.lead_days_max)

                # Map model rows by (valid_date, model)
                model_map: Dict[tuple[str, str], float] = {}
                for mr in model_rows:
                    vd_str = mr["valid_date"].isoformat() if hasattr(mr["valid_date"], "isoformat") else str(mr["valid_date"])
                    model_map[(vd_str, mr["model"])] = float(mr["value"])

                for br in blend_rows:
                    vd_str = br["valid_date"].isoformat() if hasattr(br["valid_date"], "isoformat") else str(br["valid_date"])
                    blended_val = round(float(br["blended"]), 2)
                    gfs_val = model_map.get((vd_str, "gfs"), blended_val)
                    ifs_val = model_map.get((vd_str, "ecmwf_ifs"), blended_val)
                    icon_val = model_map.get((vd_str, "icon"), blended_val)
                    aifs_val = model_map.get((vd_str, "aifs"), blended_val)
                    spread_val = round(float(br["spread"]), 2) if br["spread"] is not None else round(max(gfs_val, ifs_val, icon_val, aifs_val) - min(gfs_val, ifs_val, icon_val, aifs_val), 2)
                    over_thresh = int(br["models_over_threshold"] or 0)

                    full_rows.append({
                        "valid_date": vd_str,
                        "blended": blended_val,
                        "gfs": gfs_val,
                        "ecmwf_ifs": ifs_val,
                        "icon": icon_val,
                        "aifs": aifs_val,
                        "spread": spread_val,
                        "models_over_threshold": over_thresh,
                    })
            except Exception as e:
                logger.error(f"Database query failed in get_forecast: {e}")
                return ToolEnvelope(
                    ok=False,
                    artifact_id="none",
                    title=f"Forecast query failed for {location_name}",
                    columns=["status", "error"],
                    n_rows=1,
                    preview=[["error", f"Database query failed: {str(e)}"]],
                    stats={},
                    meta={
                        "location": location_name,
                        "location_id": location_id,
                        "variable": args.variable,
                        "error": str(e),
                    },
                )

        # Query authoritative parquet dataset if database rows empty or connection offline
        if not full_rows:
            parquet_path = Path(__file__).resolve().parents[4] / "data" / "blended_forecasts_test.parquet"
            if parquet_path.exists():
                try:
                    import pandas as pd
                    df = pd.read_parquet(parquet_path)
                    sub = df[(df["location_id"] == location_id) & (df["variable"] == args.variable) & (df["lead_days"] <= args.lead_days_max)]
                    if not sub.empty:
                        latest_date = sub["valid_date"].max()
                        sub_latest = sub[sub["valid_date"] == latest_date].sort_values("lead_days")
                        if sub_latest.empty:
                            sub_latest = sub.sort_values(["valid_date", "lead_days"]).head(args.lead_days_max)
                        for _, r in sub_latest.iterrows():
                            vd_str = str(r["valid_date"])
                            b_val = round(float(r["blended"]), 2)
                            g_val = round(float(r["f_gfs"]), 2)
                            i_val = round(float(r["f_ecmwf_ifs"]), 2)
                            ic_val = round(float(r["f_icon"]), 2)
                            ai_val = round(float(r["f_aifs"]), 2)
                            sp_val = round(float(r["spread"]), 2) if pd.notna(r["spread"]) else round(max(g_val, i_val, ic_val, ai_val) - min(g_val, i_val, ic_val, ai_val), 2)
                            ot_val = int(r["models_over_threshold"]) if pd.notna(r["models_over_threshold"]) else 0
                            full_rows.append({
                                "valid_date": vd_str,
                                "blended": b_val,
                                "gfs": g_val,
                                "ecmwf_ifs": i_val,
                                "icon": ic_val,
                                "aifs": ai_val,
                                "spread": sp_val,
                                "models_over_threshold": ot_val,
                            })
                except Exception as e:
                    logger.debug(f"Parquet query fallback error: {e}")

        # Empty result if no records found
        if not full_rows:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"No forecast records found — {location_name}, {args.variable}",
                columns=columns,
                n_rows=0,
                preview=[],
                stats={
                    "message": "No forecast records available for this location and variable",
                    "variable": args.variable,
                    "lead_days_max": args.lead_days_max,
                },
                meta={
                    "location": location_name,
                    "location_id": location_id,
                    "variable": args.variable,
                    "model_version": active_version,
                    "issue_time": datetime.now(timezone.utc).isoformat(),
                    "source": "blended_forecasts",
                    "resolved": True,
                },
            )

        # Calculate summary statistics
        blended_vals = [r["blended"] for r in full_rows]
        stats = {
            "blended": {
                "min": round(min(blended_vals), 2),
                "max": round(max(blended_vals), 2),
                "mean": round(sum(blended_vals) / len(blended_vals), 2),
            },
            "variable": args.variable,
            "unit": "mm/24h" if args.variable == "rain_mm" else ("°C" if args.variable == "tmax_c" else "km/h"),
        }

        # Format preview rows (up to 5)
        preview = [[r[c] for c in columns] for r in full_rows[:5]]

        # Store complete artifact
        title = f"Blended vs models — {location_name}, {args.variable}, next {args.lead_days_max} days"
        owner_id = context.current_user.user_id if context.current_user else "anonymous"
        artifact_id = save_tool_artifact(owner_id, title, columns, full_rows)

        return ToolEnvelope(
            ok=True,
            artifact_id=artifact_id,
            title=title,
            columns=columns,
            n_rows=len(full_rows),
            preview=preview,
            stats=stats,
            meta={
                "location": location_name,
                "location_id": location_id,
                "variable": args.variable,
                "model_version": active_version,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "blended_forecasts",
            },
        )
