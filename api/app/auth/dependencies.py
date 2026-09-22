"""FastAPI authentication and role dependencies for AAGAM API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, status

from api.app.auth.jwt import verify_supabase_jwt
from api.app.db.pool import get_db_conn, set_rls_claims

logger = logging.getLogger("aagam.api.auth.dependencies")


@dataclass
class CurrentUser:
    """Authenticated user context with resolved role."""
    user_id: str
    email: Optional[str] = None
    role: str = "viewer"  # 'viewer', 'forecaster', 'admin'


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> CurrentUser:
    """FastAPI dependency to extract and authenticate the current user via Supabase JWT.

    Resolves the user's role from the `profiles` table in Supabase.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Missing Authorization bearer token.",
                "retry_after": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Authorization header must be formatted as 'Bearer <token>'.",
                "retry_after": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    try:
        payload = verify_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": "The provided JWT token has expired.",
                "retry_after": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.warning(f"JWT verification failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Invalid JWT token signature or claims.",
                "retry_after": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Token payload missing 'sub' claim.",
                "retry_after": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("email")

    # Fetch authoritative role from `profiles` table
    user_role = "viewer"
    try:
        # Inject RLS claims so the connection acts in the context of the user
        await set_rls_claims(conn, user_id, role="authenticated")
        row = await conn.fetchrow(
            "SELECT role FROM profiles WHERE user_id = $1::uuid",
            user_id,
        )
        if row and row["role"]:
            user_role = row["role"]
        else:
            # Check if role is present in app_metadata or user_metadata
            app_meta = payload.get("app_metadata", {})
            user_meta = payload.get("user_metadata", {})
            user_role = app_meta.get("role") or user_meta.get("role") or "viewer"
    except Exception as e:
        logger.warning(f"Failed to query user profile for {user_id}: {e}")
        user_role = "viewer"

    return CurrentUser(user_id=user_id, email=email, role=user_role)


async def get_optional_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> CurrentUser:
    """Dependency that extracts user if Authorization header is provided, or yields anonymous user."""
    if not authorization:
        await set_rls_claims(conn, None, role="anon")
        return CurrentUser(user_id="", email=None, role="anon")
    return await get_current_user(authorization=authorization, conn=conn)


def require_role(min_role: str, allow_anonymous: bool = False) -> Callable[..., CurrentUser]:
    """Dependency factory to enforce role-based access control.

    min_role:
    - 'public' or allow_anonymous=True: allows 'anon', 'viewer', 'forecaster', 'admin'
    - 'any': allows authenticated 'viewer', 'forecaster', 'admin'
    - 'forecaster+': allows 'forecaster', 'admin'
    - 'admin': allows 'admin' only
    """
    if min_role == "public" or allow_anonymous:
        def public_role_checker(current_user: CurrentUser = Depends(get_optional_user)) -> CurrentUser:
            return current_user
        return public_role_checker

    def role_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user_role = current_user.role

        if min_role == "any":
            return current_user

        if min_role == "forecaster+":
            if user_role in ("forecaster", "admin"):
                return current_user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Action requires forecaster or admin privileges (current role: {user_role}).",
                    "retry_after": None,
                },
            )

        if min_role == "admin":
            if user_role == "admin":
                return current_user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Action requires admin privileges (current role: {user_role}).",
                    "retry_after": None,
                },
            )

        return current_user

    return role_checker
