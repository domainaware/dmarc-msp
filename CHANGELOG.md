# Changelog

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
