"""AAGAM Notifications Package (PRD §6.12, Tech Stack §8a)."""

from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.daily_summary import run_daily_summary_job
from pipeline.notify.lifecycle import process_lifecycle_notifications
from pipeline.notify.templates import (
    format_daily_summary_email,
    format_lifecycle_email,
)

__all__ = [
    "BrevoClient",
    "process_lifecycle_notifications",
    "run_daily_summary_job",
    "format_lifecycle_email",
    "format_daily_summary_email",
]
