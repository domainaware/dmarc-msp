"""Client management CLI commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import (
    get_db_session,
    get_offboarding_service,
    get_settings,
)
from dmarc_msp.services.clients import ClientService

app = typer.Typer(help="Client management commands.", no_args_is_help=True)
console = Console()


@app.command()
def create(
    name: str = typer.Argument(..., help="Client name"),
    contact: Optional[str] = typer.Option(None, "--contact", help="Contact email"),
    index_prefix: Optional[str] = typer.Option(None, "--index-prefix"),
    retention_days: Optional[int] = typer.Option(None, "--retention-days"),
    notes: Optional[str] = typer.Option(None, "--notes"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Create a new client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    svc = ClientService(db)
    try:
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
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("list")
def list_clients(
    all: bool = typer.Option(False, "--all", help="Include offboarded clients"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
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
    config: Optional[str] = typer.Option(None, "--config", "-c"),
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
    contact: Optional[str] = typer.Option(None, "--contact"),
    notes: Optional[str] = typer.Option(None, "--notes"),
    retention_days: Optional[int] = typer.Option(None, "--retention-days"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
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
def offboard(
    name: str = typer.Argument(..., help="Client name"),
    purge_indices: bool = typer.Option(False, "--purge-indices"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
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
