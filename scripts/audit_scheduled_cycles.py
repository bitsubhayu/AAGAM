import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
with conn.cursor() as cur:
    print("=== Operational Runs Audit (Excluding rapid automated test loop bursts) ===")
    cur.execute("""
        SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
        FROM pipeline_runs
        WHERE job in ('ingest-blend', 'operational_blend')
          AND status = 'SUCCESS'
        ORDER BY started_at ASC;
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"Total successful ingest-blend runs: {len(rows)}")

    # Group runs into clusters by timestamp (runs separated by > 30 minutes)
    clusters = []
    current_cluster = []
    for r in rows:
        d = dict(zip(cols, r))
        if not current_cluster:
            current_cluster.append(d)
        else:
            prev_time = current_cluster[-1]["started_at"]
            curr_time = d["started_at"]
            if (curr_time - prev_time).total_seconds() > 1800:  # > 30 min gap
                clusters.append(current_cluster)
                current_cluster = [d]
            else:
                current_cluster.append(d)
    if current_cluster:
        clusters.append(current_cluster)

    print(f"\nIdentified {len(clusters)} distinct operational run clusters / sessions:")
    for idx, cl in enumerate(clusters, 1):
        first_run = cl[0]
        last_run = cl[-1]
        print(f"\n--- Cluster {idx} (Runs: {len(cl)}) ---")
        print(f"  First Run: ID {first_run['id']} at {first_run['started_at']} | Rows: {first_run['rows_written']} | Status: {first_run['status']}")
        print(f"  Last Run:  ID {last_run['id']} at {last_run['started_at']} | Rows: {last_run['rows_written']} | Status: {last_run['status']}")
        print(f"  Sample Msg: {first_run['message'][:85]}")

conn.close()
