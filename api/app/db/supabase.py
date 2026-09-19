import logging
from typing import Any, Dict, Optional, Tuple

from core.config import settings
from supabase import Client, create_client

logger = logging.getLogger("aagam.db")

_supabase_client: Optional[Client] = None


def get_supabase_client() -> Optional[Client]:
    """Returns initialized Supabase client or None if credentials are not configured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = settings.SUPABASE_URL
    # Prefer service role key on backend if present, else anon key
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY

    if not url or not key:
        logger.warning("SUPABASE_URL or API key not set in environment.")
        return None

    try:
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None


def read_setup_row() -> Tuple[str, Optional[Dict[str, Any]], str]:
    """
    Reads a real row from Supabase to fulfill PRD Phase 0 condition:
    'hello-world API on Render reads a row from Supabase'

    Returns:
        (status, row_data, message)
        status: "PASS" (real DB read), "BLOCKED" (credentials/migration missing), or "FAIL" (broken/error)
    """
    client = get_supabase_client()
    if client is None:
        return "BLOCKED", None, "Supabase client not configured (SUPABASE_URL or API key missing in environment)"

    try:
        # 1. Attempt reading from Phase 0 setup verification table
        res = client.table("_aagam_setup_check").select("*").limit(1).execute()
        if res.data and len(res.data) > 0:
            return "PASS", res.data[0], "Read from _aagam_setup_check table successfully"
        else:
            return "BLOCKED", None, "Table _aagam_setup_check exists but has no rows; apply migration 20260919000001_phase0_setup.sql"
    except Exception as e:
        err_msg = str(e)
        logger.warning(f"_aagam_setup_check query failed: {err_msg}")
        # Distinguish between unapplied migration / table missing (BLOCKED) vs broken connection (FAIL)
        if "relation" in err_msg.lower() or "not found" in err_msg.lower() or "404" in err_msg or "PGRST204" in err_msg:
            return "BLOCKED", None, f"Table _aagam_setup_check not yet created; apply migration 20260919000001_phase0_setup.sql ({err_msg})"
        elif "jwt" in err_msg.lower() or "auth" in err_msg.lower() or "invalid api key" in err_msg.lower() or "401" in err_msg:
            return "FAIL", None, f"Supabase authentication failure: {err_msg}"
        else:
            return "FAIL", None, f"Supabase query error: {err_msg}"
