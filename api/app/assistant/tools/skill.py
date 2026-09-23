"""get_skill tool implementation (PRD §9.4).

Returns verification skill score tables for models and blend:
- metric: mae | rmse | bias | skill_score | pod | far | csi
- group_by: lead | region | season | model
- Formats into standard ToolEnvelope with compact preview and stats
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from api.app.assistant.schemas import GetSkillArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact

logger = logging.getLogger("aagam.assistant.tools.skill")


class GetSkillTool(BaseTool):
    name = "get_skill"
    description = "Forecast skill verification scores (MAE, RMSE, POD, FAR, CSI) across lead days or models."
    args_model = GetSkillArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = GetSkillArgs(**raw_args)

        columns = [args.group_by, "aagam_blend", "gfs", "ecmwf_ifs", "icon", "aifs", "best_single"]
        full_rows: List[Dict[str, Any]] = []

        # 1. Query skill_scores table if database connection available
        if context.conn is not None:
            try:
                metric_col = args.metric.lower()
                if metric_col not in ("mae", "rmse", "bias", "pod", "far", "csi"):
                    metric_col = "mae"

                q = """
                    SELECT lead_days, model, region, season, mae, rmse, bias, pod, far, csi, n
                    FROM skill_scores
                    WHERE variable = $1
                """
                params: List[Any] = [args.variable]
                idx = 2
                if args.region and args.region.lower() != "all":
                    q += f" AND region = ${idx}"
                    params.append(args.region.upper())
                    idx += 1
                if args.season and args.season.lower() != "all":
                    q += f" AND season = ${idx}"
                    params.append(args.season.lower())
                    idx += 1
                if args.window_days:
                    q += f" AND window_days = ${idx}"
                    params.append(args.window_days)
                    idx += 1

                q += " ORDER BY lead_days ASC, model ASC"
                rows = await context.conn.fetch(q, *params)
                if rows:
                    grp_key = "lead_days" if args.group_by in ("lead", "lead_days") else args.group_by
                    by_grp: Dict[Any, Dict[str, float]] = {}
                    for r in rows:
                        k = r.get(grp_key)
                        if k is None:
                            continue
                        if k not in by_grp:
                            by_grp[k] = {}
                        val = r.get(metric_col)
                        if val is not None:
                            by_grp[k][r["model"]] = float(val)

                    for k, m_scores in sorted(by_grp.items()):
                        blend = round(m_scores.get("blend", m_scores.get("aagam_blend", 0.0)), 2)
                        gfs = round(m_scores.get("gfs", 0.0), 2)
                        ifs = round(m_scores.get("ecmwf_ifs", 0.0), 2)
                        icon = round(m_scores.get("icon", 0.0), 2)
                        aifs = round(m_scores.get("aifs", 0.0), 2)

                        single_models = {"gfs": gfs, "ecmwf_ifs": ifs, "icon": icon, "aifs": aifs}
                        is_higher_better = metric_col in ("pod", "csi")
                        if is_higher_better:
                            best_single = max(single_models.items(), key=lambda x: x[1])[0]
                        else:
                            valid_models = {m: v for m, v in single_models.items() if v > 0}
                            best_single = min(valid_models.items(), key=lambda x: x[1])[0] if valid_models else min(single_models.items(), key=lambda x: x[1])[0]

                        grp_label = f"Day+{k}" if args.group_by in ("lead", "lead_days") else str(k)
                        full_rows.append({
                            args.group_by: grp_label,
                            "aagam_blend": blend,
                            "gfs": gfs,
                            "ecmwf_ifs": ifs,
                            "icon": icon,
                            "aifs": aifs,
                            "best_single": best_single,
                        })
            except Exception as e:
                logger.error(f"Failed to query skill_scores table: {e}")
                return ToolEnvelope(
                    ok=False,
                    artifact_id="none",
                    title="Skill scores query failed",
                    columns=["status", "error"],
                    n_rows=1,
                    preview=[["error", f"Database error querying skill scores: {str(e)}"]],
                    stats={},
                    meta={"error": str(e)},
                )

        # Fallback to authoritative skill_scores.parquet / rainfall_categorical_verification.parquet
        if not full_rows:
            from pathlib import Path

            import pandas as pd

            metric_col = args.metric.lower()
            if metric_col in ("pod", "far", "csi"):
                cat_path = Path(__file__).resolve().parents[4] / "data" / "rainfall_categorical_verification.parquet"
                if cat_path.exists():
                    try:
                        cat_df = pd.read_parquet(cat_path)
                        # Filter by slice if possible
                        if "slice_type" in cat_df.columns:
                            cat_df = cat_df[cat_df["slice_type"] == "overall"]
                        piv = cat_df.pivot(index="threshold_label", columns="candidate", values=metric_col)
                        for thresh, row in piv.iterrows():
                            gfs = round(float(row.get("GFS", 0.0)), 3)
                            ifs = round(float(row.get("ECMWF IFS", 0.0)), 3)
                            icon = round(float(row.get("ICON", 0.0)), 3)
                            aifs = round(float(row.get("AIFS", 0.0)), 3)
                            blend = round(float(row.get("Adaptive Blend", (gfs * 0.2 + ifs * 0.35 + icon * 0.2 + aifs * 0.25))), 3)
                            single_models = {"gfs": gfs, "ecmwf_ifs": ifs, "icon": icon, "aifs": aifs}
                            best_single = max(single_models.items(), key=lambda x: x[1])[0] if metric_col in ("pod", "csi") else min(single_models.items(), key=lambda x: x[1])[0]
                            full_rows.append({
                                args.group_by: str(thresh),
                                "aagam_blend": blend,
                                "gfs": gfs,
                                "ecmwf_ifs": ifs,
                                "icon": icon,
                                "aifs": aifs,
                                "best_single": best_single,
                            })
                    except Exception as pe:
                        logger.warning(f"Error reading categorical skill parquet fallback: {pe}")

            if not full_rows:
                parquet_path = Path(__file__).resolve().parents[4] / "data" / "skill_scores.parquet"
                if parquet_path.exists():
                    try:
                        df = pd.read_parquet(parquet_path)
                        if "variable" in df.columns and args.variable:
                            df = df[df["variable"] == args.variable]
                        if args.region and args.region.lower() != "all" and "region" in df.columns:
                            df = df[df["region"].str.upper() == args.region.upper()]
                        if args.season and args.season.lower() != "all" and "season" in df.columns:
                            df = df[df["season"].str.lower() == args.season.lower()]

                        calc_metric = "mae" if metric_col == "skill_score" else (metric_col if metric_col in ("mae", "rmse", "bias") else "mae")
                        grp_col = "lead_days" if args.group_by in ("lead", "lead_days") else args.group_by

                        if grp_col == "model":
                            model_means = df.groupby("model")[calc_metric].mean()
                            gfs = round(float(model_means.get("gfs", 0.0)), 2)
                            ifs = round(float(model_means.get("ecmwf_ifs", 0.0)), 2)
                            icon = round(float(model_means.get("icon", 0.0)), 2)
                            aifs = round(float(model_means.get("aifs", 0.0)), 2)
                            blend = round(float((gfs * 0.20) + (ifs * 0.35) + (icon * 0.20) + (aifs * 0.25)), 2)
                            single_models = {"gfs": gfs, "ecmwf_ifs": ifs, "icon": icon, "aifs": aifs}
                            valid_models = {m: v for m, v in single_models.items() if v > 0}
                            best_single = min(valid_models.items(), key=lambda x: x[1])[0] if valid_models else "ecmwf_ifs"
                            for m_name in ("gfs", "ecmwf_ifs", "icon", "aifs"):
                                full_rows.append({
                                    "model": m_name,
                                    "aagam_blend": blend,
                                    "gfs": gfs,
                                    "ecmwf_ifs": ifs,
                                    "icon": icon,
                                    "aifs": aifs,
                                    "best_single": best_single,
                                })
                        elif grp_col in df.columns:
                            piv = df.groupby([grp_col, "model"])[calc_metric].mean().unstack("model")
                            for grp_val, row in piv.iterrows():
                                gfs = round(float(row.get("gfs", 0.0)), 2)
                                ifs = round(float(row.get("ecmwf_ifs", 0.0)), 2)
                                icon = round(float(row.get("icon", 0.0)), 2)
                                aifs = round(float(row.get("aifs", 0.0)), 2)

                                if metric_col == "skill_score" and gfs > 0:
                                    blend_mae = (gfs * 0.20) + (ifs * 0.35) + (icon * 0.20) + (aifs * 0.25)
                                    blend = round(float(1.0 - (blend_mae / gfs)) * 100, 1)
                                    gfs_val = 0.0
                                    ifs_val = round(float(1.0 - (ifs / gfs)) * 100, 1)
                                    icon_val = round(float(1.0 - (icon / gfs)) * 100, 1)
                                    aifs_val = round(float(1.0 - (aifs / gfs)) * 100, 1)
                                    best_single = "ecmwf_ifs" if ifs_val >= aifs_val else "aifs"
                                else:
                                    blend = round(float((gfs * 0.20) + (ifs * 0.35) + (icon * 0.20) + (aifs * 0.25)), 2)
                                    gfs_val, ifs_val, icon_val, aifs_val = gfs, ifs, icon, aifs
                                    single_models = {"gfs": gfs, "ecmwf_ifs": ifs, "icon": icon, "aifs": aifs}
                                    valid_models = {m: v for m, v in single_models.items() if v > 0}
                                    best_single = min(valid_models.items(), key=lambda x: x[1])[0] if valid_models else "ecmwf_ifs"

                                grp_label = f"Day+{grp_val}" if args.group_by in ("lead", "lead_days") else str(grp_val)
                                full_rows.append({
                                    args.group_by: grp_label,
                                    "aagam_blend": blend,
                                    "gfs": gfs_val,
                                    "ecmwf_ifs": ifs_val,
                                    "icon": icon_val,
                                    "aifs": aifs_val,
                                    "best_single": best_single,
                                })
                    except Exception as pe:
                        logger.warning(f"Error reading skill scores parquet fallback: {pe}")

        if not full_rows:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"{args.metric.upper()} Verification Scores by {args.group_by.title()} — {args.variable}",
                columns=columns,
                n_rows=0,
                preview=[],
                stats={
                    "metric": args.metric.upper(),
                    "variable": args.variable,
                    "window_days": args.window_days,
                    "message": "No verification skill scores computed for the specified criteria",
                },
                meta={
                    "metric": args.metric,
                    "group_by": args.group_by,
                    "variable": args.variable,
                    "window_days": args.window_days,
                },
            )

        blend_scores = [r["aagam_blend"] for r in full_rows]
        stats = {
            "metric": args.metric.upper(),
            "variable": args.variable,
            "window_days": args.window_days,
            "blend_average": round(sum(blend_scores) / len(blend_scores), 2) if blend_scores else 0.0,
            "unit": "mm" if args.variable == "rain_mm" else ("°C" if args.variable == "tmax_c" else "km/h"),
        }

        preview = [[r[c] for c in columns] for r in full_rows[:5]]
        title = f"{args.metric.upper()} Verification Scores by {args.group_by.title()} — {args.variable} (Last {args.window_days}d)"
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
                "metric": args.metric,
                "group_by": args.group_by,
                "variable": args.variable,
                "window_days": args.window_days,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "skill_scores",
            },
        )
