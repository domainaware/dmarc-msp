"""One-shot data-migration CLI commands.

These repair existing OpenSearch documents and Dashboards saved objects
that drifted when parsedmarc renamed ASN fields and improved its IP-based
enrichment (GeoIP swap to ipinfo, better source-name/type classification).
All commands are idempotent and safe to re-run.
"""

from __future__ import annotations

import typer
from rich.console import Console

from dmarc_msp.cli.helpers import get_db_session, get_settings
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.migrate import (
    DEFAULT_ENRICHMENT_FIELDS,
    DMARC_INDEX_PATTERN,
    FIELD_TO_PARSEDMARC_KEY,
    MigrationService,
)

app = typer.Typer(
    help="Data-migration commands for existing indices.", no_args_is_help=True
)
console = Console()

_DEFAULT_FIELDS_CSV = ",".join(DEFAULT_ENRICHMENT_FIELDS)


def _parse_fields(raw: str) -> list[str]:
    items = [f.strip() for f in raw.split(",") if f.strip()]
    unknown = [f for f in items if f not in FIELD_TO_PARSEDMARC_KEY]
    if unknown:
        supported = ", ".join(sorted(FIELD_TO_PARSEDMARC_KEY))
        raise typer.BadParameter(f"Unknown field(s): {unknown}. Supported: {supported}")
    return items


def _refresh_tenant_index_patterns(settings, clients, indent: str = "  ") -> int:
    """Rebuild each tenant's cached index-pattern field list. Returns the
    number of tenants that failed."""
    dash_svc = DashboardService(settings.dashboards, settings.opensearch)
    failed = 0
    for c in clients:
        try:
            n = dash_svc.refresh_index_pattern_fields(c.tenant_name)
            console.print(
                f"{indent}[green]✓[/green] {c.name} (tenant={c.tenant_name}) "
                f"— refreshed {n} index-pattern(s)"
            )
        except Exception as e:
            failed += 1
            console.print(f"{indent}[red]✗[/red] {c.name}: {e}")
    return failed


@app.command("rename-asn-fields")
def rename_asn_fields(
    index_pattern: str = typer.Option(
        DMARC_INDEX_PATTERN,
        "--index-pattern",
        help="Comma-separated OpenSearch index pattern to target.",
    ),
    skip_refresh: bool = typer.Option(
        False,
        "--skip-refresh",
        help="Don't refresh Dashboards index-pattern field caches afterward.",
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Rename ``source_asn_{name,domain}`` → ``source_as_{name,domain}``
    in existing documents, then refresh each tenant's cached index-pattern
    fields so Discover picks up the new field names."""
    settings = get_settings(config)
    svc = MigrationService(settings.opensearch, settings.parsedmarc.container)
    console.print(f"Running ASN rename on [bold]{index_pattern}[/bold]…")
    result = svc.rename_asn_fields(index_pattern=index_pattern)
    console.print(
        f"  scanned: {result.total}  updated: [green]{result.updated}[/green]  "
        f"failures: {result.failures}"
    )
    refresh_failed = 0
    if not skip_refresh:
        db = get_db_session(settings)
        try:
            clients = ClientService(db).list(include_offboarded=False)
            if clients:
                console.print("Refreshing index-pattern fields per tenant…")
                refresh_failed = _refresh_tenant_index_patterns(settings, clients)
        finally:
            db.close()
    if result.failures or refresh_failed:
        raise typer.Exit(1)


@app.command("refresh-index-fields")
def refresh_index_fields(
    client: str | None = typer.Option(
        None, "--client", help="Refresh fields for a single client (default: all)."
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Rebuild each tenant's cached index-pattern field list from the live
    mapping. Run this after a parsedmarc upgrade that adds or renames fields."""
    settings = get_settings(config)
    db = get_db_session(settings)
    try:
        client_svc = ClientService(db)
        if client:
            clients = [client_svc.get(client)]
        else:
            clients = client_svc.list(include_offboarded=False)
        if not clients:
            console.print("No active clients found.")
            return
        failed = _refresh_tenant_index_patterns(settings, clients)
        console.print(f"\nRefreshed {len(clients) - failed}/{len(clients)} tenants.")
        if failed:
            raise typer.Exit(1)
    finally:
        db.close()


@app.command("refill-enrichment")
def refill_enrichment(
    fields: str = typer.Option(
        _DEFAULT_FIELDS_CSV,
        "--fields",
        help=(
            "Comma-separated doc fields to re-enrich. Supported: "
            + ", ".join(sorted(FIELD_TO_PARSEDMARC_KEY))
        ),
    ),
    index_pattern: str = typer.Option(
        DMARC_INDEX_PATTERN,
        "--index-pattern",
        help="Comma-separated OpenSearch index pattern to target.",
    ),
    lookup_batch: int = typer.Option(
        500, "--lookup-batch", help="IPs sent per parsedmarc lookup call."
    ),
    update_batch: int = typer.Option(
        500, "--update-batch", help="IPs grouped per _update_by_query call."
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Re-derive IP-based enrichment fields (country, source_name,
    source_type) on existing docs by calling parsedmarc's own helper inside
    the parsedmarc container, so historical data matches what new docs get."""
    field_list = _parse_fields(fields)
    settings = get_settings(config)
    svc = MigrationService(settings.opensearch, settings.parsedmarc.container)
    console.print(
        f"Re-enriching {field_list} on [bold]{index_pattern}[/bold] "
        f"via container [bold]{settings.parsedmarc.container}[/bold]…"
    )
    result = svc.refill_enrichment_fields(
        index_pattern=index_pattern,
        fields=field_list,
        lookup_batch=lookup_batch,
        update_batch=update_batch,
    )
    console.print(
        f"  unique IPs: {result.unique_ips}  resolved: {result.resolved_ips}  "
        f"docs updated: [green]{result.updated_docs}[/green]"
    )


@app.command("all")
def run_all(
    fields: str = typer.Option(
        _DEFAULT_FIELDS_CSV,
        "--fields",
        help="Enrichment fields to re-derive in step 2.",
    ),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """Run all three migrations in order: rename ASN fields, re-derive
    IP-based enrichment, refresh index-pattern fields."""
    field_list = _parse_fields(fields)
    settings = get_settings(config)

    svc = MigrationService(settings.opensearch, settings.parsedmarc.container)
    console.print("[bold]1/3[/bold] Renaming ASN fields…")
    r1 = svc.rename_asn_fields()
    console.print(
        f"    scanned: {r1.total}  updated: [green]{r1.updated}[/green]  "
        f"failures: {r1.failures}"
    )

    console.print(f"[bold]2/3[/bold] Re-deriving enrichment ({field_list})…")
    r2 = svc.refill_enrichment_fields(fields=field_list)
    console.print(
        f"    unique IPs: {r2.unique_ips}  resolved: {r2.resolved_ips}  "
        f"docs updated: [green]{r2.updated_docs}[/green]"
    )

    console.print("[bold]3/3[/bold] Refreshing index-pattern fields per tenant…")
    db = get_db_session(settings)
    try:
        clients = ClientService(db).list(include_offboarded=False)
        failed = _refresh_tenant_index_patterns(settings, clients, indent="    ")
    finally:
        db.close()

    if r1.failures or failed:
        raise typer.Exit(1)
