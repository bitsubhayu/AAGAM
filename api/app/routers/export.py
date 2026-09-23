"""Data streaming export endpoint (PRD §12, role: any)."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings

logger = logging.getLogger("aagam.api.export")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Export"])

VALID_DATASETS = {"forecasts", "alerts", "weights", "skill", "forecast", "history"}
VALID_FORMATS = {"csv", "json"}


@router.get("/export")
async def export_dataset(
    dataset: str = Query(..., description="Dataset to export: forecasts, alerts, weights, skill, history"),
    format: str = Query("csv", description="Output format: csv or json"),
    variable: Optional[str] = Query(None, description="Variable filter"),
    location: Optional[str] = Query(None, description="Location slug filter"),
    token: Optional[str] = Query(None, description="Signed export token for download URLs"),
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> StreamingResponse:
    """Streams data exports as CSV or JSON (PRD §12: requires signed token or authenticated session)."""
    dataset_clean = dataset.lower().strip()
    if dataset_clean in ("forecast", "history"):
        dataset_clean = "forecasts"

    format_clean = format.lower().strip()

    if token:
        from api.app.assistant.tools.export import verify_signed_export_token
        try:
            verify_signed_export_token(token)
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "EXPIRED_OR_INVALID_TOKEN", "message": str(ve), "retry_after": None},
            )

    if dataset_clean not in {"forecasts", "alerts", "weights", "skill"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DATASET",
                "message": f"Invalid dataset '{dataset}'. Must be one of: forecasts, alerts, weights, skill",
                "retry_after": None,
            },
        )

    if format_clean not in VALID_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_FORMAT",
                "message": f"Invalid format '{format}'. Must be 'csv' or 'json'.",
                "retry_after": None,
            },
        )

    rows: List[asyncpg.Record] = []

    if dataset_clean == "forecasts":
        q = "SELECT location_id, variable, valid_date, lead_days, issue_time, blended, ridge, lgbm, spread FROM blended_forecasts LIMIT 5000"
        rows = await conn.fetch(q)
        if not rows:
            # Fallback to model_forecasts if blended_forecasts is empty
            q = "SELECT location_id, variable, valid_date, lead_days, issue_time, model, value FROM model_forecasts LIMIT 5000"
            rows = await conn.fetch(q)
    elif dataset_clean == "alerts":
        q = "SELECT id, issue_time, location_id, hazard, severity, valid_date, lead_days, value, status FROM alerts ORDER BY issue_time DESC LIMIT 5000"
        rows = await conn.fetch(q)
    elif dataset_clean == "weights":
        q = "SELECT version_id, variable, region, season, lead_days, model, weight, method, n_samples FROM weights LIMIT 5000"
        rows = await conn.fetch(q)
    elif dataset_clean == "skill":
        q = "SELECT computed_at, window_days, variable, region, season, lead_days, model, mae, rmse, bias FROM skill_scores LIMIT 5000"
        rows = await conn.fetch(q)

    # Serialize to CSV or JSON
    if format_clean == "csv":
        output = io.StringIO()
        if rows:
            headers = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                d = dict(r)
                # Convert dates/datetimes to ISO strings
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                writer.writerow(d)
        else:
            output.write("no_records\n")

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="aagam_{dataset_clean}_export.csv"'},
        )
    else:
        # JSON streaming
        items: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            items.append(d)

        json_bytes = json.dumps({"dataset": dataset_clean, "count": len(items), "data": items}, indent=2)
        return StreamingResponse(
            iter([json_bytes]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="aagam_{dataset_clean}_export.json"'},
        )
