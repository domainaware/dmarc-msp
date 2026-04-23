# Changelog

## 0.6.2 2026-04-23

### Fixed

- `dmarcmsp migrate refill-enrichment` (and `migrate all`) no longer fails
  with a `fielddata` error. The composite aggregation that collects unique
  source IPs and the terms filter that targets docs for the patch step
  both now use `source_ip_address.keyword` instead of the text field.
- `dmarcmsp migrate rename-asn-fields` now refreshes each tenant's cached
  index-pattern field list after the rename, so Discover stops warning that
  `source_as_name` / `source_as_domain` have no cached mapping. Pass
  `--skip-refresh` to opt out.
- `dmarcmsp migrate refill-enrichment` silently produced zero updates on
  every run. The in-container lookup helper passed `parallel=False` to
  `parsedmarc.utils.get_ip_address_info`, which has no such kwarg, so every
  IP raised `TypeError`. A broad `except Exception` inside the lookup
  script masked the error as `{ip: None}`, which then fell through as a
  no-op patch. Removed the bad kwarg and dropped the per-IP try/except so
  programming errors surface as a non-zero subprocess exit — the existing
  `CalledProcessError` handler then raises with the real traceback.
  Lookup-helper stderr is also logged at warning level now.

## 0.6.1 2026-04-23

### Added

- `dmarcmsp migrate` CLI group with one-shot data-repair commands for
  existing OpenSearch indices after a parsedmarc upgrade:
  - `migrate rename-asn-fields` renames `source_asn_{name,domain}` to
    `source_as_{name,domain}` on historical docs.
  - `migrate refill-enrichment` re-derives IP-based enrichment fields
    (`source_country`, `source_name`, `source_type`, `source_as_name`,
    `source_as_domain`) by invoking `parsedmarc.utils.get_ip_address_info`
    inside the parsedmarc container, so historical data matches the
    enrichment new docs receive. Configurable via `--fields`.
  - `migrate refresh-index-fields` rebuilds each tenant's cached
    index-pattern field list from the live OpenSearch mapping, picking
    up newly added or renamed parsedmarc fields.
  - `migrate all` runs all three in order.
- `DashboardService.refresh_index_pattern_fields(tenant_name)` backing
  the per-tenant field refresh.

## 0.6.0 2026-04-17

### Changed

- Analysts and client users are no longer added to the `kibana_read_only` role mapping on creation. The role is a UI-only modifier that hid edit controls and caused UI bugs; these accounts have no write permissions through the `analyst` / client tenant roles regardless.
- Stopped writing the redundant `roles` attribute on internal users. The OpenSearch role mappings are the source of truth for access; the attribute was pure bookkeeping and introduced drift risk. `disable` and `delete` now query live role mappings to determine what to tear down. `reset-password` (for a disabled user) derives the roles to restore from `role_type` and `client_tenant`.

### Removed

- Unused `OpenSearchService.create_role_mapping` method. `add_user_to_role_mapping` already creates mappings on demand.
- Unused `backend_roles` parameter on `create_internal_user`. The defensive passthrough in `update_internal_user_password` and `update_internal_user_attributes` is retained so admin-set backend roles survive our updates.

### Migration note

Existing analyst and client users keep whatever role mappings they were originally added to — including `kibana_read_only`. This change only affects newly created users. Existing users' stale `attributes.roles` field is also left in place (harmless — nothing reads it). To remove an existing user from the `kibana_read_only` mapping, disable and re-enable the account via `reset-password`; the restored role set is derived from the account type and no longer includes `kibana_read_only`.

## 0.5.0 2026-04-15

### Changed

