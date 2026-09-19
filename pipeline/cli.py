"""AAGAM Pipeline CLI (Phase 0 Scaffold).

Full scheduled ingestion, blending, and retraining jobs belong to Phase 1-4.
"""
import typer

app = typer.Typer(help="AAGAM Scheduled Data & ML Pipeline CLI")


@app.command()
def status():
    """Print pipeline scaffolding status."""
    typer.echo("AAGAM Pipeline: Phase 0 Setup Scaffold. Production jobs scheduled for Phase 1-4.")


if __name__ == "__main__":
    app()
