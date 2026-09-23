"""Supabase JWT verification helper.

Supports:
1. Asymmetric ES256 verification via Supabase JWKS (.well-known/jwks.json).
2. Symmetric HS256 verification using SUPABASE_JWT_SECRET (for local/testing).
3. Live Supabase client auth verification fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient

from api.app.db.supabase import get_supabase_client
from core.config import settings

logger = logging.getLogger("aagam.api.auth.jwt")

_jwks_client: Optional[PyJWKClient] = None


def get_jwks_client() -> Optional[PyJWKClient]:
    """Returns a cached PyJWKClient instance for the Supabase JWKS endpoint."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    jwks_url = settings.jwks_url
    if jwks_url:
        try:
            _jwks_client = PyJWKClient(jwks_url, cache_keys=True, max_cached_keys=10)
            return _jwks_client
        except Exception as e:
            logger.warning(f"Failed to initialize PyJWKClient with {jwks_url}: {e}")
            return None
    return None


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """Verifies a Supabase JWT and returns its claims payload.

    Raises:
        jwt.PyJWTError: If token is expired, has an invalid signature, or is malformed.
    """
    # 0. Local Demo authentication (strictly when ENABLE_LOCAL_DEMO_AUTH is true and token is a demo token)
    if settings.ENABLE_LOCAL_DEMO_AUTH:
        # Match direct demo tokens
        if token in ("demo-public-token", "demo-token-public"):
            return {
                "sub": "00000000-0000-0000-0000-000000000001",
                "email": "public@aagam.gov.in",
                "role": "authenticated",
                "app_metadata": {"role": "public"},
                "user_metadata": {"role": "public"},
            }
        elif token in ("demo-forecaster-token", "demo-token-forecaster"):
            return {
                "sub": "00000000-0000-0000-0000-000000000002",
                "email": "forecaster@aagam.gov.in",
                "role": "authenticated",
                "app_metadata": {"role": "forecaster"},
                "user_metadata": {"role": "forecaster"},
            }
        elif token in ("demo-coordinator-token", "demo-token-coordinator"):
            return {
                "sub": "00000000-0000-0000-0000-000000000003",
                "email": "coordinator@aagam.gov.in",
                "role": "authenticated",
                "app_metadata": {"role": "coordinator"},
                "user_metadata": {"role": "coordinator"},
            }

    # 1. Try symmetric verification if SUPABASE_JWT_SECRET is explicitly configured
    if settings.SUPABASE_JWT_SECRET:
        try:
            return jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise
        except jwt.PyJWTError as e:
            logger.debug(f"HS256 verification failed: {e}")

    # 2. Try asymmetric JWKS verification (standard Supabase default)
    jwks_client = get_jwks_client()
    if jwks_client:
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256", "HS256"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise
        except Exception as e:
            logger.debug(f"JWKS verification failed: {e}")

    # 3. Fallback: Verify directly via Supabase Auth API if client is available
    client = get_supabase_client()
    if client:
        try:
            user_resp = client.auth.get_user(token)
            if user_resp and user_resp.user:
                return {
                    "sub": str(user_resp.user.id),
                    "email": user_resp.user.email,
                    "role": "authenticated",
                    "user_metadata": user_resp.user.user_metadata or {},
                    "app_metadata": user_resp.user.app_metadata or {},
                }
        except Exception as e:
            logger.debug(f"Supabase auth API fallback verification failed: {e}")

    # If all methods failed, raise error
    raise jwt.InvalidTokenError("Token signature or credentials could not be verified against Supabase.")
