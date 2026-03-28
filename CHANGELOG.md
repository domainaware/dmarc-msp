# Changelog

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
