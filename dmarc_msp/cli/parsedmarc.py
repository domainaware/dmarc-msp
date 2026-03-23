"""parsedmarc reload CLI command."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_settings
from dmarc_msp.process.docker import DockerSignaler

app = typer.Typer(help="parsedmarc management commands.", no_args_is_help=True)
console = Console()


@app.command()
def reload(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Send SIGHUP to parsedmarc to reload configuration."""
    settings = get_settings(config)
    signaler = DockerSignaler(settings.parsedmarc.container)
    if signaler.send_sighup():
        console.print("[green]✓[/green] parsedmarc reloaded")
    else:
        console.print("[red]✗[/red] Failed to reload parsedmarc")
        raise typer.Exit(1)
