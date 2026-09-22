"""export_data tool implementation (PRD §9.4).

Generates short-lived (10-minute) backend-signed download URLs for bulk datasets:
- dataset: forecast | history | skill | weights | alerts
- filters: arbitrary dictionary of filters
- format: csv | json
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from api.app.assistant.schemas import ExportDataArgs, ToolEnvelope
from api.app.assistant.tools.base import BaseTool, ToolContext, save_tool_artifact
from core.config import settings

logger = logging.getLogger("aagam.assistant.tools.export")

EXPORT_SECRET = settings.SUPABASE_JWT_SECRET or "aagam_internal_export_signing_key_2026"


def create_signed_export_token(dataset: str, format_str: str, expires_in_seconds: int = 600) -> str:
    """Generates an HMAC-signed token expiring in expires_in_seconds (~10 minutes)."""
    expires_at = int(time.time()) + expires_in_seconds
    payload = {
        "dataset": dataset,
        "format": format_str,
        "exp": expires_at,
    }
    raw_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("utf-8").rstrip("=")

    signature = hmac.new(
        EXPORT_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{payload_b64}.{signature}"


def verify_signed_export_token(token: str) -> Dict[str, Any]:
    """Verifies HMAC signature and expiration for an export token.

    Raises ValueError on invalid signature or expiration.
    """
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid export token format")

    payload_b64, signature = parts
    expected_sig = hmac.new(
        EXPORT_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise ValueError("Export token signature mismatch")

    # Decode payload
    padding = "=" * (-len(payload_b64) % 4)
    payload_bytes = base64.urlsafe_b64decode((payload_b64 + padding).encode("utf-8"))
    payload = json.loads(payload_bytes.decode("utf-8"))

    if time.time() > payload.get("exp", 0):
        raise ValueError("Export token has expired")

    return payload


class ExportDataTool(BaseTool):
    name = "export_data"
    description = "Generates a 10-minute signed download URL for bulk weather datasets (forecast, history, skill, alerts)."
    args_model = ExportDataArgs

    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        args = ExportDataArgs(**raw_args)

        token = create_signed_export_token(args.dataset, args.format, expires_in_seconds=600)
        # Build query parameters from filters
        filter_params = ""
        if args.filters:
            for k, v in args.filters.items():
                if v is not None:
                    filter_params += f"&{k}={v}"

        download_url = f"/api/v1/export?dataset={args.dataset}&format={args.format}&token={token}{filter_params}"

        columns = ["dataset", "format", "download_url", "expires_in_minutes"]
        preview = [[args.dataset, args.format, download_url, 10]]
        full_rows = [{"dataset": args.dataset, "format": args.format, "download_url": download_url, "expires_in_minutes": 10}]

        stats = {
            "dataset": args.dataset,
            "format": args.format,
            "expiry": "10 minutes",
            "signed_url": download_url,
        }

        title = f"Signed Data Export Link — {args.dataset.title()} ({args.format.upper()})"
        owner_id = context.current_user.user_id if context.current_user else "anonymous"
        artifact_id = save_tool_artifact(owner_id, title, columns, full_rows)

        return ToolEnvelope(
            ok=True,
            artifact_id=artifact_id,
            title=title,
            columns=columns,
            n_rows=1,
            preview=preview,
            stats=stats,
            meta={
                "dataset": args.dataset,
                "format": args.format,
                "download_url": download_url,
                "expires_at": datetime.fromtimestamp(time.time() + 600, tz=timezone.utc).isoformat(),
                "issue_time": datetime.now(timezone.utc).isoformat(),
                "source": "export",
            },
        )
