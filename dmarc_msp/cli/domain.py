"""Domain management CLI commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import (
    get_db_session,
    get_onboarding_service,
    get_settings,
)
from dmarc_msp.db import DomainRow
from dmarc_msp.services.clients import ClientService

app = typer.Typer(help="Domain management commands.", no_args_is_help=True)
console = Console()


@app.command()
def add(
    client: str = typer.Option(..., "--client", help="Client name"),
    domain: str = typer.Option(..., "--domain", help="Domain to add"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Add a domain to a client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        result = svc.add_domain(client, domain)
        console.print(f"Added [bold]{result.domain}[/bold] to {result.client_name}")
        console.print(f"  Tenant:       {result.tenant}")
        console.print(f"  DNS verified: {'yes' if result.dns_verified else 'pending'}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def remove(
    domain: str = typer.Option(..., "--domain", help="Domain to remove"),
    keep_dns: bool = typer.Option(False, "--keep-dns", help="Keep DNS records"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Remove a domain from monitoring."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        client_name = svc.remove_domain(domain, purge_dns=not keep_dns)
        console.print(
            f"Removed [bold]{domain}[/bold] from {client_name}"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def move(
    domain: str = typer.Option(..., "--domain", help="Domain to move"),
    to: str = typer.Option(..., "--to", help="Destination client name"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Move a domain to a different client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        result = svc.move_domain(domain, to)
        console.print(
            f"Moved [bold]{result.domain}[/bold]: "
            f"{result.from_client} → {result.to_client}"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def verify(
    domain: str = typer.Option(..., "--domain", help="Domain to verify"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Verify DNS propagation for a domain's authorization record."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        from dmarc_msp.cli.helpers import get_dns_provider
        from dmarc_msp.services.dns import DNSService

        dns_svc = DNSService(get_dns_provider(settings), settings)
        verified = dns_svc.verify_authorization_record(domain)
        if verified:
            console.print(f"[green]✓[/green] DNS record verified for {domain}")
        else:
            console.print(f"[yellow]✗[/yellow] DNS record not found for {domain}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("list")
def list_domains(
    client: Optional[str] = typer.Option(None, "--client", help="Filter by client"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """List monitored domains."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        query = db.query(DomainRow)
        if client:
            client_svc = ClientService(db)
            client_row = client_svc.get(client)
            query = query.filter(DomainRow.client_id == client_row.id)

        domains = query.order_by(DomainRow.domain_name).all()
        if not domains:
            console.print("No domains found.")
            return

        table = Table(title="Domains")
        table.add_column("Domain")
        table.add_column("Client")
        table.add_column("Status")
        table.add_column("DNS")
        for d in domains:
            table.add_row(
                d.domain_name,
                d.client.name if d.client else "—",
                d.status,
                "✓" if d.dns_verified else "—",
            )
        console.print(table)
    finally:
        db.close()


@app.command("bulk-add")
def bulk_add(
    client: str = typer.Option(..., "--client"),
    file: str = typer.Option(..., "--file", help="File with one domain per line"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Bulk-add domains from a file."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        result = svc.bulk_import(file, client, operation="add")
        console.print(
            f"Bulk add: {len(result.succeeded)} succeeded, "
            f"{len(result.skipped)} skipped, {len(result.failed)} failed"
        )
        for domain, err in result.failed:
            console.print(f"  [red]✗[/red] {domain}: {err}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("bulk-remove")
def bulk_remove(
    file: str = typer.Option(..., "--file"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Bulk-remove domains from a file."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        result = svc.bulk_import(file, "", operation="remove")
        console.print(
            f"Bulk remove: {len(result.succeeded)} succeeded, "
            f"{len(result.failed)} failed"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("bulk-move")
def bulk_move(
    to: str = typer.Option(..., "--to"),
    file: str = typer.Option(..., "--file"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Bulk-move domains from a file to a different client."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        svc = get_onboarding_service(settings, db)
        result = svc.bulk_import(file, to, operation="move")
        console.print(
            f"Bulk move: {len(result.succeeded)} succeeded, "
            f"{len(result.skipped)} skipped, {len(result.failed)} failed"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
