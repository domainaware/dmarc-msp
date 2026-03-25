"""Tenant provisioning CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_db_session, get_settings
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.opensearch import OpenSearchService

app = typer.Typer(help="OpenSearch tenant management.", no_args_is_help=True)
console = Console()


@app.command()
def provision(
    client: str = typer.Option(..., "--client", help="Client name"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Provision an OpenSearch tenant and role for a client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        os_svc = OpenSearchService(settings.opensearch)
        os_svc.provision_tenant(client_row.tenant_name)
        os_svc.create_client_role(client_row.tenant_name, client_row.index_prefix)
        console.print(f"Provisioned tenant: [bold]{client_row.tenant_name}[/bold]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def deprovision(
    client: str = typer.Option(..., "--client", help="Client name"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Deprovision an OpenSearch tenant and role for a client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        os_svc = OpenSearchService(settings.opensearch)
        os_svc.deprovision_tenant(client_row.tenant_name)
        os_svc.delete_client_role(client_row.tenant_name)
        console.print(f"Deprovisioned tenant: [bold]{client_row.tenant_name}[/bold]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
