"""Client management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import (
    get_db_session,
    get_offboarding_service,
    get_settings,
)
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.opensearch import OpenSearchService
from dmarc_msp.services.retention import RetentionService

app = typer.Typer(help="Client management commands.", no_args_is_help=True)
console = Console()


@app.command()
def create(
    name: str = typer.Argument(..., help="Client name"),
    contact: str | None = typer.Option(None, "--contact", help="Contact email"),
    index_prefix: str | None = typer.Option(None, "--index-prefix"),
    retention_days: int | None = typer.Option(None, "--retention-days"),
    notes: str | None = typer.Option(None, "--notes"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Create a new client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
        # Verify OpenSearch is reachable before creating the client
        try:
            os_svc = OpenSearchService(settings.opensearch)
            os_svc.health()
        except Exception as e:
            console.print(
                f"[red]Error:[/red] Cannot connect to OpenSearch: {e}"
            )
            raise typer.Exit(1)

        client = svc.create(
            name=name,
            contact_email=contact,
            index_prefix=index_prefix,
            notes=notes,
            retention_days=retention_days,
        )
        console.print(f"Created client: [bold]{client.name}[/bold]")
        console.print(f"  Index prefix: {client.index_prefix}")
        console.print(f"  Tenant:       {client.tenant_name}")

        # Provision OpenSearch tenant, role, and dashboards
        os_svc.provision_tenant(client.tenant_name)
        os_svc.create_client_role(client.tenant_name, client.index_prefix)
        console.print("  OpenSearch:   tenant + role provisioned")

        if client.retention_days:
            ret_svc = RetentionService(settings.opensearch, settings.retention)
            ret_svc.create_client_policy(
                client.index_prefix, client.retention_days
            )

        dash_svc = DashboardService(settings.dashboards, settings.opensearch)
        dash_svc.import_for_client(client.tenant_name, client.index_prefix)
        console.print("  Dashboards:   imported")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("list")
def list_clients(
    all: bool = typer.Option(False, "--all", help="Include offboarded clients"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """List all clients."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
        clients = svc.list(include_offboarded=all)
        if not clients:
            console.print("No clients found.")
            return

        table = Table(title="Clients")
        table.add_column("Name")
        table.add_column("Prefix")
        table.add_column("Domains")
        table.add_column("Status")
        table.add_column("Contact")

        for c in clients:
            active_count = len(c.active_domains)
            table.add_row(
                c.name,
                c.index_prefix,
                str(active_count),
                c.status,
                c.contact_email or "",
            )
        console.print(table)
    finally:
        db.close()


@app.command()
def show(
    name: str = typer.Argument(..., help="Client name"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Show full client status."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
        client = svc.get(name)
        console.print(f"[bold]{client.name}[/bold]")
        console.print(f"  Status:         {client.status}")
        console.print(f"  Index prefix:   {client.index_prefix}")
        console.print(f"  Tenant:         {client.tenant_name}")
        console.print(f"  Contact:        {client.contact_email or '—'}")
        console.print(f"  Retention:      {client.retention_days or 'default'} days")
        console.print(f"  Created:        {client.created_at}")
        console.print(f"  Notes:          {client.notes or '—'}")
        console.print()

        if client.domains:
            table = Table(title="Domains")
            table.add_column("Domain")
            table.add_column("Status")
            table.add_column("DNS Verified")
            table.add_column("Added")
            for d in client.domains:
                table.add_row(
                    d.domain_name,
                    d.status,
                    "yes" if d.dns_verified else "no",
                    str(d.created_at.date()) if d.created_at else "—",
                )
            console.print(table)
        else:
            console.print("  No domains.")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def update(
    name: str = typer.Argument(..., help="Client name"),
    contact: str | None = typer.Option(None, "--contact"),
    notes: str | None = typer.Option(None, "--notes"),
    retention_days: int | None = typer.Option(None, "--retention-days"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Update client details."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
        kwargs = {}
        if contact is not None:
            kwargs["contact_email"] = contact
        if notes is not None:
            kwargs["notes"] = notes
        if retention_days is not None:
            kwargs["retention_days"] = retention_days
        client = svc.update(name, **kwargs)
        console.print(f"Updated client: [bold]{client.name}[/bold]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def rename(
    name: str = typer.Argument(..., help="Current client name"),
    new_name: str = typer.Argument(..., help="New client name"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Rename a client. Index prefix and tenant name stay the same."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
        client = svc.rename(name, new_name)
        console.print(
            f"Renamed to [bold]{client.name}[/bold] "
            f"(index prefix: {client.index_prefix} — unchanged)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def offboard(
    name: str = typer.Argument(..., help="Client name"),
    purge_indices: bool = typer.Option(False, "--purge-indices"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Offboard a client (remove DNS, deprovision tenant)."""
    settings = get_settings(config)
    db = get_db_session(settings)

    if dry_run:
        svc = ClientService(db)
        client = svc.get(name)
        console.print(f"[yellow]Dry run[/yellow] — would offboard '{client.name}':")
        console.print(f"  Domains to remove: {len(client.active_domains)}")
        for d in client.active_domains:
            console.print(f"    - {d.domain_name}")
        console.print(f"  Purge indices: {purge_indices}")
        db.close()
        return

    try:
        svc = get_offboarding_service(settings, db)
        result = svc.offboard_client(
            name, purge_dns=True, purge_indices=purge_indices
        )
        console.print(
            f"Offboarded [bold]{result.client_name}[/bold] "
            f"({result.domains_removed} domains removed)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
