"""AAGAM Pipeline CLI Main Entrypoint.

Enables execution via `python -m pipeline <command>`.
"""
from pipeline.cli import app

if __name__ == "__main__":
    app()
