# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-23

### Added

- **Client management** — create, list, show, update, rename, and offboard clients with isolated OpenSearch tenants, roles, and index prefixes.
- **Domain management** — add, remove, move, and verify domains across clients. Bulk operations via text file (bulk-add, bulk-remove, bulk-move).
- **DNS authorization** — automatic RFC 7489 DMARC authorization TXT record creation and deletion on the MSP's domain.
- **Pluggable DNS providers** — Cloudflare (built-in), AWS Route 53, Google Cloud DNS, and Azure DNS via optional extras.
- **OpenSearch multi-tenancy** — per-client tenant, role, and role mapping provisioning. Clients see only their own data.
- **Dashboard provisioning** — automatic rewrite and import of parsedmarc's bundled OpenSearch Dashboards saved objects into per-client tenants.
- **Index retention** — ISM policy management with a global default (180 days) and per-client overrides.
- **Email retention** — cron-based cleanup of processed DMARC report emails from Maildir.
- **parsedmarc integration** — YAML domain-to-index-prefix mapping management with atomic moves and SIGHUP-based config reload via Docker.
- **Typer CLI** (`dmarcmsp`) — full command suite for client, domain, tenant, dashboard, and parsedmarc management.
- **FastAPI management API** — REST API mirroring CLI functionality, with IP allowlist middleware. Swagger UI at `/docs`.
- **Audit trail** — every action logged with timestamps, client context, and outcome.
- **Docker Compose stack** — single `docker compose up` deployment: Postfix (SMTP), parsedmarc, OpenSearch, Dashboards, certbot (TLS), cron, and the management tool.
- **Network isolation** — two-network architecture separating public-facing services (frontend) from internal infrastructure (backend, `internal: true`).
- **Secrets management** — `.env` + Docker Compose secrets, with automatic resolution from env vars, secret files, or config YAML.
- **Idempotent operations** — all onboarding and provisioning commands are safe to re-run.
