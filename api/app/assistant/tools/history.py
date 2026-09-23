"""query_history tool implementation (PRD §9.4).

Queries historical forecast, blended, or observed series:
- location: location name or slug
- variable: rain_mm | tmax_c | wind_max_kmh
- start, end: ISO dates YYYY-MM-DD
- kind: forecast | observed | blended
- Cap: 5,000 rows. Exceeding 5,000 returns structured narrowing recommendation or export action.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from api.app.assistant.location_resolver import resolve_location
from api.app.assistant.schemas import QueryHistoryArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact

logger = logging.getLogger("aagam.assistant.tools.history")

ROW_CAP = 5000


class QueryHistoryTool(BaseTool):
    name = "query_history"
    description = "Queries historical forecast or observed data for a location (up to 5,000 rows)."
    args_model = QueryHistoryArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = QueryHistoryArgs(**raw_args)

        # 1. Resolve location
        loc_res = resolve_location(args.location)
        if not loc_res["resolved"]:
            return ToolEnvelope(
                ok=False,
                artifact_id="none",
                title=f"Location resolution failed for '{args.location}'",
                columns=["status", "message"],
                n_rows=1,
                preview=[["error", loc_res["message"]]],
                stats={},
                meta={"resolved": False},
            )

        location = loc_res["location"]
        location_id = location["id"]
        location_name = location["name"]

        # Parse date range
        try:
            d_start = datetime.strptime(args.start, "%Y-%m-%d").date()
            d_end = datetime.strptime(args.end, "%Y-%m-%d").date()
            day_count = (d_end - d_start).days + 1
        except Exception:
            day_count = 30

        # Check expected row count: day_count * 7 leads * (models or 1)
        expected_rows = day_count * (7 if args.kind != "observed" else 1)
        if expected_rows > ROW_CAP:
            return ToolEnvelope(
                ok=False,
                artifact_id="none",
                title=f"Query exceeds 5,000 row cap ({expected_rows} estimated rows)",
                columns=["status", "message", "action"],
                n_rows=1,
                preview=[[
                    "ROW_CAP_EXCEEDED",
                    f"Date range {args.start} to {args.end} exceeds 5,000 rows limit.",
                    "Please narrow the date range to <= 70 days or use the export_data tool.",
                ]],
                stats={"estimated_rows": expected_rows, "cap": ROW_CAP},
                meta={"exceeded": True, "suggest_export": True},
            )

        columns = ["date", "lead_days", "variable", "value", "kind", "source"]
        full_rows: List[Dict[str, Any]] = []

        if args.kind == "observed":
            # Query verified ground-truth observations from data/truth.parquet
            truth_path = Path(__file__).resolve().parents[4] / "data" / "truth.parquet"
            if truth_path.exists():
                try:
                    import pandas as pd
                    var_col = "rain_truth" if args.variable == "rain_mm" else ("tmax_truth" if args.variable == "tmax_c" else "wind_max_truth")
                    src_col = "rain_truth_source" if args.variable == "rain_mm" else ("temp_truth_source" if args.variable == "tmax_c" else "wind_truth_source")

                    df = pd.read_parquet(truth_path, columns=["location_id", "valid_date", var_col, src_col])
                    df["valid_date_str"] = df["valid_date"].astype(str)
                    mask = (df["location_id"] == location_id) & (df["valid_date_str"] >= args.start) & (df["valid_date_str"] <= args.end)
                    sub = df[mask].sort_values("valid_date_str")
                    for _, row in sub.head(ROW_CAP).iterrows():
                        val = row[var_col]
                        if pd.notna(val):
                            full_rows.append({
                                "date": str(row["valid_date_str"]),
                                "lead_days": 0,
                                "variable": args.variable,
                                "value": round(float(val), 1),
                                "kind": "observed",
                                "source": str(row[src_col]) if pd.notna(row[src_col]) else "truth_dataset",
                            })
                except Exception as e:
                    logger.error(f"Failed to query observed data from truth.parquet: {e}")
                    return ToolEnvelope(
                        ok=False,
                        artifact_id="none",
                        title=f"Failed to query observed data for {location_name}",
                        columns=["status", "error"],
                        n_rows=1,
                        preview=[["error", f"Error reading ground-truth observations: {str(e)}"]],
                        stats={},
                        meta={"location": location_name, "error": str(e)},
                    )
        elif context.conn is not None:
            try:
                if args.kind == "blended":
                    q = """
                        SELECT valid_date, lead_days, variable, blended as value
                        FROM blended_forecasts
                        WHERE location_id = $1 AND variable = $2
                          AND valid_date >= $3::date AND valid_date <= $4::date
                        ORDER BY valid_date ASC
                        LIMIT 5000
                    """
                    rows = await context.conn.fetch(q, location_id, args.variable, args.start, args.end)
                    for r in rows:
                        full_rows.append({
                            "date": str(r["valid_date"]),
                            "lead_days": r["lead_days"],
                            "variable": r["variable"],
                            "value": round(float(r["value"]), 1),
                            "kind": "blended",
                            "source": "AAGAM Blend",
                        })
                else:
                    q = """
                        SELECT valid_date, lead_days, variable, value, model
                        FROM model_forecasts
                        WHERE location_id = $1 AND variable = $2
                          AND valid_date >= $3::date AND valid_date <= $4::date
                        ORDER BY valid_date ASC
                        LIMIT 5000
                    """
                    rows = await context.conn.fetch(q, location_id, args.variable, args.start, args.end)
                    for r in rows:
                        full_rows.append({
                            "date": str(r["valid_date"]),
                            "lead_days": r["lead_days"],
                            "variable": r["variable"],
                            "value": round(float(r["value"]), 1),
                            "kind": args.kind,
                            "source": r["model"],
                        })
            except Exception as e:
                logger.error(f"Failed to query history from DB: {e}")
                return ToolEnvelope(
                    ok=False,
                    artifact_id="none",
                    title=f"History query failed for {location_name}",
                    columns=["status", "error"],
                    n_rows=1,
                    preview=[["error", f"Database query failed: {str(e)}"]],
                    stats={},
                    meta={"location": location_name, "error": str(e)},
                )

        if not full_rows:
            return ToolEnvelope(
                ok=True,
                artifact_id="none",
                title=f"Historical {args.kind.title()} — {location_name}, {args.variable} ({args.start} to {args.end})",
                columns=columns,
                n_rows=0,
                preview=[],
                stats={
                    "total_rows": 0,
                    "location": location_name,
                    "message": f"No historical {args.kind} data found for the specified location and date range",
                    "unit": "mm" if args.variable == "rain_mm" else ("°C" if args.variable == "tmax_c" else "km/h"),
                },
                meta={
                    "location": location_name,
                    "location_id": location_id,
                    "variable": args.variable,
                    "start": args.start,
                    "end": args.end,
                    "kind": args.kind,
                },
            )

        vals = [r["value"] for r in full_rows]
        stats = {
            "total_rows": len(full_rows),
            "location": location_name,
            "min_val": round(min(vals), 2) if vals else 0,
            "max_val": round(max(vals), 2) if vals else 0,
            "mean_val": round(sum(vals) / len(vals), 2) if vals else 0,
            "unit": "mm" if args.variable == "rain_mm" else ("°C" if args.variable == "tmax_c" else "km/h"),
        }

        preview = [[r[c] for c in columns] for r in full_rows[:5]]
        title = f"Historical {args.kind.title()} — {location_name}, {args.variable} ({args.start} to {args.end})"
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
                "variable": args.variable,
                "start": args.start,
                "end": args.end,
                "kind": args.kind,
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "history",
            },
        )
