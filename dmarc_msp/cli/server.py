"""Server-related CLI commands (hidden subcommand group)."""

from __future__ import annotations

import typer

app = typer.Typer(help="Server management.", no_args_is_help=True)
