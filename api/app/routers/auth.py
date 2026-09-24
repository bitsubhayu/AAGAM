"""Authentication & OTP Router (PRD §6.9, §12, Tech Stack §8a).

Implements passwordless email OTP request and verification via Supabase Auth + Brevo SMTP.
First-time verification automatically seeds the user's personal subscriptions record.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from api.app.db.supabase import get_supabase_client
from core.config import settings
from core.schemas import (
    CheckAccessRequest,
    CheckAccessResponse,
    ForecasterAccessRequestCreate,
    ForecasterAccessRequestItem,
)

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
    token: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="Exactly six-digit numeric OTP code received via email",
    )


class ForecasterOtpRequest(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Forecaster institutional email address",
    )
    name: Optional[str] = Field(None, max_length=100, description="Optional full name of forecaster")
    institution: Optional[str] = Field(None, max_length=150, description="Optional meteorological or research institution")



class ForecasterOtpVerify(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Forecaster email address",
    )
    token: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="Exactly six-digit numeric OTP code received via email",
    )
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
        # Supabase passwordless OTP with redirect to configured auth redirect URL
        client.auth.sign_in_with_otp({
            "email": payload.email,
            "options": {"email_redirect_to": settings.AUTH_REDIRECT_URL},
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


async def _is_email_approved_forecaster(conn: asyncpg.Connection, email: str) -> bool:
    """Checks if email belongs to an approved forecaster/coordinator account.

    Approved accounts have:
    - a profiles record with role in ('forecaster', 'coordinator')
    - OR an approved access request in forecaster_access_requests table
    - OR demo auth forecaster/coordinator accounts if local demo auth is enabled
    """
    clean_email = email.strip().lower()

    # 1. Local demo auth accounts for test fixtures
    demo_approved = ("forecaster@aagam.gov.in", "coordinator@aagam.gov.in", "admin@aagam.gov.in")
    if settings.ENABLE_LOCAL_DEMO_AUTH and (clean_email in demo_approved or clean_email.endswith("@aagam.gov.in")):
        return True

    # 2. Check profiles joined with auth.users
    try:
        prof_row = await conn.fetchrow(
            """
            SELECT p.role
            FROM profiles p
            JOIN auth.users u ON p.user_id = u.id
            WHERE LOWER(u.email) = $1 AND p.role IN ('forecaster', 'coordinator')
            LIMIT 1;
            """,
            clean_email,
        )
        if prof_row:
            return True
    except Exception as e:
        logger.warning(f"Error querying profiles for approved forecaster {clean_email}: {e}")

    # 3. Check forecaster_access_requests table
    try:
        req_row = await conn.fetchrow(
            """
            SELECT id FROM forecaster_access_requests
            WHERE LOWER(email) = $1 AND status = 'approved'
            LIMIT 1;
            """,
            clean_email,
        )
        if req_row:
            return True
    except Exception as e:
        logger.warning(f"Error querying forecaster_access_requests for {clean_email}: {e}")

    return False


@router.post(
    "/forecaster/check-access",
    response_model=CheckAccessResponse,
    summary="Check if email belongs to an approved forecaster/coordinator account",
)
async def check_forecaster_access(
    payload: CheckAccessRequest,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> CheckAccessResponse:
    """Checks whether an email belongs to an approved Forecaster or Coordinator."""
    clean_email = payload.email.strip().lower()
    approved = await _is_email_approved_forecaster(conn, clean_email)
    role = None
    if approved:
        prof_row = await conn.fetchrow(
            """
            SELECT p.role
            FROM profiles p
            JOIN auth.users u ON p.user_id = u.id
            WHERE LOWER(u.email) = $1
            LIMIT 1;
            """,
            clean_email,
        )
        role = prof_row["role"] if prof_row else "forecaster"

    return CheckAccessResponse(
        status="ok",
        email=payload.email,
        is_approved=approved,
        role=role,
    )


@router.post(
    "/forecaster/request-access",
    summary="Submit a Forecaster access request for coordinator review",
)
async def request_forecaster_access(
    payload: ForecasterAccessRequestCreate,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, str]:
    """Submits an access request for unapproved candidates to be reviewed by a Forecaster Coordinator."""
    clean_email = payload.email.strip().lower()

    if await _is_email_approved_forecaster(conn, clean_email):
        return {
            "status": "ok",
            "message": "This email is already approved for Forecaster access. Please proceed with login.",
        }

    existing = await conn.fetchrow(
        "SELECT id, status FROM forecaster_access_requests WHERE LOWER(email) = $1 AND status = 'pending'",
        clean_email,
    )
    if existing:
        return {
            "status": "ok",
            "message": "Your access request has already been submitted and is pending review by a Forecaster Coordinator.",
        }

    await conn.execute(
        """
        INSERT INTO forecaster_access_requests (name, email, institution, status, created_at)
        VALUES ($1, $2, $3, 'pending', NOW())
        """,
        payload.name.strip(),
        clean_email,
        payload.institution.strip() if payload.institution else None,
    )
    logger.info(f"Forecaster access request submitted for {clean_email} ({payload.name})")
    return {
        "status": "ok",
        "message": "Your access request has been submitted successfully. A Forecaster Coordinator will review it.",
    }


@router.post(
    "/forecaster/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a 6-digit OTP code for Forecaster login (approved accounts only)",
)
async def request_forecaster_otp(
    payload: ForecasterOtpRequest,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, str]:
    """Requests a 6-digit OTP code sent via email for approved forecasters/coordinators only."""
    clean_email = payload.email.strip().lower()
    is_approved = await _is_email_approved_forecaster(conn, clean_email)
    if not is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCESS_NOT_APPROVED",
                "message": "This email is not an approved Forecaster or Coordinator account. Please request forecaster access.",
                "retry_after": None,
            },
        )

    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Supabase authentication client is not configured."},
        )

    try:
        client.auth.sign_in_with_otp({
            "email": clean_email,
            "options": {
                "data": {
                    "display_name": payload.name or "Forecaster",
                    "institution": payload.institution or "Meteorological Organization",
                },
                "email_redirect_to": settings.AUTH_REDIRECT_URL,
            },
        })
        logger.info(f"Forecaster OTP requested for approved email {clean_email}")
        return {
            "status": "ok",
            "message": "A 6-digit forecaster verification code has been sent to your email address.",
        }
    except Exception as e:
        logger.error(f"Failed to request Forecaster OTP for {clean_email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "OTP_REQUEST_FAILED", "message": str(e)},
        )


@router.post(
    "/forecaster/otp/verify",
    status_code=status.HTTP_200_OK,
    response_model=OtpVerifyResponse,
    summary="Verify Forecaster OTP code, load authoritative profile role, and return session",
)
async def verify_forecaster_otp(
    payload: ForecasterOtpVerify,
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> OtpVerifyResponse:
    """Verifies OTP code for forecaster, resolves authoritative role from profiles table, and returns authenticated session."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Supabase authentication client is not configured."},
        )

    clean_email = payload.email.strip().lower()

    try:
        auth_resp = client.auth.verify_otp({
            "email": clean_email,
            "token": payload.token.strip(),
            "type": "email",
        })
    except Exception as e:
        logger.warning(f"Forecaster OTP verification failed for {clean_email}: {e}")
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

    # Fetch authoritative profile
    prof_row = await conn.fetchrow("SELECT role, display_name, org FROM profiles WHERE user_id = $1::uuid", user_id)

    # If no profile or role is public, check if an approved request exists for this email
    if not prof_row or prof_row["role"] == "public":
        req_row = await conn.fetchrow(
            "SELECT name, institution FROM forecaster_access_requests WHERE LOWER(email) = $1 AND status = 'approved' ORDER BY reviewed_at DESC LIMIT 1",
            clean_email,
        )
        if req_row:
            cand_name = req_row["name"] or payload.name or "Forecaster"
            cand_org = req_row["institution"] or payload.institution or "Meteorological Organization"
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
                cand_name,
                cand_org,
            )
            prof_row = await conn.fetchrow("SELECT role, display_name, org FROM profiles WHERE user_id = $1::uuid", user_id)

    assigned_role = prof_row["role"] if prof_row else "public"
    assigned_name = prof_row["display_name"] if prof_row else payload.name
    assigned_org = prof_row["org"] if prof_row else payload.institution

    return OtpVerifyResponse(
        status="ok",
        access_token=session.access_token,
        token_type="bearer",
        expires_in=session.expires_in,
        refresh_token=session.refresh_token,
        user=UserSummary(
            id=user_id,
            email=user.email or clean_email,
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


@router.get(
    "/forecaster/requests",
    response_model=List[ForecasterAccessRequestItem],
    summary="List all forecaster access requests (Coordinator only)",
)
async def list_forecaster_requests(
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[ForecasterAccessRequestItem]:
    """Returns all forecaster access requests for coordinator review."""
    rows = await conn.fetch(
        """
        SELECT id, name, email, institution, status, created_at, reviewed_by, reviewed_at, rejection_reason
        FROM forecaster_access_requests
        ORDER BY created_at DESC;
        """
    )
    return [
        ForecasterAccessRequestItem(
            id=r["id"],
            name=r["name"],
            email=r["email"],
            institution=r["institution"],
            status=r["status"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            reviewed_by=str(r["reviewed_by"]) if r["reviewed_by"] else None,
            reviewed_at=r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
            rejection_reason=r["rejection_reason"],
        )
        for r in rows
    ]


@router.post(
    "/forecaster/requests/{id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve a forecaster access request (Coordinator only)",
)
async def approve_forecaster_request(
    id: int = Path(..., description="ID of the access request to approve"),
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, Any]:
    """Approves a forecaster access request, setting status='approved' and updating/creating profile role='forecaster'."""
    req = await conn.fetchrow(
        "SELECT id, name, email, institution, status FROM forecaster_access_requests WHERE id = $1",
        id,
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUEST_NOT_FOUND", "message": f"Access request {id} not found."},
        )

    if req["status"] == "approved":
        return {"status": "ok", "message": f"Request {id} for {req['email']} is already approved."}

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE forecaster_access_requests
            SET status = 'approved',
                reviewed_by = $1::uuid,
                reviewed_at = NOW()
            WHERE id = $2
            """,
            current_user.user_id,
            id,
        )

        # Check if auth.users has an existing user with this email
        user_row = await conn.fetchrow(
            "SELECT id FROM auth.users WHERE LOWER(email) = LOWER($1)",
            req["email"],
        )
        if user_row:
            u_id = user_row["id"]
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
                u_id,
                req["name"],
                req["institution"],
            )

    logger.info(f"Coordinator {current_user.user_id} approved forecaster access for {req['email']} (request {id})")
    return {
        "status": "ok",
        "message": f"Forecaster access for {req['name']} ({req['email']}) has been approved.",
        "request_id": id,
        "email": req["email"],
        "status": "approved",
    }


@router.post(
    "/forecaster/requests/{id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject a forecaster access request (Coordinator only)",
)
async def reject_forecaster_request(
    id: int = Path(..., description="ID of the access request to reject"),
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, Any]:
    """Rejects a forecaster access request."""
    req = await conn.fetchrow(
        "SELECT id, name, email, status FROM forecaster_access_requests WHERE id = $1",
        id,
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUEST_NOT_FOUND", "message": f"Access request {id} not found."},
        )

    await conn.execute(
        """
        UPDATE forecaster_access_requests
        SET status = 'rejected',
            reviewed_by = $1::uuid,
            reviewed_at = NOW()
        WHERE id = $2
        """,
        current_user.user_id,
        id,
    )
    logger.info(f"Coordinator {current_user.user_id} rejected forecaster access for {req['email']} (request {id})")
    return {
        "status": "ok",
        "message": f"Forecaster access for {req['email']} has been rejected.",
        "request_id": id,
        "email": req["email"],
        "status": "rejected",
    }

