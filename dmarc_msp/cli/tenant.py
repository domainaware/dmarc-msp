"""Tenant provisioning CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import get_db_session, get_settings
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.opensearch import OpenSearchService

app = typer.Typer(help="OpenSearch tenant management.", no_args_is_help=True)
console = Console()


@app.command()
def provision(
    client: str = typer.Argument(..., help="Client name"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Provision an OpenSearch tenant and role for a client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client)
        os_svc = OpenSearchService(settings.opensearch)
        os_svc.provision_tenant(client_row.tenant_name, client_row.index_prefix)
        console.print(f"Provisioned tenant: [bold]{client_row.tenant_name}[/bold]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def deprovision(
    client: str = typer.Argument(..., help="Client name"),
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
        console.print(f"Deprovisioned tenant: [bold]{client_row.tenant_name}[/bold]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("migrate-prefix")
def migrate_prefix(
    config: str | None = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without making changes"),
):
    """Migrate tenant names to use the 'client_' prefix.

    Required for wildcard-based analyst role access. Safe to re-run.
    """
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        os_svc = OpenSearchService(settings.opensearch)
        dash_svc = DashboardService(settings.dashboards, settings.opensearch)

        if not dry_run:
            try:
                os_svc.health()
            except Exception as e:
                console.print(f"[red]Error:[/red] Cannot connect to OpenSearch: {e}")
                raise typer.Exit(1)

        clients = client_svc.list(include_offboarded=False)
        to_migrate = [c for c in clients if not c.tenant_name.startswith("client_")]

        if not to_migrate:
            console.print("All tenants already have the 'client_' prefix. Nothing to do.")
            return

        table = Table(title="Tenant Prefix Migration" + (" (dry run)" if dry_run else ""))
        table.add_column("Client")
        table.add_column("Old Tenant")
        table.add_column("New Tenant")
        table.add_column("Status")

        migrated = 0
        for client_row in to_migrate:
            new_tenant = f"client_{client_row.index_prefix}"
            old_tenant = client_row.tenant_name

            if dry_run:
                table.add_row(client_row.name, old_tenant, new_tenant, "[yellow]pending[/yellow]")
                continue

            try:
                # Create new tenant
                os_svc.provision_tenant(new_tenant, client_row.index_prefix)
                # Import dashboards into new tenant
                dash_svc.import_for_client(new_tenant, client_row.index_prefix)
                # Delete old tenant only (role name is unchanged)
                try:
                    os_svc.client.transport.perform_request(
                        "DELETE",
                        f"/_plugins/_security/api/tenants/{old_tenant}",
                    )
                except Exception:
                    pass
                # Update DB
                client_row.tenant_name = new_tenant
                db.commit()
                db.refresh(client_row)
                table.add_row(client_row.name, old_tenant, new_tenant, "[green]migrated[/green]")
                migrated += 1
            except Exception as e:
                table.add_row(client_row.name, old_tenant, new_tenant, f"[red]failed: {e}[/red]")

        console.print(table)
        if dry_run:
            console.print(f"\n{len(to_migrate)} tenant(s) would be migrated. Run without --dry-run to apply.")
        else:
            console.print(f"\n{migrated}/{len(to_migrate)} tenant(s) migrated.")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
