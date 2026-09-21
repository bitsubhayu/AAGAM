"""Database connection helper for AAGAM pipeline."""
import psycopg2

from core.config import settings


def get_db_connection():
    """Returns a new psycopg2 connection using settings.DATABASE_URL."""
    if not settings.DATABASE_URL:
        raise ValueError("DATABASE_URL is not set in environment or settings.")
    return psycopg2.connect(settings.DATABASE_URL)
