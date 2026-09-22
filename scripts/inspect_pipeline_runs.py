import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
with conn.cursor() as cur:
    print("=== Pipeline Runs before 2026-09-22 00:00:00 UTC ===")
    cur.execute("""
        SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
        FROM pipeline_runs
        WHERE started_at < '2026-09-22 00:00:00+00'
        ORDER BY started_at ASC;
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    for r in rows:
        d = dict(zip(cols, r))
        print(f"ID: {d['id']:3d} | Job: {d['job']:22s} | Started: {str(d['started_at'])} | Status: {d['status']:7s} | Rows: {d['rows_written']} | Msg: {str(d['message'])[:80]}")

    print("\n=== Recent Non-Pytest Pipeline Runs (Checking for deployed 6h scheduler runs) ===")
    cur.execute("""
        SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
        FROM pipeline_runs
        WHERE started_at >= '2026-09-22 00:00:00+00'
          AND message NOT LIKE '%Successfully blended 960 forecasts%'
          AND message NOT LIKE '%Cleaned 2886 expired%'
          AND message NOT LIKE '%Nightly backup FAILED for 1 table(s)%'
        ORDER BY started_at ASC;
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} matching recent runs:")
    for r in rows:
        d = dict(zip(cols, r))
        print(f"ID: {d['id']:3d} | Job: {d['job']:22s} | Started: {str(d['started_at'])} | Status: {d['status']:7s} | Rows: {d['rows_written']} | Msg: {str(d['message'])[:80]}")
conn.close()
