"""AAGAM Scheduled Data & ML Pipeline CLI (Phase 5 Production Interface).

Provides entry points for all operational workflows:
- python -m pipeline ingest-live
- python -m pipeline verify
- python -m pipeline train
- python -m pipeline backup
- python -m pipeline migrate
- python -m pipeline status
"""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="AAGAM Scheduled Data & ML Pipeline CLI")
console = Console()
logger = logging.getLogger("aagam.pipeline.cli")


@app.command("ingest-live")
def ingest_live_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without mutating DB or hitting external APIs"),
):
    """Fetch live forecasts, aggregate to IST daily, blend with active model, and evaluate hazards."""
    console.print("[bold green]Starting Live Ingestion & Blending Cycle...[/bold green]")
    from pipeline.live.runner import live_runner

    result = live_runner.run_ingest_and_blend(dry_run=dry_run)
    console.print(f"[bold]Result:[/bold] {result}")
    if result.get("status") in ["SUCCESS", "HALTED"]:
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)


@app.command("verify")
def verify_cmd(
    window_days: int = typer.Option(60, "--window-days", "-w", help="Trailing verification evaluation window"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run verification without writing to DB"),
):
    """Run daily verification of model and blended forecasts against ground truth."""
    console.print(f"[bold green]Starting Daily Verification (window={window_days}d, dry_run={dry_run})...[/bold green]")
    from pipeline.live.verification_runner import verification_runner

    result = verification_runner.run_daily_verification(window_days=window_days, dry_run=dry_run)
    console.print(f"[bold]Result:[/bold] {result}")
    raise typer.Exit(code=0)


@app.command("train")
def train_cmd(
    retrain_date: Optional[str] = typer.Option(None, "--retrain-date", "-d", help="Retraining version date (YYYYMMDD)"),
    tolerance: float = typer.Option(0.02, "--tolerance", "-t", help="Quality gate validation MAE tolerance (default 2%)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Evaluate models and quality gate without updating DB"),
):
    """Run weekly model retraining with automated quality-gate verification and registry update."""
    console.print(f"[bold green]Starting Weekly Retraining (tolerance={tolerance*100:.1f}%, dry_run={dry_run})...[/bold green]")
    from pipeline.live.retrain_runner import retrain_runner

    result = retrain_runner.run_weekly_retraining(
        retrain_date=retrain_date,
        tolerance=tolerance,
        dry_run=dry_run,
    )
    console.print(f"[bold]Result:[/bold] {result}")
    raise typer.Exit(code=0)


@app.command("backup")
def backup_cmd(
    backup_date: Optional[str] = typer.Option(None, "--backup-date", "-d", help="Backup version date (YYYYMMDD)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Export locally without uploading or purging DB"),
):
    """Run nightly backup of key tables to Parquet in Storage followed by retention cleanup."""
    console.print(f"[bold green]Starting Nightly Backup & Retention Cleanup (dry_run={dry_run})...[/bold green]")
    from pipeline.maintenance.retention import retention_engine

    result = retention_engine.run_nightly_backup(backup_date=backup_date, dry_run=dry_run)
    console.print(f"[bold]Result:[/bold] {result}")
    if result.get("status") == "SUCCESS":
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)
@app.command("climatology-backfill")
def climatology_backfill_cmd(
    truth_path: Optional[str] = typer.Option(None, "--truth-path", "-p", help="Path to Parquet truth observations"),
    min_years: int = typer.Option(15, "--min-years", "-y", help="Minimum years guard floor"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Calculate without database mutation"),
):
    """Run climatology percentiles backfill or annual refresh across stations (Phase 13)."""
    console.print(f"[bold green]Starting Climatology Percentiles Backfill (min_years={min_years}, dry_run={dry_run})...[/bold green]")
    from pipeline.climatology.backfill import run_climatology_backfill

    result = run_climatology_backfill(truth_source=truth_path, min_years=min_years, dry_run=dry_run)
    console.print(f"[bold]Result:[/bold] {result}")
    if result.get("status") == "SUCCESS":
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)




@app.command("migrate")
def migrate_cmd():
    """Apply all pending Supabase SQL migrations."""
    console.print("[bold green]Applying Supabase SQL migrations...[/bold green]")
    from pipeline.db.setup_tables import apply_migrations

    apply_migrations()
    console.print("[bold green]All migrations applied successfully.[/bold green]")


@app.command("status")
def status_cmd():
    """Display comprehensive operational status of AAGAM pipeline, database, and storage."""
    import psycopg2

    from core.config import settings
    from pipeline.models.registry import model_registry
    from pipeline.storage.manager import storage_manager

    console.print("[bold cyan]=== AAGAM Operational Pipeline Status ===[/bold cyan]\n")

    # 1. Active model version
    active = model_registry.get_active_version()
    if active:
        console.print(f"[bold]Active Model Version:[/bold] ID {active['id']} ({active['storage_path']}) registered at {active['created_at']}")
    else:
        console.print("[bold yellow]Active Model Version:[/bold yellow] None active")

    # 2. Storage buckets
    buckets = storage_manager.ensure_buckets()
    console.print(f"[bold]Storage Buckets:[/bold] {buckets}")

    # 3. Database latest pipeline runs
    if settings.DATABASE_URL:
        try:
            conn = psycopg2.connect(settings.DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT job, status, rows_written, api_calls_est, started_at, message
                    FROM pipeline_runs
                    ORDER BY id DESC
                    LIMIT 5;
                """)
                runs = cur.fetchall()

            table = Table(title="Recent Pipeline Runs (Observability)")
            table.add_column("Job", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Rows", justify="right")
            table.add_column("API Calls", justify="right")
            table.add_column("Started At")
            table.add_column("Message")

            for r in runs:
                status_style = "green" if r[1] == "SUCCESS" else ("yellow" if r[1] == "HALTED" else "red")
                table.add_row(
                    r[0],
                    f"[{status_style}]{r[1]}[/{status_style}]",
                    str(r[2] or 0),
                    str(r[3] or 0),
                    r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else "",
                    (r[5] or "")[:60],
                )
            console.print(table)
            conn.close()
        except Exception as e:
            console.print(f"[red]Could not query database runs: {e}[/red]")


if __name__ == "__main__":
    app()
