"""get_alerts tool implementation (PRD §9.4).

Returns active or historical extreme weather alerts:
- status: active | acknowledged | all
- filters: hazard, region, min_severity, max_lead_days
- Formats into standard ToolEnvelope with decision-rule inputs and agreement chips
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from api.app.assistant.schemas import GetAlertsArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact

logger = logging.getLogger("aagam.assistant.tools.alerts")


class GetAlertsTool(BaseTool):
    name = "get_alerts"
    description = (
        "Active extreme weather alert warnings (heavy rain, heatwave, wind) across India or specific regions. "
        "Use when listing active alerts or warnings rather than querying a city forecast."
    )
    args_model = GetAlertsArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = GetAlertsArgs(**raw_args)

        columns = [
            "location",
            "hazard",
            "severity",
            "valid_date",
            "lead_days",
            "value",
            "unit",
            "model_agreement",
            "status",
        ]
        full_rows: List[Dict[str, Any]] = []

        if context.conn is not None:
            try:
                SEVERITY_ORDER = {"advisory": 1, "watch": 2, "alert": 3, "warning": 3}

                # Query alerts table
                q = """
                    SELECT a.id, a.hazard, a.severity, a.valid_date, a.lead_days, a.value, a.models_over, a.rule, a.status,
                           l.name as location_name, l.region
                    FROM alerts a
                    JOIN locations l ON a.location_id = l.id
                    WHERE ($1 = 'all' OR a.status = $1)
                    ORDER BY a.valid_date ASC, a.severity DESC
                    LIMIT 200
                """
                rows = await context.conn.fetch(q, args.status)
                for r in rows:
                    if args.hazard:
                        norm_filter = args.hazard.lower().replace("_", "").replace("-", "")
                        norm_hz = r["hazard"].lower().replace("_", "").replace("-", "")
                        if norm_filter != norm_hz:
                            continue
                    if args.region and r["region"].lower() != args.region.lower():
                        continue
                    if args.max_lead_days is not None and r["lead_days"] > args.max_lead_days:
                        continue
                    if args.min_severity:
                        req_sev = SEVERITY_ORDER.get(args.min_severity.lower(), 1)
                        row_sev = SEVERITY_ORDER.get(r["severity"].lower(), 1)
                        if row_sev < req_sev:
                            continue

                    vd_str = r["valid_date"].isoformat() if hasattr(r["valid_date"], "isoformat") else str(r["valid_date"])
                    hz = r["hazard"]
                    unit = "mm/24h" if "rain" in hz else ("°C" if "heat" in hz else "km/h")
                    models_over = r.get("models_over")
                    agreement_str = f"{models_over}/4 models exceed threshold" if models_over is not None else "Consensus threshold"

                    full_rows.append({
                        "location": r["location_name"],
                        "hazard": hz,
                        "severity": r["severity"],
                        "valid_date": vd_str,
                        "lead_days": r["lead_days"],
                        "value": round(float(r["value"]), 1) if r["value"] is not None else 0.0,
                        "unit": unit,
                        "model_agreement": agreement_str,
                        "status": r["status"],
                    })
            except Exception as e:
                logger.error(f"Failed to query alerts table: {e}")
                return ToolEnvelope(
                    ok=False,
                    artifact_id="none",
                    title="Alerts query failed",
                    columns=["status", "error"],
                    n_rows=1,
                    preview=[["error", f"Database query failed: {str(e)}"]],
                    stats={},
                    meta={"status": args.status, "error": str(e)},
                )

        # Fallback to test dataset ONLY in explicit test mode (AAGAM_ALLOW_TEST_FALLBACK=1)
        import os
        allow_test_fallback = os.environ.get("AAGAM_ALLOW_TEST_FALLBACK", "0") == "1"
        if not full_rows and allow_test_fallback:
            from pathlib import Path

            import pandas as pd
            parquet_path = Path(__file__).resolve().parents[4] / "data" / "historical_alerts_replay.parquet"
            if parquet_path.exists():
                try:
                    df = pd.read_parquet(parquet_path)
                    SEVERITY_ORDER = {"advisory": 1, "watch": 2, "alert": 3, "warning": 3}
                    for r in df.itertuples():
                        st = str(getattr(r, "status", "active"))
                        if args.status != "all" and st.lower() != args.status.lower():
                            continue
                        hz = str(getattr(r, "hazard", ""))
                        if args.hazard:
                            norm_filter = args.hazard.lower().replace("_", "").replace("-", "")
                            norm_hz = hz.lower().replace("_", "").replace("-", "")
                            if norm_filter != norm_hz:
                                continue
                        reg = str(getattr(r, "region", ""))
                        if args.region and reg.lower() != args.region.lower():
                            continue
                        ld = int(getattr(r, "lead_days", 1))
                        if args.max_lead_days is not None and ld > args.max_lead_days:
                            continue
                        sev = str(getattr(r, "severity", "advisory"))
                        if args.min_severity:
                            req_sev = SEVERITY_ORDER.get(args.min_severity.lower(), 1)
                            row_sev = SEVERITY_ORDER.get(sev.lower(), 1)
                            if row_sev < req_sev:
                                continue

                        vd_val = getattr(r, "valid_date", None)
                        vd_str = vd_val.isoformat() if hasattr(vd_val, "isoformat") else str(vd_val)
                        unit = "mm/24h" if "rain" in hz else ("°C" if "heat" in hz else "km/h")
                        aggr = getattr(r, "agreement", None)
                        agreement_str = f"{aggr}/4 models exceed threshold" if aggr is not None else "Consensus threshold"
                        val_num = getattr(r, "value", 0.0)

                        full_rows.append({
                            "location": getattr(r, "location_name", "Station"),
                            "hazard": hz,
                            "severity": sev,
                            "valid_date": vd_str,
                            "lead_days": ld,
                            "value": round(float(val_num), 1) if pd.notna(val_num) else 0.0,
                            "unit": unit,
                            "model_agreement": agreement_str,
                            "status": st,
                        })
                        if len(full_rows) >= 50:
                            break
                except Exception as pe:
                    logger.warning(f"Error reading historical alerts replay fallback: {pe}")

        if not full_rows:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"Extreme Weather Alerts (Status: {args.status})",
                columns=columns,
                n_rows=0,
                preview=[],
                stats={
                    "total_alerts": 0,
                    "severity_breakdown": {},
                    "status_filter": args.status,
                    "message": "No alerts found matching criteria",
                    "decision_rule_notice": "decision support, not an official IMD warning",
                },
                meta={
                    "status": args.status,
                    "hazard": args.hazard,
                    "region": args.region,
                    "issue_time": datetime.now(timezone.utc).isoformat(),
                },
            )

        severity_counts: Dict[str, int] = {}
        for r in full_rows:
            sev = r["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        stats = {
            "total_alerts": len(full_rows),
            "severity_breakdown": severity_counts,
            "status_filter": args.status,
            "decision_rule_notice": "decision support, not an official IMD warning",
        }

        preview = [[r[c] for c in columns] for r in full_rows[:5]]
        title = f"Extreme Weather Alerts (Status: {args.status})"
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
                "status": args.status,
                "hazard": args.hazard,
                "region": args.region,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "alerts",
            },
        )
