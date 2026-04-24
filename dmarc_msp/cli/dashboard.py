"""Dashboard import CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_db_session, get_settings
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService

app = typer.Typer(help="Dashboard management commands.", no_args_is_help=True)
console = Console()


@app.command("import")
def import_dashboards(
    client: str = typer.Argument(..., help="Client name"),
    replace: bool = typer.Option(
        False,
        "--replace",
        help=(
            "Delete every template saved object from the tenant before "
            "importing. Use when an overwrite import silently fails to "
            "update a dashboard or visualization."
        ),
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Import dashboards into a client's tenant."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        dash_svc = DashboardService(settings.dashboards, settings.opensearch)
        dash_svc.import_for_client(
            client_row.tenant_name, client_row.index_prefix, replace=replace
        )
        console.print(
            f"Imported dashboards for [bold]{client_row.name}[/bold] "
            f"(tenant={client_row.tenant_name})"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("dark-mode")
def dark_mode(
    client: str = typer.Argument(..., help="Client name"),
    enabled: bool = typer.Argument(..., help="Enable or disable dark mode"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Enable or disable dark mode for a client's tenant."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        dash_svc = DashboardService(settings.dashboards, settings.opensearch)
        dash_svc.set_dark_mode(client_row.tenant_name, enabled)
        state = "enabled" if enabled else "disabled"
        console.print(
            f"Dark mode {state} for [bold]{client_row.name}[/bold] "
            f"(tenant={client_row.tenant_name})"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("import-all")
def import_all_dashboards(
    replace: bool = typer.Option(
        False,
        "--replace",
        help=(
            "Delete every template saved object from each tenant before "
            "importing. Use when an overwrite import silently fails to "
            "update a dashboard or visualization."
        ),
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Re-import dashboards into every active client's tenant."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        clients = client_svc.list(include_offboarded=False)
        if not clients:
            console.print("No active clients found.")
            return

        dash_svc = DashboardService(settings.dashboards, settings.opensearch)
        failed = []
        for client_row in clients:
            try:
                dash_svc.import_for_client(
                    client_row.tenant_name,
                    client_row.index_prefix,
                    replace=replace,
                )
                console.print(
                    f"  [green]✓[/green] {client_row.name} "
                    f"(tenant={client_row.tenant_name})"
                )
            except Exception as e:
                failed.append((client_row.name, e))
                console.print(f"  [red]✗[/red] {client_row.name}: {e}")

        total = len(clients)
        ok = total - len(failed)
        console.print(f"\nImported dashboards for {ok}/{total} clients.")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
