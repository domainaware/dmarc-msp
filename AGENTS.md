# AGENTS.md

This file provides context for AI agents working on this codebase.

## Project Overview

dmarc-msp is a Python tool and Docker-based deployment stack that automates DMARC monitoring across multiple client domains for Managed Service Providers (MSPs). It integrates with [parsedmarc](https://github.com/domainaware/parsedmarc) as the underlying report processor.

One email address receives all DMARC reports. parsedmarc routes them to per-client OpenSearch indices via a YAML domain-to-index-prefix mapping. dmarc-msp manages the lifecycle: DNS authorization records, OpenSearch multi-tenancy, dashboard provisioning, and retention policies.

## Architecture Principles

- **Service layer is king** — all business logic lives in `dmarc_msp/services/`. The CLI and API are thin wrappers.
- **CLI-first, server-optional** — the CLI calls services directly. The API server is optional.
- **Plugin-based DNS** — DNS providers implement `DNSProvider` (see `dns_providers/base.py`).
- **Idempotent operations** — onboarding the same domain twice is safe.
- **Normalize early** — all domain names and index prefixes are lowercased at the point of entry.

## Key Directories

```text
dmarc_msp/
├── config.py           # Pydantic Settings — YAML + env + Docker secrets
├── models.py           # Pydantic models (API responses, inter-service data)
├── db.py               # SQLAlchemy ORM (Client, Domain, AuditLog) + SQLite
├── services/           # Core business logic
│   ├── clients.py      # Client CRUD + rename
│   ├── dns.py          # DMARC authorization record lifecycle (RFC 7489)
│   ├── opensearch.py   # Tenant/role/role-mapping provisioning
│   ├── dashboards.py   # NDJSON rewrite + saved object import
│   ├── parsedmarc.py   # YAML domain mapping management
│   ├── retention.py    # ISM policy management
│   ├── onboarding.py   # Orchestrator: add/remove/move domains
│   └── offboarding.py  # Orchestrator: full client teardown
├── dns_providers/      # Pluggable DNS backends
│   ├── base.py         # Abstract DNSProvider + DNSRecord
│   ├── cloudflare.py   # Cloudflare (default, included in base deps)
│   ├── route53.py      # AWS Route 53 (optional extra)
│   ├── gcp.py          # Google Cloud DNS (optional extra)
│   └── azure.py        # Azure DNS (optional extra)
├── process/
│   └── docker.py       # Send SIGHUP to parsedmarc container
├── cli/                # Typer CLI (dmarcmsp)
│   ├── helpers.py      # Dependency wiring for CLI commands
│   ├── client.py       # client create/list/show/update/rename/offboard
│   ├── domain.py       # domain add/remove/move/verify/list/bulk-*
│   ├── tenant.py       # tenant provision/deprovision
│   ├── dashboard.py    # dashboard import
│   └── parsedmarc.py   # parsedmarc reload
└── api/                # FastAPI management API
    ├── dependencies.py # DI (settings, db session, services)
    ├── middleware.py    # IP allowlist
    ├── schemas.py      # Request/response models
    └── routers/        # One router per resource
```

## Data Model

Three SQLAlchemy tables in SQLite:

- **clients** — `name` (unique, lowercase), `index_prefix` (unique), `tenant_name` (unique), `status` (active/offboarded), `retention_days` (nullable, overrides global default)
- **domains** — `domain_name` (unique across ALL clients), `client_id` (FK), `status` (pending_dns/active/offboarding/offboarded), `dns_verified`
- **audit_log** — breadcrumb trail of every action

A domain can only belong to one client at a time. Offboarded domains can be re-added.

## Conventions

- **Python 3.11+** required. Type hints throughout using `X | None` syntax.
- **Pydantic v2** for models and settings.
- **SQLAlchemy 2.x** with mapped_column declarative style.
- **Testing** — pytest with in-memory SQLite (`conftest.py` provides `db_session` and `settings` fixtures). DNS providers are tested via a `FakeDNSProvider` in `tests/test_dns_providers/test_base.py`.
- **No mocks for DB** — tests use real SQLAlchemy sessions against `:memory:` SQLite.
- **Slugification** — `db.slugify()` converts client names to index prefixes (e.g., "Acme Corp" → "acme_corp").
- **Client rename** — changes display name only. `index_prefix` and `tenant_name` are immutable after creation.
- **Secrets** — never in config YAML or docker-compose.yml. Resolved at runtime from env vars → Docker secret files → config values.

## Running Tests

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

## Common Tasks

### Adding a new DNS provider

1. Create `dmarc_msp/dns_providers/<provider>.py` implementing `DNSProvider`.
2. Add the provider option to `cli/helpers.py:get_dns_provider()`.
3. Add optional dependency to `pyproject.toml` under `[project.optional-dependencies]`.
4. Add the provider to the dropdown in `.github/ISSUE_TEMPLATE/bug_report.yml`.
5. Document in README.md under "DNS Providers".

### Adding a new CLI command

1. Add the command function in the appropriate `cli/*.py` module.
2. Wire dependencies using helpers from `cli/helpers.py`.
3. Follow the pattern: get settings → get db session → call service → print result → close db in `finally`.

### Adding a new API endpoint

1. Add request/response schemas to `api/schemas.py`.
2. Add the route to the appropriate `api/routers/*.py` module.
3. Use dependency injection via `api/dependencies.py` (annotated types like `ClientServiceDep`, `DbDep`, `SettingsDep`).

### Adding a new service

1. Create `dmarc_msp/services/<service>.py`.
2. Wire it into `cli/helpers.py` for CLI access.
3. Wire it into `api/dependencies.py` for API access.

## Files That Must Not Be Committed

These are in `.gitignore` — never generate or suggest committing them:

- `.env` — Docker Compose env vars (contains passwords)
- `secrets/` — Docker secret files (API tokens)
- `parsedmarc.ini` — contains OpenSearch password
- `dmarc-msp.yaml` — local config (use `dmarc-msp.example.yaml` as template)
- `domain_map.yaml` — auto-managed by the service layer
- `*.db` — SQLite database
