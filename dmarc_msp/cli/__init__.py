"""Typer CLI application for dmarc-msp."""

from __future__ import annotations

import typer

from dmarc_msp.cli.client import app as client_app
from dmarc_msp.cli.dashboard import app as dashboard_app
from dmarc_msp.cli.domain import app as domain_app
from dmarc_msp.cli.parsedmarc import app as parsedmarc_app
from dmarc_msp.cli.retention import app as retention_app
from dmarc_msp.cli.server import app as server_app
from dmarc_msp.cli.tenant import app as tenant_app

app = typer.Typer(
    name="dmarcmsp",
    help="DMARC monitoring automation for Managed Service Providers.",
    no_args_is_help=True,
)

app.add_typer(client_app, name="client")
app.add_typer(domain_app, name="domain")
app.add_typer(tenant_app, name="tenant")
app.add_typer(dashboard_app, name="dashboard")
app.add_typer(parsedmarc_app, name="parsedmarc")
app.add_typer(retention_app, name="retention")
app.add_typer(server_app, name="server", hidden=True)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8000, help="Bind port"),
    config: str = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Start the FastAPI management API server."""
    import uvicorn

    from dmarc_msp.api import create_app
    from dmarc_msp.config import load_settings

    settings = load_settings(config)
    fastapi_app = create_app(settings)
    uvicorn.run(
        fastapi_app,
        host=host or settings.server.host,
        port=port or settings.server.port,
    )


@app.command()
def config_validate(
    config: str = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Validate configuration and connectivity."""
    from rich.console import Console

    from dmarc_msp.config import load_settings

    console = Console()

    try:
        settings = load_settings(config)
        console.print(f"Configuration: {config or 'auto-detected'} [green]✓[/green]")
    except Exception as e:
        console.print(f"Configuration: [red]✗[/red] {e}")
        raise typer.Exit(1)

    # Check OpenSearch password
    try:
        _ = settings.opensearch.resolved_password
        console.print("  opensearch_password: [green]✓[/green]")
    except ValueError:
        console.print("  opensearch_password: [red]✗[/red] not configured")

    console.print(f"  dns_provider: {settings.dns.provider}")
    console.print(f"  msp_domain: {settings.msp.domain}")
    console.print(f"  database: {settings.database.url}")

    # Check OpenSearch Dashboards connectivity
    console.print(f"  dashboards_url: {settings.dashboards.url}", end=" ")
    try:
        import httpx

        with httpx.Client(verify=False, timeout=5) as client:
            resp = client.get(
                f"{settings.dashboards.url}/api/status",
                auth=(
                    settings.opensearch.username,
                    settings.opensearch.resolved_password,
                ),
            )
            resp.raise_for_status()
        console.print("[green]✓[/green]")
    except Exception as e:
        console.print(f"[red]✗[/red] {e}")
