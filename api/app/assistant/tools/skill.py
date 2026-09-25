"""get_skill tool implementation (PRD §9.4, §12).

Authoritative verification skill score retrieval using the shared `fetch_skill_scores`
service matching the Skill page exactly:
- scope: 'live' (operational verification window, max 90 days) | 'held_out' (fixed 90-day benchmark 2026-06-21 to 2026-09-18)
- metric: mae | rmse | bias | skill_score | pod | far | csi
- group_by: lead | region | season | model
- Formats into standard ToolEnvelope with compact preview and stats
- Strictly NO hardcoded 0.20/0.35/0.20/0.25 blend weights
- Strictly NO test parquet fallbacks in live production
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from api.app.assistant.schemas import GetSkillArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact
from api.app.services.skill_service import fetch_skill_scores

logger = logging.getLogger("aagam.assistant.tools.skill")


class GetSkillTool(BaseTool):
    name = "get_skill"
    description = (
        "Authoritative forecast skill verification scores (MAE, RMSE, Bias, POD, FAR, CSI) "
        "matching the Skill page for live operational verification (scope='live') or the "
        "formal 90-day benchmark (scope='held_out', 2026-06-21 to 2026-09-18)."
    )
    args_model = GetSkillArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = GetSkillArgs(**raw_args)

        scope = getattr(args, "scope", "live")
        metric_name = args.metric.lower()
        if metric_name not in ("mae", "rmse", "bias", "pod", "far", "csi", "skill_score"):
            metric_name = "mae"

        try:
            skill_resp = await fetch_skill_scores(
                conn=context.conn,
                scope=scope,
                group_by=args.group_by,
                variable=args.variable,
                window_days=min(args.window_days or 90, 90),
                region=args.region,
                season=args.season,
            )
        except Exception as e:
            logger.error(f"Error calling fetch_skill_scores in get_skill tool: {e}", exc_info=True)
            return ToolEnvelope(
                ok=False,
                artifact_id="none",
                title="Skill scores query failed",
                columns=["status", "error"],
                n_rows=1,
                preview=[["error", f"Skill scoring service error: {str(e)}"]],
                stats={"error": str(e)},
                meta={"error": str(e)},
            )

        if not skill_resp.scores:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"{args.metric.upper()} Verification Scores ({scope.upper()}) — {args.variable}",
                columns=[args.group_by, "status"],
                n_rows=0,
                preview=[],
                stats={
                    "metric": args.metric.upper(),
                    "variable": args.variable,
                    "scope": skill_resp.evaluation_scope,
                    "data_status": skill_resp.data_status,
                    "effective_window_days": skill_resp.effective_window_days,
                    "verified_days_count": skill_resp.verified_days_count,
                    "truth_source": skill_resp.truth_source,
                    "message": "No verification skill scores computed for the specified criteria",
                },
                meta={
                    "metric": args.metric,
                    "group_by": args.group_by,
                    "variable": args.variable,
                    "scope": skill_resp.evaluation_scope,
                    "effective_window_days": skill_resp.effective_window_days,
                    "truth_source": skill_resp.truth_source,
                },
            )

        full_rows: List[Dict[str, Any]] = []

        if args.group_by == "model":
            columns = ["model", args.metric, "sample_count"]
            for s in skill_resp.scores:
                val = getattr(s, metric_name, None)
                if val is not None:
                    full_rows.append({
                        "model": s.model,
                        args.metric: round(float(val), 3),
                        "sample_count": s.n,
                    })
        else:
            # Grouping by lead_days, region, or season
            columns = [args.group_by, "aagam_blend", "gfs", "ecmwf_ifs", "icon", "aifs", "best_single"]
            grp_key_attr = "lead_days" if args.group_by in ("lead", "lead_days") else args.group_by

            by_grp: Dict[Any, Dict[str, Any]] = {}
            for s in skill_resp.scores:
                k = getattr(s, grp_key_attr, None)
                if k is None:
                    continue
                if k not in by_grp:
                    by_grp[k] = {}

                val = getattr(s, metric_name, None)
                m_norm = s.model.lower()
                if val is not None:
                    by_grp[k][m_norm] = float(val)

            is_higher_better = metric_name in ("pod", "csi")

            for k, m_scores in sorted(by_grp.items()):
                blend_val = m_scores.get("blend", m_scores.get("aagam_blend", m_scores.get("inverse-mae blend")))
                gfs_val = m_scores.get("gfs")
                ifs_val = m_scores.get("ecmwf_ifs", m_scores.get("ifs"))
                icon_val = m_scores.get("icon")
                aifs_val = m_scores.get("aifs")

                single_models = {
                    "gfs": gfs_val,
                    "ecmwf_ifs": ifs_val,
                    "icon": icon_val,
                    "aifs": aifs_val,
                }
                valid_singles = {m: v for m, v in single_models.items() if v is not None}

                if valid_singles:
                    if is_higher_better:
                        best_single = max(valid_singles.items(), key=lambda x: x[1])[0]
                    else:
                        best_single = min(valid_singles.items(), key=lambda x: x[1])[0]
                else:
                    best_single = "unavailable"

                grp_label = f"D+{k}" if args.group_by in ("lead", "lead_days") else str(k)
                full_rows.append({
                    args.group_by: grp_label,
                    "aagam_blend": round(blend_val, 3) if blend_val is not None else None,
                    "gfs": round(gfs_val, 3) if gfs_val is not None else None,
                    "ecmwf_ifs": round(ifs_val, 3) if ifs_val is not None else None,
                    "icon": round(icon_val, 3) if icon_val is not None else None,
                    "aifs": round(aifs_val, 3) if aifs_val is not None else None,
                    "best_single": best_single,
                })

        blend_vals = [r["aagam_blend"] for r in full_rows if "aagam_blend" in r and r["aagam_blend"] is not None]
        avg_blend = round(sum(blend_vals) / len(blend_vals), 3) if blend_vals else None

        unit_str = "mm" if args.variable == "rain_mm" else ("°C" if args.variable == "tmax_c" else "km/h")
        if metric_name in ("pod", "far", "csi"):
            unit_str = "ratio (0..1)"

        scope_title = "Held-Out 90-Day Test" if skill_resp.evaluation_scope == "held_out" else f"Live Verification ({skill_resp.effective_window_days}d)"
        title = f"{args.metric.upper()} Skill Scores by {args.group_by.title()} — {args.variable} [{scope_title}]"

        stats = {
            "metric": args.metric.upper(),
            "variable": args.variable,
            "scope": skill_resp.evaluation_scope,
            "data_status": skill_resp.data_status,
            "effective_window_days": skill_resp.effective_window_days,
            "verified_days_count": skill_resp.verified_days_count,
            "window_start": skill_resp.window_start,
            "window_end": skill_resp.window_end,
            "latest_verified_date": skill_resp.latest_verified_date,
            "truth_source": skill_resp.truth_source,
            "blend_average": avg_blend,
            "unit": unit_str,
        }

        preview = [[r.get(c) for c in columns] for r in full_rows[:5]]
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
                "scope": skill_resp.evaluation_scope,
                "window_days": skill_resp.effective_window_days,
                "truth_source": skill_resp.truth_source,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "skill_service (authoritative)",
            },
        )
