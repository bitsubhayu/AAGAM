"""get_weights tool implementation (PRD §9.4).

Returns model × lead weight matrix, sample size n_samples, and dominant model:
- Accepts variable, region OR location (resolved to region), season, lead_days
- Formats into standard ToolEnvelope with compact preview and stats
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import asyncpg

from api.app.assistant.location_resolver import resolve_location
from api.app.assistant.schemas import GetWeightsArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact
from api.app.db.model_versions import get_active_model_version_cached

logger = logging.getLogger("aagam.assistant.tools.weights")


class GetWeightsTool(BaseTool):
    name = "get_weights"
    description = "Model weights matrix and sample sizes for a region or location."
    args_model = GetWeightsArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = GetWeightsArgs(**raw_args)

        # 1. Resolve region if location is provided
        target_region = (args.region or "EAST_NE").upper()
        resolved_loc_name = None
        if args.location:
            loc_res = resolve_location(args.location)
            if loc_res["resolved"]:
                target_region = loc_res["location"]["region"]
                resolved_loc_name = loc_res["location"]["name"]

        target_season = args.season or "monsoon"
        target_var = args.variable or "rain_mm"

        columns = ["lead_days", "gfs", "ecmwf_ifs", "icon", "aifs", "dominant_model", "n_samples"]
        full_rows: List[Dict[str, Any]] = []

        # 2. Query weights from DB
        raw_weights: List[asyncpg.Record] = []
        active_version_str = "v1"
        if context.conn is not None:
            try:
                active_ver = await get_active_model_version_cached(context.conn)
                active_ver_id = active_ver.get("id", 2)
                active_version_str = active_ver.get("version_str") or f"v{active_ver_id}"

                q = """
                    SELECT lead_days, model, weight, n_samples
                    FROM weights
                    WHERE version_id = $1 AND variable = $2 AND region = $3
                """
                params: List[Any] = [active_ver_id, target_var, target_region]
                if args.season and args.season.lower() != "all":
                    q += " AND season = $4"
                    params.append(args.season.lower())
                if args.lead_days is not None:
                    q += f" AND lead_days = ${len(params)+1}"
                    params.append(args.lead_days)

                q += " ORDER BY lead_days ASC"
                raw_weights = await context.conn.fetch(q, *params)
            except Exception as e:
                logger.error(f"Failed to fetch region weights: {e}")
                return ToolEnvelope(
                    ok=False,
                    artifact_id="none",
                    title=f"Weights query failed for region {target_region}",
                    columns=["status", "error"],
                    n_rows=1,
                    preview=[["error", f"Database error querying weights: {str(e)}"]],
                    stats={},
                    meta={"region": target_region, "error": str(e)},
                )

        # Fallback to authoritative live_weights_60d.parquet dataset if DB is offline or empty
        if not raw_weights:
            from pathlib import Path

            import pandas as pd
            for p_name in ("live_weights_60d.parquet", "baseline_weights.parquet"):
                p_file = Path(__file__).resolve().parents[4] / "data" / p_name
                if p_file.exists():
                    try:
                        df = pd.read_parquet(p_file)
                        if "variable" in df.columns and target_var:
                            df = df[df["variable"] == target_var]
                        if "region" in df.columns and target_region and target_region.upper() != "ALL":
                            df = df[df["region"].str.upper() == target_region.upper()]
                        if "season" in df.columns and args.season and args.season.lower() != "all":
                            df = df[df["season"].str.lower() == args.season.lower()]
                        if "lead_days" in df.columns and args.lead_days is not None:
                            df = df[df["lead_days"] == args.lead_days]
                        if not df.empty:
                            raw_weights = [
                                {
                                    "lead_days": int(r.lead_days),
                                    "model": str(r.model),
                                    "weight": float(r.weight),
                                    "n_samples": int(r.n_samples) if pd.notna(r.n_samples) else 0,
                                }
                                for r in df.itertuples()
                            ]
                            active_version_str = p_name.replace(".parquet", "")
                            break
                    except Exception as pe:
                        logger.warning(f"Error reading parquet weights fallback: {pe}")

        if not raw_weights:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"Model Weights Matrix — Region {target_region}, {target_var} ({target_season})",
                columns=columns,
                n_rows=0,
                preview=[],
                stats={
                    "dominant_model": "none",
                    "average_dominant_margin": "0%",
                    "region": target_region,
                    "season": target_season,
                    "variable": target_var,
                    "message": "No model weights recorded for the specified criteria",
                },
                meta={
                    "region": target_region,
                    "location": resolved_loc_name,
                    "variable": target_var,
                    "season": target_season,
                    "resolved": True,
                },
            )

        # Group by lead_days
        weights_by_lead: Dict[int, Dict[str, float]] = {}
        samples_by_lead: Dict[int, int] = {}
        for rw in raw_weights:
            ld = rw["lead_days"]
            if ld not in weights_by_lead:
                weights_by_lead[ld] = {}
            weights_by_lead[ld][rw["model"]] = float(rw["weight"])
            if rw.get("n_samples") is not None:
                samples_by_lead[ld] = int(rw["n_samples"])

        leads = sorted(weights_by_lead.keys())
        for ld in leads:
            lead_w = weights_by_lead.get(ld, {})
            gfs = round(lead_w.get("gfs", 0.0), 3)
            ifs = round(lead_w.get("ecmwf_ifs", 0.0), 3)
            icon = round(lead_w.get("icon", 0.0), 3)
            aifs = round(lead_w.get("aifs", 0.0), 3)

            models_w = {"ecmwf_ifs": ifs, "aifs": aifs, "gfs": gfs, "icon": icon}
            dominant = max(models_w.items(), key=lambda x: x[1])[0]
            n_samp = samples_by_lead.get(ld, 0)

            full_rows.append({
                "lead_days": ld,
                "gfs": gfs,
                "ecmwf_ifs": ifs,
                "icon": icon,
                "aifs": aifs,
                "dominant_model": dominant,
                "n_samples": n_samp,
            })

        # Summary statistics
        dominant_counts: Dict[str, int] = {}
        margins: List[float] = []
        for r in full_rows:
            d = r["dominant_model"]
            dominant_counts[d] = dominant_counts.get(d, 0) + 1
            w_vals = sorted([r["gfs"], r["ecmwf_ifs"], r["icon"], r["aifs"]], reverse=True)
            if len(w_vals) >= 2:
                margins.append(w_vals[0] - w_vals[1])

        overall_dominant = max(dominant_counts.items(), key=lambda x: x[1])[0] if dominant_counts else "none"
        avg_margin_val = round(float(sum(margins) / len(margins)) * 100, 1) if margins else 0.0

        stats = {
            "dominant_model": overall_dominant,
            "average_dominant_margin": f"{avg_margin_val}%",
            "region": target_region,
            "season": target_season,
            "variable": target_var,
        }

        preview = [[r[c] for c in columns] for r in full_rows[:5]]
        title = f"Model Weights Matrix — Region {target_region}, {target_var} ({target_season})"
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
                "region": target_region,
                "location": resolved_loc_name,
                "variable": target_var,
                "season": target_season,
                "model_version": active_version_str,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "weights",
            },
        )
