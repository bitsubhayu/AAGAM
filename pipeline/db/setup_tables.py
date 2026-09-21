"""AAGAM — Database setup script to apply all Supabase SQL migrations."""
import logging
import sys
from pathlib import Path

import psycopg2

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.db")

REQUIRED_TABLES = [
    "locations",
    "model_forecasts",
    "model_versions",
    "blended_forecasts",
    "weights",
    "skill_scores",
    "alerts",
    "profiles",
    "weight_overrides",
    "pipeline_runs",
    "chat_audit",
]


def apply_migrations():
    """Applies all Supabase SQL migrations in chronological sequence."""
    db_url = settings.DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not found in settings / .env.")
        sys.exit(1)

    migrations_dir = Path(__file__).resolve().parent.parent.parent / "supabase" / "migrations"
    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        sys.exit(1)

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        logger.error(f"No SQL migration files found in: {migrations_dir}")
        sys.exit(1)

    logger.info(f"Found {len(migration_files)} migration files in {migrations_dir}")

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            for mig_file in migration_files:
                logger.info(f"Executing migration: {mig_file.name}...")
                with open(mig_file, "r", encoding="utf-8") as f:
                    sql = f.read()
                cur.execute(sql)
                logger.info(f"Successfully applied {mig_file.name}")

            # Verify all required tables exist
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public';
            """)
            existing_tables = {row[0] for row in cur.fetchall()}
            missing = [t for t in REQUIRED_TABLES if t not in existing_tables]

            if missing:
                logger.error(f"Missing required tables in public schema: {missing}")
                sys.exit(1)
            else:
                logger.info(f"Verified all {len(REQUIRED_TABLES)} required core tables exist: {sorted(REQUIRED_TABLES)}")

            # Verify RLS enabled on all core tables
            cur.execute("""
                SELECT relname, relrowsecurity
                FROM pg_class
                JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                WHERE pg_namespace.nspname = 'public'
                  AND relname = ANY(%s);
            """, (REQUIRED_TABLES,))
            rls_status = dict(cur.fetchall())
            unsecured = [t for t, secured in rls_status.items() if not secured]
            if unsecured:
                logger.error(f"Tables without RLS enabled: {unsecured}")
                sys.exit(1)
            else:
                logger.info("Verified Row Level Security (RLS) is enabled on all core tables.")

        conn.close()
        logger.info("Database migration and verification complete.")
    except Exception as e:
        logger.error(f"Failed to apply migrations: {e}")
        sys.exit(1)


if __name__ == "__main__":
    apply_migrations()
