"""Authentication & OTP Router (PRD §6.9, §12, Tech Stack §8a).

Implements passwordless email OTP request and verification via Supabase Auth + Brevo SMTP.
First-time verification automatically seeds the user's personal subscriptions record.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.app.auth.dependencies import CurrentUser, require_role
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


class ForecasterOtpRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Full name of forecaster")
    institution: str = Field(..., min_length=2, max_length=150, description="Meteorological or research institution")
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Forecaster institutional email address",
    )


class ForecasterOtpVerify(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Forecaster email address",
    )
    token: str = Field(..., min_length=6, max_length=10, description="Six-digit OTP code received via email")
    name: Optional[str] = Field(None, max_length=100, description="Optional forecaster name")
    institution: Optional[str] = Field(None, max_length=150, description="Optional forecaster institution")


class UserSummary(BaseModel):
    id: str
    email: Optional[str] = None
    role: Optional[str] = "public"
    display_name: Optional[str] = None
    org: Optional[str] = None


class OtpVerifyResponse(BaseModel):
    status: str = "ok"
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    user: UserSummary


class ForecasterProfileSummary(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    org: Optional[str] = None
    role: str
    created_at: Optional[str] = None


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
        # Supabase passwordless OTP with redirect to http://localhost:3000
        client.auth.sign_in_with_otp({
            "email": payload.email,
            "options": {"email_redirect_to": "http://localhost:3000"},
        })
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

    # Fetch profile role using user_id primary key
    profile_row = await conn.fetchrow("SELECT role, display_name, org FROM profiles WHERE user_id = $1::uuid", user_id)
    u_role = profile_row["role"] if profile_row else "public"
    disp_name = profile_row["display_name"] if profile_row else None
    org_name = profile_row["org"] if profile_row else None

    return OtpVerifyResponse(
        status="ok",
        access_token=session.access_token,
        token_type="bearer",
        expires_in=session.expires_in,
        refresh_token=session.refresh_token,
        user=UserSummary(id=user_id, email=user.email or payload.email, role=u_role, display_name=disp_name, org=org_name),
    )


@router.post(
    "/forecaster/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a 6-digit OTP code for Forecaster registration/login",
)
async def request_forecaster_otp(payload: ForecasterOtpRequest) -> Dict[str, str]:
    """Requests a 6-digit OTP code sent via email for verified forecaster onboarding."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Supabase authentication client is not configured."},
        )

    try:
        client.auth.sign_in_with_otp({
            "email": payload.email,
            "options": {
                "data": {
                    "display_name": payload.name,
                    "institution": payload.institution,
                },
                "email_redirect_to": "http://localhost:3000",
            },
        })
        logger.info(f"Forecaster OTP requested for {payload.email} ({payload.name}, {payload.institution})")
        return {
            "status": "ok",
            "message": "A 6-digit forecaster verification code has been sent to your email address.",
        }
    except Exception as e:
        logger.error(f"Failed to request Forecaster OTP for {payload.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "OTP_REQUEST_FAILED", "message": str(e)},
        )