- Disabled forensic/failure report saving in parsedmarc (`PARSEDMARC_GENERAL_SAVE_FORENSIC=false`) to avoid liability from storing email samples.
- Failure/forensic dashboard objects (index pattern, visualizations, and dashboard) are no longer imported by default. Controlled by the new `dashboards.import_failure_reports` config option (default `false`).
- `dmarcmsp dashboard import` and `import-all` now delete previously imported failure objects from existing tenants when `import_failure_reports` is `false`. Run `dmarcmsp dashboard import-all` after upgrading to clean up existing clients.
- Dashboard imports now explicitly set `defaultIndex` to the aggregate index pattern, preventing a 403 error for read-only users on first visit.
- Refactored `set_dark_mode` to use a shared `_set_tenant_settings` method.

### Added

- `dashboards.import_failure_reports` config option to control whether failure/forensic report dashboards are imported during client onboarding.

## 0.4.1 2026-04-11

### Fixed

- Parsedmarc YAML writes no longer fail with `EBUSY` on Docker bind-mounted files. The atomic rename is still attempted first, but falls back to a direct overwrite when the target is a mount point.

## 0.4.0 2026-04-06

### Added

- `dmarcmsp domain cleanup-dns` command and `POST /api/v1/domains/cleanup-dns` endpoint to remove stale DMARC authorization DNS records from the zone. Compares all authorization TXT records against the database and deletes any whose domain is not actively monitored. Defaults to dry-run mode; pass `--no-dry-run` to actually delete records.
- `list_txt_records(zone)` method on the `DNSProvider` interface, implemented for all four providers (Cloudflare, Route 53, GCP, Azure).

### Fixed

- `add_domain` now commits the domain row to the database (as `pending_dns`) before creating the DNS record. This prevents a concurrent `cleanup-dns` from deleting a record that is mid-onboarding. On failure, the reservation is fully reverted.
- `add_domain` now cleans up the parsedmarc YAML mapping on rollback. Previously, a failure after the YAML write but before the final DB commit would leave a stale mapping in the YAML file.
- `remove_domain` now restores the parsedmarc YAML mapping if the DB commit fails after the mapping was removed.
- `move_domain` now reverses the parsedmarc YAML move if the DB commit or OpenSearch provisioning fails afterward.
- `offboard_client` now restores all parsedmarc YAML mappings if the DB commit fails after domain mappings were removed.
- Parsedmarc YAML read-modify-write operations are now serialized with a file lock. Previously, concurrent domain operations (add, remove, move) could race on the YAML file, silently losing mappings.
- Cloudflare provider now iterates paginated responses directly instead of accessing `.result` (first page only). Previously, `get_txt_records`, `delete_txt_record`, and zone-wide listing could silently truncate results in large zones.
- Route 53 `delete_txt_record` now sends the complete record set in the DELETE call. Previously, it sent per-value DELETEs that would fail when a record set contained multiple TXT values.

## 0.3.0 2026-04-06

### Fixed

- Client offboarding no longer aborts on a single DNS deletion failure. DNS cleanup is now best-effort per domain — failures are collected, logged, recorded in the audit log, and surfaced via CLI warnings and the API response. The DB transaction always commits so that DNS and DB state stay consistent.
- `add_domain` now cleans up the DNS authorization record it created when a later step fails (parsedmarc write, reload, OpenSearch provisioning, or dashboard import). Previously, a rollback would leave an orphaned DNS record in the provider.
- Pre-existing authorization records (e.g. left by a previous DMARC solution) no longer cause onboarding failures. `create_authorization_record` now re-checks after a provider conflict and treats a confirmed existing record as success.
- `ParsedmarcService.reload()` now raises `ParsedmarcReloadError` on failure instead of returning `False`. During onboarding, this triggers a full rollback (including DNS cleanup) so domains are not committed if parsedmarc cannot reload. During offboarding, the error is caught and logged as a warning — the YAML is already updated and parsedmarc will pick up changes on next restart.
- The parsedmarc YAML domain map is now written atomically (temp file + `os.rename`). A crash mid-write can no longer leave a truncated file that breaks parsedmarc.

### Added

- `OffboardingResult.dns_failures` field reports which domains had DNS cleanup failures during offboarding.
- `ParsedmarcReloadError` exception for explicit reload failure handling.
- Stress tests for bulk onboarding/offboarding at MSP scale (28 tests covering 20+ domain batches, multi-client churn, interleaved operations, pre-existing DNS records, and DNS/DB consistency).

