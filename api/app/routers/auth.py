"""Authentication & OTP Router (PRD §6.9, §12, Tech Stack §8a).

Implements passwordless email OTP request and verification via Supabase Auth + Brevo SMTP.
First-time verification automatically seeds the user's personal subscriptions record.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.app.db.pool import get_db_conn
from api.app.db.supabase import get_supabase_client
from core.config import settings

logger = logging.getLogger("aagam.api.auth")

router = APIRouter(prefix=f"{settings.API_V1_STR}/auth", tags=["Auth"])


class OtpRequest(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="User email address to receive OTP code",
    )


class OtpVerify(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="User email address",
    )
    token: str = Field(..., min_length=6, max_length=10, description="Six-digit OTP code received via email")


class UserSummary(BaseModel):
    id: str
    email: Optional[str] = None


class OtpVerifyResponse(BaseModel):
    status: str = "ok"
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    user: UserSummary


@router.post(
    "/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a 6-digit OTP code via email",
)
async def request_otp(payload: OtpRequest) -> Dict[str, str]:
    """Requests a 6-digit login OTP code sent via Supabase Auth + Brevo SMTP."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Supabase authentication client is not configured."},
        )

    try:
        # Supabase passwordless OTP
        client.auth.sign_in_with_otp({"email": payload.email})
        logger.info(f"OTP requested for {payload.email}")
        return {
            "status": "ok",
            "message": "A 6-digit verification code has been sent to your email address.",
        }
    except Exception as e:
        logger.error(f"Failed to request OTP for {payload.email}: {e}")
        # Return generic safe message to prevent email enumeration where desired, or error if Supabase explicitly fails
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "OTP_REQUEST_FAILED", "message": str(e)},
        )


@router.post(
    "/otp/verify",
    status_code=status.HTTP_200_OK,
    response_model=OtpVerifyResponse,
    summary="Verify 6-digit OTP code and create/return session",
)
async def verify_otp(
    payload: OtpVerify,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> OtpVerifyResponse:
    """Verifies the 6-digit OTP code, returns authenticated JWT session, and ensures subscription record."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Supabase authentication client is not configured."},
        )

    try:
        auth_resp = client.auth.verify_otp({
            "email": payload.email,
            "token": payload.token.strip(),
            "type": "email",
        })
    except Exception as e:
        logger.warning(f"OTP verification failed for {payload.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_OTP", "message": "Invalid or expired verification code."},
        )

    if not auth_resp or not auth_resp.session or not auth_resp.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_OTP", "message": "Invalid or expired verification code."},
        )

    session = auth_resp.session
    user = auth_resp.user
    user_id = str(user.id)

    # PRD §4 / §11: Upsert default subscription record on first verification
    try:
        await conn.execute(
            """
            INSERT INTO subscriptions (
                user_id, email, location_ids, hazards, min_severity,
                daily_summary, lifecycle_emails, active
            ) VALUES (
                $1::uuid, $2, '{}', '{heavy_rain,heatwave,high_wind,heavy_rain_3day}',
                'watch', true, true, true
            )
            ON CONFLICT (user_id) DO UPDATE
            SET email = EXCLUDED.email,
                updated_at = NOW();
            """,
            user_id,
            payload.email,
        )
    except Exception as e:
        logger.error(f"Failed to auto-seed subscription for {user_id}: {e}")
        # Non-fatal for auth verification, but logged

    return OtpVerifyResponse(
        status="ok",
        access_token=session.access_token,
        token_type="bearer",
        expires_in=session.expires_in,
        refresh_token=session.refresh_token,
        user=UserSummary(id=user_id, email=user.email or payload.email),
    )
