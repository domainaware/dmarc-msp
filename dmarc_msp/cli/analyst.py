"""Analyst account management CLI commands."""

from __future__ import annotations

import json
import secrets

import typer
from opensearchpy import TransportError
from rich.console import Console
from rich.table import Table

from dmarc_msp.cli.helpers import get_opensearch_service, get_settings
from dmarc_msp.services.opensearch import (
    OpenSearchService,
    UserAlreadyExistsError,
    UserNotFoundError,
)

app = typer.Typer(help="Analyst account management.", no_args_is_help=True)
console = Console()

KIBANA_READ_ONLY = "kibana_read_only"


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
    username: str = typer.Argument(..., help="Username for the analyst account"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Create an analyst account with read-only access to all client tenants."""
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        os_svc.health()
    except Exception as e:
        console.print(f"[red]Error:[/red] Cannot connect to OpenSearch: {e}")
        raise typer.Exit(1)

    roles = [OpenSearchService.ANALYST_ROLE, KIBANA_READ_ONLY]
    password = _generate_password()

    try:
        os_svc.ensure_analyst_role()
        os_svc.create_internal_user(
            username=username,
            password=password,
            backend_roles=[],
            attributes={
                "role_type": "analyst",
                "roles": json.dumps(roles),
                "disabled": "false",
            },
            description="Analyst account — read-only access to all client tenants",
        )
        for role in roles:
            os_svc.add_user_to_role_mapping(role, username)

        console.print("[green]Created analyst account:[/green]")
        _print_credentials(username, password)
    except Exception as e:
        _fail(e)


@app.command("reset-password")
def reset_password(
    username: str = typer.Argument(..., help="Username"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Reset an analyst's password.

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
                f"[green]Re-enabled analyst '{username}'.[/green] "
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
    """Disable an analyst account.

    Changes the password to an unknown value (prevents login) and removes
    role mappings (prevents access). To re-enable, use reset-password.
    """
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        roles = os_svc.disable_user(username)
        console.print(
            f"[green]Disabled analyst '{username}'.[/green] "
            f"Password changed and removed from roles: {', '.join(roles)}"
        )
        console.print("To re-enable, run: dmarcmsp analyst reset-password " + username)
    except Exception as e:
        _fail(e)


@app.command()
def delete(
    username: str = typer.Argument(..., help="Username"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Delete an analyst account."""
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        # Remove from role mappings before deleting
        user = os_svc.get_internal_user(username)
        attrs = user.get("attributes", {})
        roles = json.loads(attrs.get("roles", "[]"))
        for role in roles:
            os_svc.remove_user_from_role_mapping(role, username)
        os_svc.delete_internal_user(username)
        console.print(f"[green]Deleted analyst account: {username}[/green]")
    except Exception as e:
        _fail(e)


@app.command("list")
def list_analysts(
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """List all analyst accounts."""
    settings = get_settings(config)
    os_svc = get_opensearch_service(settings)

    try:
        users = os_svc.list_internal_users()
        table = Table(title="Analyst Accounts")
        table.add_column("Username")
        table.add_column("Disabled")
        table.add_column("Description")

        count = 0
        for username, data in sorted(users.items()):
            attrs = data.get("attributes", {})
            if attrs.get("role_type") != "analyst":
                continue
            disabled = attrs.get("disabled", "false")
            desc = data.get("description", "")
            table.add_row(
                username,
                "[red]yes[/red]" if disabled == "true" else "no",
                desc,
            )
            count += 1

        console.print(table)
        console.print(f"\n{count} analyst account(s)")
    except Exception as e:
        _fail(e)
