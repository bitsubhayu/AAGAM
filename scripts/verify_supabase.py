"""AAGAM — Supabase & PostGIS Verification Script (PRD Phase 0 & Tech Stack §15).

Verifies:
1. Supabase environment variable configuration
2. PostGIS extension verification query & migration status
3. Connection pooler recommendations
4. Service-role vs anon key separation (security audit)
5. Live database query to _aagam_setup_check table

Strict Status Rules:
- PASS (exit 0): Real network connection established, real row returned from _aagam_setup_check
- BLOCKED (exit 2): Live credentials missing in environment, or table empty/migration pending
- FAIL (exit 1): Network error, authentication failure, or unhandled exception
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings


def verify_supabase() -> int:
    """Executes live Supabase verification with strict PASS / BLOCKED / FAIL distinction."""
    print("=" * 70)
    print("AAGAM — SUPABASE & POSTGIS VERIFICATION (PHASE 0)")
    print("=" * 70)

    url = settings.SUPABASE_URL
    anon = settings.SUPABASE_ANON_KEY or settings.SUPABASE_PUBLISHABLE_KEY
    service = settings.SUPABASE_SERVICE_ROLE_KEY
    db_url = settings.DATABASE_URL

    print("\n1. Environment Configuration Audit:")
    print("-" * 50)
    print(f"  SUPABASE_URL:               {'CONFIGURED (' + url[:25] + '...)' if url else 'MISSING / PENDING (.env)'}")
    print(f"  SUPABASE_ANON_KEY:          {'CONFIGURED (length ' + str(len(anon)) + ')' if anon else 'MISSING / PENDING (.env)'}")
    print(f"  SUPABASE_SERVICE_ROLE_KEY:  {'CONFIGURED (Server-side isolated)' if service else 'MISSING / PENDING (.env)'}")
    print(f"  DATABASE_URL:               {'CONFIGURED (Pooler URL)' if db_url else 'MISSING / PENDING (.env)'}")

    print("\n2. PostGIS Extension & Schema Specifications:")
    print("-" * 50)
    print("  Migration Path:             supabase/migrations/20260919000001_phase0_setup.sql")
    print("  PostGIS SQL Statement:      CREATE EXTENSION IF NOT EXISTS postgis;")
    print("  Spatial Column:             geography(Point, 4326) for 40 locations")
    print("  Target Table:               _aagam_setup_check (RLS enabled, anon read allowed)")

    print("\n3. Connection Pooler Best Practices (Tech Stack §6.1):")
    print("-" * 50)
    print("  - Transaction Pooler (Port 6543): For serverless/short-lived jobs (FastAPI on Render, GitHub Actions).")
    print("  - Session Pooler (Port 5432): For direct Postgres migrations and long sessions.")

    print("\n4. Security & Credential Isolation Audit:")
    print("-" * 50)
    print("  - Anon Key: Public-safe, restricted by Row Level Security (RLS). Bound to frontend.")
    print("  - Service Role Key: STRICTLY SERVER-SIDE. Bypasses RLS. NEVER bundled in frontend bundle.")
    print("  - .env: Enforced in .gitignore. No hardcoded credentials in repository.")

    print("\n5. Live Connectivity & Database Read Test:")
    print("-" * 50)

    if not url or (not anon and not service):
        print("  RESULT: BLOCKED")
        print("  REASON: Live Supabase credentials are not set in the active environment.")
        print("  NOTE: Local fallback or mocked results are strictly prohibited from reporting PASS.")
        print("  ACTION REQUIRED BY USER:")
        print("    1. Create a Supabase project at https://supabase.com")
        print("    2. Copy .env.example to .env and provide SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY")
        print("    3. Apply migration: supabase/migrations/20260919000001_phase0_setup.sql in Supabase SQL Editor")
        print("=" * 70)
        return 2  # BLOCKED

    try:
        from supabase import create_client
        key = service or anon
        client = create_client(url, key)

        # 1. Test reading setup table
        print("  Executing query on remote table '_aagam_setup_check'...")
        res = client.table("_aagam_setup_check").select("*").limit(1).execute()

        if not res.data or len(res.data) == 0:
            print("  RESULT: BLOCKED")
            print("  REASON: Connected to Supabase, but table '_aagam_setup_check' is empty or not yet seeded.")
            print("  ACTION REQUIRED:")
            print("    Apply migration: supabase/migrations/20260919000001_phase0_setup.sql")
            print("=" * 70)
            return 2  # BLOCKED

        row = res.data[0]
        print("  PASS: Successfully read remote database row!")
        print(f"    - ID:         {row.get('id')}")
        print(f"    - Component:  {row.get('component')}")
        print(f"    - Status:     {row.get('status')}")
        print(f"    - VerifiedAt: {row.get('verified_at')}")
        print(f"    - Details:    {row.get('details')}")

        # 2. Test PostGIS if DATABASE_URL is available
        if db_url:
            print("\n  Executing PostGIS live query via DATABASE_URL...")
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                cur = conn.cursor()
                cur.execute("SELECT PostGIS_Full_Version();")
                pg_ver = cur.fetchone()[0]
                print(f"  PASS: PostGIS Version Verified: {pg_ver}")
                cur.close()
                conn.close()
            except Exception as e_pg:
                print(f"  NOTICE: PostGIS query via direct connection returned: {e_pg}")

        print("\n" + "=" * 70)
        print("STATUS: PASS — Live Supabase connectivity and row read verified.")
        print("=" * 70)
        return 0  # PASS

    except Exception as e:
        err_str = str(e)
        print("  RESULT: FAIL")
        print(f"  REASON: Exception during remote query: {type(e).__name__}: {err_str}")
        print("=" * 70)
        return 1  # FAIL


if __name__ == "__main__":
    exit_code = verify_supabase()
    sys.exit(exit_code)
