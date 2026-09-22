"""Brevo Transactional Email Client (Tech Stack §8a, §13).

Provides delivery of alert lifecycle and daily summary emails via Brevo's
REST API (https://api.brevo.com/v3/smtp/email).
Supports mock / dry-run execution when BREVO_API_KEY is not configured or in testing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

import requests

from core.config import settings

logger = logging.getLogger("aagam.notify.brevo")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoClient:
    """Client for sending transactional emails via Brevo API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.BREVO_API_KEY
        self.sender_email = sender_email or settings.BREVO_SENDER_EMAIL or "alerts@aagam.org"
        self.sender_name = sender_name or settings.BREVO_SENDER_NAME or "AAGAM Weather Alerts"

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        to_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a transactional email.

        If api_key is not set (e.g. in development/tests), logs and returns a mock ID.
        """
        if not self.api_key or self.api_key.startswith("mock") or self.api_key in ("xkeysib-...", "placeholder"):
            mock_id = f"mock-{uuid.uuid4()}"
            logger.info(
                f"[MOCK EMAIL] To: {to_email} | Subject: {subject} | Mock MsgID: {mock_id}"
            )
            return {"status": "mocked", "messageId": mock_id}

        payload = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email,
            },
            "to": [
                {
                    "email": to_email,
                    "name": to_name or to_email,
                }
            ],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content or html_content,
        }

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = requests.post(
                BREVO_API_URL,
                json=payload,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Brevo email sent to {to_email}: messageId={data.get('messageId')}")
            return data
        except requests.RequestException as e:
            logger.error(f"Failed to send Brevo email to {to_email}: {e}")
            raise
