import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
with conn.cursor() as cur:
    print("=== All ingest-blend runs in database ===")
    cur.execute("""
        SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
        FROM pipeline_runs
        WHERE job in ('ingest-blend', 'operational_blend', 'live_forecast_ingestion')
        ORDER BY id ASC;
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"Total runs: {len(rows)}")
    for r in rows:
        d = dict(zip(cols, r))
        print(f"ID: {d['id']:3d} | Job: {d['job']:22s} | Started: {str(d['started_at'])} | Status: {d['status']:7s} | Rows: {d['rows_written']} | Msg: {str(d['message'])[:85]}")

    print("\n=== Unique message patterns in ingest-blend ===")
    cur.execute("""
        SELECT message, count(*), min(started_at), max(started_at)
        FROM pipeline_runs
        WHERE job in ('ingest-blend', 'operational_blend')
        GROUP BY message
        ORDER BY count(*) DESC;
    """)
    for r in cur.fetchall():
        print(f"Count: {r[1]:3d} | Min: {r[2]} | Max: {r[3]} | Msg: {str(r[0])[:85]}")
conn.close()
