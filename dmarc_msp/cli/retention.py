"""Retention management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_settings
from dmarc_msp.services.retention import RetentionService

app = typer.Typer(help="Retention management commands.", no_args_is_help=True)
console = Console()


@app.command("cleanup-emails")
def cleanup_emails(
    maildir: str = typer.Option("/var/mail/dmarc/Maildir", "--maildir", help="Path to Maildir"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Delete processed email files older than retention.email_days."""
    settings = get_settings(config)
    svc = RetentionService(settings.opensearch, settings.retention)
    deleted = svc.cleanup_emails(maildir)
    console.print(
        f"Deleted {deleted} files older than {settings.retention.email_days} days"
    )


@app.command("ensure-default-policy")
def ensure_default_policy(
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Create or update the default ISM retention policy."""
    settings = get_settings(config)
    svc = RetentionService(settings.opensearch, settings.retention)
    svc.ensure_default_policy()
    console.print(
        "Default retention policy ensured"
        f" ({settings.retention.index_default_days} days)"
    )
