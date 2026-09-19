"""AAGAM — Database setup script to apply Phase 1 migrations."""
import logging
import sys
from pathlib import Path

import psycopg2

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.db")


def apply_migrations():
    """Applies Phase 1 data foundation SQL migration."""
    db_url = settings.DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not found in settings / .env.")
        sys.exit(1)

    migration_file = Path(__file__).resolve().parent.parent.parent / "supabase" / "migrations" / "20260919000002_phase1_data_foundation.sql"
    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        sys.exit(1)

    with open(migration_file, "r", encoding="utf-8") as f:
        sql = f.read()

    logger.info("Connecting to database via DATABASE_URL...")
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            logger.info("Executing Phase 1 migration SQL...")
            cur.execute(sql)
            logger.info("Migration executed successfully!")

            # Verify tables exist
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('locations', 'model_forecasts', 'pipeline_runs');
            """)
            tables = [row[0] for row in cur.fetchall()]
            logger.info(f"Verified tables present in public schema: {tables}")
            if len(tables) < 3:
                logger.error(f"Expected 3 tables, but found: {tables}")
                sys.exit(1)
        conn.close()
        logger.info("Database setup complete.")
    except Exception as e:
        logger.error(f"Failed to apply migration: {e}")
        sys.exit(1)


if __name__ == "__main__":
    apply_migrations()