## 0.2.10 2026-04-05

### Changed

- Change OpenSearch default `applicationTitle` for this project to `DMARC analytics`

## 0.2.9 2026-04-05

### Fixed

- Fixed colors in the Message disposition over time visualization.

## 0.2.8 2026-04-05

### Changed

- Removed redundant cluster permissions (`cluster:admin/opensearch/ql/datasources/read`, `cluster_composite_ops_ro`) from analyst and client roles.
- Added `uiSettings.overrides.defaultRoute: /app/dashboards` to `opensearch_dashboards.yml` and an nginx redirect from `/app/home` to `/app/dashboards` to prevent users from landing on pages they cannot access.
- Modernized nginx TLS configuration.
- nginx DNS resolver is now configurable via the `DNS_RESOLVER` environment variable (defaults to `127.0.0.11`, Docker's embedded DNS).

## 0.2.7 2026-04-03

### Fixed

- Analyst and client roles now include cluster permissions (`cluster:admin/opensearch/ql/datasources/read`, `cluster_composite_ops_ro`) required for Dashboards queries.
- Fixed forensic index pattern from `*_dmarc_forensic*` to `*_dmarc_fo*` to match the actual index names created by parsedmarc.
- Client role index patterns are now explicit per-index-type (`{prefix}_dmarc_aggregate*`, `{prefix}_dmarc_fo*`, `{prefix}_smtp_tls*`) instead of a broad `{prefix}_*` wildcard.
- Simplified index permissions to the `read` action group instead of listing individual actions.

## 0.2.6 2026-04-01

### Fixed

- Analyst and client user accounts are now assigned the `kibana_user` role, fixing "Application Not Found" on the Dashboards overview page. `kibana_read_only` alone is a UI modifier that hides edit controls — `kibana_user` provides the actual cluster and index permissions needed to use Dashboards.
- Reverted the Global tenant permission added in 0.2.3, as it was not the actual cause.

## 0.2.5 2026-04-01

### Fixed

- Creating an analyst or client user account with an existing username no longer silently resets the password. It now returns an error instead.

## 0.2.4 2026-04-01

### Changed

- Password display message now prompts admins to ask users to change their password at first login.

## 0.2.3 2026-04-01

### Fixed

- Analyst and client user roles now include read access to the Global tenant, fixing "Application Not Found" on the Dashboards overview page after login.

## 0.2.2 2026-04-01

### Fixed

- `docker kill` hook used by `certbot` after successful certificate renewals now correctly uses the service name, not the container name.

## 0.2.1 2026-03-31

### Added

- **Separate bind IPs for nginx and Postfix** — new `HTTP_BIND_IP` and
  `SMTP_BIND_IP` environment variables allow nginx and Postfix to listen on
  different IP addresses. This lets you put the web interface behind Cloudflare
  while SMTP uses an IP with matching forward/reverse DNS for deliverability.
- **Docker Compose override example** — new `docker-compose.override.example.yml`
  showing how to add extra nginx server blocks for other websites on the same
  host.

### Fixed

- Resolved 6 ruff E501 (line too long) lint errors across API routers, CLI, and
  services.

## 0.2.0 2026-03-30

### Added

- **Analyst accounts** — new `analyst create/delete/disable/reset-password/list`
  CLI commands and `/api/v1/analysts` API endpoints for managing read-only
  analyst users with wildcard access to all client tenants.
- **Client user accounts** — new `client user create/delete/disable/reset-password/list`
  CLI commands and `/api/v1/clients/{name}/users` API endpoints for managing
  per-client users scoped to a single tenant.
- **OpenSearch internal user management** — `OpenSearchService` now supports
  creating, deleting, disabling, and password-resetting internal users, plus
  role mapping add/remove helpers.
- **Analyst role provisioning** — `ensure_analyst_role()` creates a wildcard
  role granting read access to all `client_*` tenants.
- **Tenant prefix migration** — new `tenant migrate-prefix` CLI command to
  rename existing tenants to use the `client_` prefix required for
  wildcard-based analyst access. Supports `--dry-run`.

### Changed

- Tenant names now use a `client_` prefix (e.g., `client_acme_corp` instead of
  `acme_corp`) to enable wildcard role patterns for analyst access.
- Role names now match the tenant name directly instead of using a
  `client_` prefix on the slug (role naming is unchanged in practice, but the
  derivation is now consistent with the tenant name).
- Deletion methods in `OpenSearchService` now catch `NotFoundError` instead of
  bare `Exception` for more precise error handling.

## 0.1.1 2026-03-27

### Fixed

- Made test assertion more specific in `test_config_validate_success` to resolve
  CodeQL "incomplete URL substring sanitization" code scanning alert.
- Mounted `opensearch_dashboards.yml` config into the opensearch-dashboards
  container in `docker-compose.yml`.

## 0.1.0 2026-03-27

First public beta release.

### Highlights

dmarc-msp automates DMARC monitoring across multiple client domains for
Managed Service Providers. A single email address receives all DMARC reports;
parsedmarc routes them to per-client OpenSearch indices via a YAML domain map
that dmarc-msp manages automatically.

### Core Features

- **Client lifecycle** — create, list, show, update, rename, and offboard
  clients. Each client gets an isolated OpenSearch tenant, role, role mapping,
  and pre-configured dashboards.
- **Domain management** — add, remove, move, and verify domains with automatic
  DNS authorization record provisioning (RFC 7489 `_dmarc` TXT records).
- **Bulk operations** — `bulk-add`, `bulk-remove`, and `bulk-verify` commands
  for managing many domains at once.
- **Pluggable DNS providers** — Cloudflare (included), AWS Route 53, Google
  Cloud DNS, and Azure DNS (optional extras).
- **OpenSearch multi-tenancy** — automatic tenant, role, and role-mapping
  provisioning per client.
- **Dashboard provisioning** — NDJSON template rewriting to scope Dashboards
  saved objects to each client's index prefix. Supports `import` and
  `import-all` for bulk re-import.
- **Retention management** — ISM policy-based index retention with a
  configurable global default and per-client overrides. Automated email cleanup
  removes processed report files from Maildir on a daily schedule.
- **Onboarding orchestration** — single command adds a domain, creates DNS
  records, updates the parsedmarc domain map, and reloads parsedmarc.
  Rolls back on failure.
- **Offboarding orchestration** — full client teardown: removes domains, DNS
  records, OpenSearch tenant/role/role-mapping, and marks the client offboarded.
- **Audit logging** — every operation is recorded in a SQLite audit log.
- **Configuration** — Pydantic Settings with YAML config file, environment
  variables, and Docker secrets support.

### Deployment Stack

- **Docker Compose** deployment with seven services: Postfix (receive-only
  SMTP), parsedmarc, OpenSearch 3, OpenSearch Dashboards 3, nginx (TLS
  termination), certbot (Let's Encrypt HTTP-01), and the dmarc-msp management
  container.
- **Automated TLS bootstrap** — nginx starts HTTP-only, certbot obtains
  certificates, nginx hot-reloads to HTTPS. Postfix waits for certs before
  starting.
- **MTA-STS support** — optional MTA-STS policy hosting via nginx.
- **Network isolation** — OpenSearch on an internal-only Docker network;
  external access only through nginx.
- **Branding support** — custom login page assets for OpenSearch Dashboards.

### Management API

- Optional FastAPI server with endpoints for clients, domains, tenants,
  dashboards, and parsedmarc reload.
- IP allowlist middleware for access control.
- Localhost-only binding by default.

### Developer Experience

- 177 tests with in-memory SQLite (no mocks for DB).
- CI via GitHub Actions.
- Shell completion support for the `dmarcmsp` CLI.
