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


def read_setup_row() -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Reads a real row from Supabase to fulfill PRD Phase 0 condition:
    'hello-world API on Render reads a row from Supabase'
    """
    client = get_supabase_client()
    if client is None:
        return False, None, "Supabase client not configured (SUPABASE_URL/KEY missing in environment)"

    try:
        # 1. Attempt reading from Phase 0 setup verification table
        res = client.table("_aagam_setup_check").select("*").limit(1).execute()
        if res.data and len(res.data) > 0:
            return True, res.data[0], "Read from _aagam_setup_check table successfully"
    except Exception as e:
        logger.info(f"_aagam_setup_check query failed, trying fallback: {e}")

    try:
        # 2. Fallback: try locations table if already created
        res = client.table("locations").select("*").limit(1).execute()
        if res.data and len(res.data) > 0:
            return True, res.data[0], "Read from locations table successfully"
    except Exception as e:
        logger.warning(f"locations table query failed: {e}")

    return False, None, "Database reachable or connected, but setup table has not been populated yet"
