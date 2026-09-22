"""Personal Subscriptions Router (PRD §6.12, §11, §12).

Provides authenticated endpoints for subscribers to view, update, and manage
their personal alert preferences. Protected by Row Level Security (own-row only).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import List

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings

logger = logging.getLogger("aagam.api.subscriptions")

router = APIRouter(prefix=f"{settings.API_V1_STR}/subscriptions", tags=["Subscriptions"])

VALID_HAZARDS = {"heavy_rain", "heatwave", "high_wind", "high_uncertainty", "heavy_rain_3day"}
VALID_SEVERITIES = {"advisory", "watch", "alert"}


class SubscriptionResponse(BaseModel):
    user_id: str
    email: str
    location_ids: List[int]
    hazards: List[str]
    min_severity: str
    daily_summary: bool
    lifecycle_emails: bool
    active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class SubscriptionUpdate(BaseModel):
    location_ids: List[int] = Field(default_factory=list, description="List of location IDs to monitor")
    hazards: List[str] = Field(
        default=["heavy_rain", "heatwave", "high_wind", "heavy_rain_3day"],
        description="Hazard types to receive alerts for",
    )
    min_severity: str = Field(
        default="watch",
        description="Minimum severity threshold ('advisory', 'watch', 'alert')",
    )
    daily_summary: bool = Field(default=True, description="Receive daily morning summary digest")
    lifecycle_emails: bool = Field(default=True, description="Receive real-time lifecycle alert updates")
    active: bool = Field(default=True, description="Subscription active status")


class UnsubscribeResponse(BaseModel):
    status: str = "unsubscribed"
    active: bool = False
    message: str = "You have been unsubscribed from all alert notifications."


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=SubscriptionResponse,
    summary="Get current user's alert subscription preferences",
)
async def get_my_subscription(
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> SubscriptionResponse:
    """Retrieves the authenticated subscriber's current alert preferences."""
    row = await conn.fetchrow(
        """
        SELECT user_id, email, location_ids, hazards, min_severity,
               daily_summary, lifecycle_emails, active, created_at, updated_at
        FROM subscriptions
        WHERE user_id = $1::uuid;
        """,
        current_user.user_id,
    )

    if not row:
        # If no subscription exists yet, create default row for authenticated user
        email = current_user.email or "user@example.com"
        row = await conn.fetchrow(
            """
            INSERT INTO subscriptions (
                user_id, email, location_ids, hazards, min_severity,
                daily_summary, lifecycle_emails, active
            ) VALUES (
                $1::uuid, $2, '{}', '{heavy_rain,heatwave,high_wind,heavy_rain_3day}',
                'watch', true, true, true
            )
            RETURNING user_id, email, location_ids, hazards, min_severity,
                      daily_summary, lifecycle_emails, active, created_at, updated_at;
            """,
            current_user.user_id,
            email,
        )

    return SubscriptionResponse(
        user_id=str(row["user_id"]),
        email=row["email"],
        location_ids=list(row["location_ids"]),
        hazards=list(row["hazards"]),
        min_severity=row["min_severity"],
        daily_summary=row["daily_summary"],
        lifecycle_emails=row["lifecycle_emails"],
        active=row["active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.put(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=SubscriptionResponse,
    summary="Create or update personal alert subscription preferences",
)
async def update_my_subscription(
    payload: SubscriptionUpdate,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> SubscriptionResponse:
    """Updates personal subscription locations, hazards, minimum severity, and delivery flags."""
    # Validate hazards
    for h in payload.hazards:
        if h not in VALID_HAZARDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_HAZARD", "message": f"Unsupported hazard '{h}'. Allowed: {sorted(VALID_HAZARDS)}"},
            )

    # Validate min_severity
    if payload.min_severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_SEVERITY", "message": f"Unsupported severity '{payload.min_severity}'. Allowed: {sorted(VALID_SEVERITIES)}"},
        )

    email = current_user.email or "user@example.com"

    row = await conn.fetchrow(
        """
        INSERT INTO subscriptions (
            user_id, email, location_ids, hazards, min_severity,
            daily_summary, lifecycle_emails, active, updated_at
        ) VALUES (
            $1::uuid, $2, $3, $4, $5, $6, $7, $8, NOW()
        )
        ON CONFLICT (user_id) DO UPDATE
        SET email = EXCLUDED.email,
            location_ids = EXCLUDED.location_ids,
            hazards = EXCLUDED.hazards,
            min_severity = EXCLUDED.min_severity,
            daily_summary = EXCLUDED.daily_summary,
            lifecycle_emails = EXCLUDED.lifecycle_emails,
            active = EXCLUDED.active,
            updated_at = NOW()
        RETURNING user_id, email, location_ids, hazards, min_severity,
                  daily_summary, lifecycle_emails, active, created_at, updated_at;
        """,
        current_user.user_id,
        email,
        payload.location_ids,
        payload.hazards,
        payload.min_severity,
        payload.daily_summary,
        payload.lifecycle_emails,
        payload.active,
    )

    return SubscriptionResponse(
        user_id=str(row["user_id"]),
        email=row["email"],
        location_ids=list(row["location_ids"]),
        hazards=list(row["hazards"]),
        min_severity=row["min_severity"],
        daily_summary=row["daily_summary"],
        lifecycle_emails=row["lifecycle_emails"],
        active=row["active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.delete(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=UnsubscribeResponse,
    summary="Soft-unsubscribe current user from notifications",
)
async def unsubscribe_my_subscription(
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> UnsubscribeResponse:
    """Soft unsubscribes the current user (sets active=false, preserves history per PRD §12)."""
    row = await conn.fetchrow(
        """
        UPDATE subscriptions
        SET active = false,
            updated_at = NOW()
        WHERE user_id = $1::uuid
        RETURNING user_id, active;
        """,
        current_user.user_id,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUBSCRIPTION_NOT_FOUND", "message": "No active subscription found to unsubscribe."},
        )

    return UnsubscribeResponse(
        status="unsubscribed",
        active=False,
        message="You have been unsubscribed from all alert notifications.",
    )
