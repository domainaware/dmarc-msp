"""Dashboard import CLI commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_db_session, get_settings
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService

app = typer.Typer(help="Dashboard management commands.", no_args_is_help=True)
console = Console()


@app.command("import")
def import_dashboards(
    client: str = typer.Option(..., "--client", help="Client name"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Import dashboards into a client's tenant."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        dash_svc = DashboardService(settings.dashboards, settings.opensearch)
        dash_svc.import_for_client(client_row.tenant_name, client_row.index_prefix)
        console.print(
            f"Imported dashboards for [bold]{client_row.name}[/bold] "
            f"(tenant={client_row.tenant_name})"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