@router.post(
    "/forecaster/otp/verify",
    status_code=status.HTTP_200_OK,
    response_model=OtpVerifyResponse,
    summary="Verify Forecaster OTP code, upsert forecaster profile, and return session",
)
async def verify_forecaster_otp(
    payload: ForecasterOtpVerify,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> OtpVerifyResponse:
    """Verifies OTP code for forecaster, sets role='forecaster' in profiles table, and returns authenticated session."""
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
        logger.warning(f"Forecaster OTP verification failed for {payload.email}: {e}")
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

    meta = getattr(user, "user_metadata", {}) or {}
    disp_name = payload.name or meta.get("display_name") or meta.get("name") or "Forecaster"
    inst = payload.institution or meta.get("institution") or meta.get("org") or "Meteorological Organization"

    # Part 11: Upsert profile with authoritative role = 'forecaster' (never trust client-supplied role)
    try:
        await conn.execute(
            """
            INSERT INTO profiles (user_id, display_name, org, role, updated_at)
            VALUES ($1::uuid, $2, $3, 'forecaster', NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET display_name = COALESCE($2, profiles.display_name),
                org = COALESCE($3, profiles.org),
                role = CASE WHEN profiles.role = 'coordinator' THEN 'coordinator' ELSE 'forecaster' END,
                updated_at = NOW();
            """,
            user_id,
            disp_name,
            inst,
        )
    except Exception as e:
        logger.error(f"Failed to upsert forecaster profile for {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROFILE_UPDATE_FAILED", "message": "Failed to configure forecaster profile."},
        )

    # Check updated profile
    prof_row = await conn.fetchrow("SELECT role, display_name, org FROM profiles WHERE user_id = $1::uuid", user_id)
    assigned_role = prof_row["role"] if prof_row else "forecaster"
    assigned_name = prof_row["display_name"] if prof_row else disp_name
    assigned_org = prof_row["org"] if prof_row else inst

    return OtpVerifyResponse(
        status="ok",
        access_token=session.access_token,
        token_type="bearer",
        expires_in=session.expires_in,
        refresh_token=session.refresh_token,
        user=UserSummary(
            id=user_id,
            email=user.email or payload.email,
            role=assigned_role,
            display_name=assigned_name,
            org=assigned_org,
        ),
    )


@router.post(
    "/forecasters/{user_id}/promote-coordinator",
    status_code=status.HTTP_200_OK,
    summary="Promote an existing verified Forecaster to Forecaster Coordinator (Coordinator only)",
)
async def promote_to_coordinator(
    user_id: str,
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, Any]:
    """Promotes an existing verified forecaster to Forecaster Coordinator.

    Rules (PRD & Part 16):
    - Requester must have role = coordinator
    - Target must exist in profiles
    - Target cannot be the requester (no self-promotion)
    - Target must currently have role = 'forecaster' (public users cannot be promoted directly)
    - On success: target role = 'coordinator'
    """
    if str(current_user.user_id) == str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SELF_PROMOTION_DISALLOWED", "message": "Coordinators cannot self-promote."},
        )

    target_profile = await conn.fetchrow(
        """
        SELECT p.user_id, u.email, p.role, p.display_name
        FROM profiles p
        LEFT JOIN auth.users u ON p.user_id = u.id
        WHERE p.user_id = $1::uuid
        """,
        user_id,
    )
    if not target_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": f"Target user profile {user_id} does not exist."},
        )

    current_target_role = target_profile["role"]
    if current_target_role == "coordinator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "ALREADY_COORDINATOR", "message": "Target user is already a Forecaster Coordinator."},
        )

    if current_target_role != "forecaster":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_TARGET_ROLE",
                "message": f"Only verified Forecasters can be promoted to Coordinator (current role: {current_target_role}).",
            },
        )

    await conn.execute(
        "UPDATE profiles SET role = 'coordinator', updated_at = NOW() WHERE user_id = $1::uuid",
        user_id,
    )

    logger.info(f"Coordinator {current_user.user_id} promoted forecaster {user_id} to Coordinator")
    return {
        "status": "ok",
        "message": f"Forecaster {target_profile['display_name'] or target_profile['email']} ({user_id}) has been promoted to Forecaster Coordinator.",
        "user_id": user_id,
        "role": "coordinator",
    }


@router.get(
    "/forecasters",
    response_model=List[ForecasterProfileSummary],
    summary="List all verified forecasters and coordinators (Coordinator only)",
)
async def list_forecasters(
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[ForecasterProfileSummary]:
    """Returns list of all verified Forecaster and Coordinator profiles for coordinator management view."""
    rows = await conn.fetch(
        """
        SELECT p.user_id, COALESCE(u.email, '') as email, p.display_name, p.org, p.role, p.updated_at as created_at
        FROM profiles p
        LEFT JOIN auth.users u ON p.user_id = u.id
        WHERE p.role IN ('forecaster', 'coordinator')
        ORDER BY p.role ASC, p.updated_at DESC;
        """
    )
    return [
        ForecasterProfileSummary(
            id=str(r["user_id"]),
            email=r["email"],
            display_name=r["display_name"],
            org=r["org"],
            role=r["role"],
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
        )
        for r in rows
    ]
