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
from typing import Any, Dict, List, Optional

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
                # Query strictly the single latest operational cycle
                q_cycle = """
                    WITH latest_blend AS (
                        SELECT MAX(issue_time) AS issue_time
                        FROM blended_forecasts
                        WHERE location_id = $1 AND variable = $2
                    ),
                    blend_rows AS (
                        SELECT
                            b.valid_date,
                            b.lead_days,
                            b.blended,
                            b.spread,
                            b.models_over_threshold,
                            b.degraded,
                            b.issue_time
                        FROM blended_forecasts b
                        JOIN latest_blend lb ON b.issue_time = lb.issue_time
                        WHERE b.location_id = $1 AND b.variable = $2
                          AND b.lead_days >= 0 AND b.lead_days <= $3
                    ),
                    model_rows AS (
                        SELECT
                            m.valid_date,
                            m.lead_days,
                            m.model,
                            m.value,
                            m.issue_time
                        FROM model_forecasts m
                        WHERE m.location_id = $1 AND m.variable = $2
                          AND (
                              EXISTS (SELECT 1 FROM blend_rows br WHERE br.valid_date = m.valid_date)
                              OR (NOT EXISTS (SELECT 1 FROM blend_rows) AND m.issue_time = (
                                  SELECT MAX(issue_time) FROM model_forecasts WHERE location_id = $1 AND variable = $2
                              ) AND m.lead_days >= 0 AND m.lead_days <= $3)
                          )
                    ),
                    models_agg AS (
                        SELECT
                            valid_date,
                            jsonb_object_agg(model, round(value::numeric, 2)) AS models_json
                        FROM model_rows
                        GROUP BY valid_date
                    ),
                    merged AS (
                        SELECT
                            COALESCE(b.valid_date, m.valid_date) AS valid_date,
                            COALESCE(b.lead_days, m_lead.lead_days) AS lead_days,
                            b.blended,
                            b.spread,
                            b.models_over_threshold,
                            b.degraded,
                            COALESCE(b.issue_time, m_lead.issue_time) AS issue_time,
                            ma.models_json
                        FROM blend_rows b
                        FULL OUTER JOIN (
                            SELECT DISTINCT valid_date FROM model_rows
                        ) m ON b.valid_date = m.valid_date
                        LEFT JOIN (
                            SELECT valid_date, MIN(lead_days) AS lead_days, MAX(issue_time) AS issue_time
                            FROM model_rows
                            GROUP BY valid_date
                        ) m_lead ON COALESCE(b.valid_date, m.valid_date) = m_lead.valid_date
                        LEFT JOIN models_agg ma ON COALESCE(b.valid_date, m.valid_date) = ma.valid_date
                    )
                    SELECT DISTINCT ON (lead_days)
                        valid_date,
                        lead_days,
                        blended,
                        spread,
                        models_over_threshold,
                        degraded,
                        issue_time,
                        models_json
                    FROM merged
                    WHERE lead_days >= 0 AND lead_days <= $3
                    ORDER BY lead_days ASC, valid_date ASC;
                """
                rows = await context.conn.fetch(q_cycle, location_id, args.variable, args.lead_days_max)

                for r in rows:
                    vd_str = r["valid_date"].isoformat() if hasattr(r["valid_date"], "isoformat") else str(r["valid_date"])
                    blended_val = round(float(r["blended"]), 2) if r["blended"] is not None else None

                    raw_models = r["models_json"]
                    m_dict: Dict[str, Optional[float]] = {}
                    if raw_models:
                        if isinstance(raw_models, str):
                            import json
                            m_dict = json.loads(raw_models)
                        else:
                            m_dict = dict(raw_models)

                    # Missing models remain None / null — NEVER substitute blend
                    gfs_val = round(float(m_dict["gfs"]), 2) if m_dict.get("gfs") is not None else None
                    ifs_val = round(float(m_dict["ecmwf_ifs"]), 2) if m_dict.get("ecmwf_ifs") is not None else None
                    icon_val = round(float(m_dict["icon"]), 2) if m_dict.get("icon") is not None else None
                    aifs_val = round(float(m_dict["aifs"]), 2) if m_dict.get("aifs") is not None else None

                    valid_vals = [v for v in (gfs_val, ifs_val, icon_val, aifs_val) if v is not None]
                    if r["spread"] is not None:
                        spread_val = round(float(r["spread"]), 2)
                    elif len(valid_vals) > 1:
                        spread_val = round(max(valid_vals) - min(valid_vals), 2)
                    else:
                        spread_val = 0.0

                    over_thresh = int(r["models_over_threshold"] or 0)

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

        # Isolated test-only mode fallback (STRICTLY GUARDED; NEVER used in production)
        import os
        if not full_rows and (getattr(context, "allow_test_fallback", False) or os.getenv("AAGAM_ALLOW_TEST_FALLBACK") == "1"):
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
                            b_val = round(float(r["blended"]), 2) if pd.notna(r["blended"]) else None
                            g_val = round(float(r["f_gfs"]), 2) if pd.notna(r.get("f_gfs")) else None
                            i_val = round(float(r["f_ecmwf_ifs"]), 2) if pd.notna(r.get("f_ecmwf_ifs")) else None
                            ic_val = round(float(r["f_icon"]), 2) if pd.notna(r.get("f_icon")) else None
                            ai_val = round(float(r["f_aifs"]), 2) if pd.notna(r.get("f_aifs")) else None
                            sp_val = round(float(r["spread"]), 2) if pd.notna(r["spread"]) else 0.0
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
                    logger.debug(f"Guarded test parquet fallback error: {e}")

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
