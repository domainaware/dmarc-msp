"""Client user account management CLI commands."""

from __future__ import annotations

import secrets

import typer
from opensearchpy import TransportError
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import (
    get_db_session,
    get_opensearch_service,
    get_settings,
)
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.opensearch import (
    OpenSearchService,
    UserAlreadyExistsError,
    UserNotFoundError,
)

app = typer.Typer(help="Client user account management.", no_args_is_help=True)
console = Console()


def _generate_password() -> str:
    return secrets.token_urlsafe(24)


def _fail(e: Exception) -> None:
    if isinstance(e, (UserNotFoundError, UserAlreadyExistsError)):
        console.print(f"[red]Error:[/red] {e}")
    elif isinstance(e, TransportError):
        console.print(
            f"[red]Error:[/red] OpenSearch returned {e.status_code}: {e.error}"
        )
    else:
        console.print(f"[red]Error:[/red] {e}")
    raise typer.Exit(1)


def _print_credentials(username: str, password: str) -> None:
    console.print(f"\n  Username: [bold]{username}[/bold]")
    console.print(f"  Password: [bold]{password}[/bold]\n")
    console.print(
        "[yellow]Save this password now — it will not be shown again.[/yellow]"
    )
    console.print(
        "[yellow]Please ask the user to change their password at their "
        "first login. OpenSearch Dashboards does not support forced "
        "password change on first login.[/yellow]"
    )


@app.command()
def create(
    client_name: str = typer.Argument(..., help="Client name"),
    username: str = typer.Argument(..., help="Username for the client user"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Create a user account with read-only access to a single client's tenant."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        client_row = client_svc.get(client_name)
        os_svc = get_opensearch_service(settings)

        try:
            os_svc.health()
        except Exception as e:
            console.print(f"[red]Error:[/red] Cannot connect to OpenSearch: {e}")
            raise typer.Exit(1)

        roles = [client_row.tenant_name, OpenSearchService.KIBANA_USER]
        password = _generate_password()

        os_svc.create_internal_user(
            username=username,
            password=password,
            attributes={
                "role_type": "client",
                "client_tenant": client_row.tenant_name,
                "disabled": "false",
            },
            description=f"Client user for {client_row.name}",
        )
        for role in roles:
            os_svc.add_user_to_role_mapping(role, username)

        console.print(
            f"[green]Created client user for [bold]{client_row.name}[/bold]:[/green]"
        )
        _print_credentials(username, password)
    except Exception as e:
        _fail(e)
    finally:
        db.close()


@app.command("reset-password")
def reset_password(
    username: str = typer.Argument(..., help="Username"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Reset a client user's password.

    If the account was disabled, this also restores access.
    """
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)
    password = _generate_password()

    try:
        os_svc.update_internal_user_password(username, password)
        restored = os_svc.restore_user_roles(username)
        if restored:
            console.print(
                f"[green]Re-enabled user '{username}'.[/green] "
                f"Restored roles: {', '.join(restored)}"
            )
        console.print("[green]Password reset for:[/green]")
        _print_credentials(username, password)
    except Exception as e:
        _fail(e)


@app.command()
def disable(
    username: str = typer.Argument(..., help="Username"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Disable a client user account.

    Changes the password to an unknown value (prevents login) and removes
    role mappings (prevents access). To re-enable, use reset-password.
    """
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        roles = os_svc.disable_user(username)
        console.print(
            f"[green]Disabled user '{username}'.[/green] "
            f"Password changed and removed from roles: {', '.join(roles)}"
        )
        console.print(
            "To re-enable, run: dmarcmsp client user reset-password " + username
        )
    except Exception as e:
        _fail(e)


@app.command()
def delete(
    username: str = typer.Argument(..., help="Username"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Delete a client user account."""
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        os_svc.get_internal_user(username)
        for role in os_svc.get_user_role_mappings(username):
            os_svc.remove_user_from_role_mapping(role, username)
        os_svc.delete_internal_user(username)
        console.print(f"[green]Deleted client user: {username}[/green]")
    except Exception as e:
        _fail(e)


@app.command("list")
def list_users(
    client_name: str | None = typer.Option(
        None, "--client", help="Filter by client name"
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """List client user accounts."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        os_svc = get_opensearch_service(settings)
        users = os_svc.list_internal_users()

        # Resolve client filter to tenant name if provided
        filter_tenant = None
        if client_name:
            client_svc = ClientService(db)
            client_row = client_svc.get(client_name)
            filter_tenant = client_row.tenant_name

        table = Table(title="Client User Accounts")
        table.add_column("Username")
        table.add_column("Client Tenant")
        table.add_column("Disabled")
        table.add_column("Description")

        count = 0
        for username, data in sorted(users.items()):
            attrs = data.get("attributes", {})
            if attrs.get("role_type") != "client":
                continue
            tenant = attrs.get("client_tenant", "")
            if filter_tenant and tenant != filter_tenant:
                continue
            disabled = attrs.get("disabled", "false")
            desc = data.get("description", "")
            table.add_row(
                username,
                tenant,
                "[red]yes[/red]" if disabled == "true" else "no",
                desc,
            )
            count += 1

        console.print(table)
        console.print(f"\n{count} client user account(s)")
    except Exception as e:
        _fail(e)
    finally:
        db.close()
