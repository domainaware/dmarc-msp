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
- **DB before external state** — `add_domain` commits the domain reservation to the database before creating DNS records or modifying the parsedmarc YAML. This prevents concurrent operations (e.g., `cleanup-dns`) from seeing orphaned external state.
- **YAML rollback on failure** — every orchestrator that mutates the parsedmarc YAML (`add_domain`, `remove_domain`, `move_domain`, `offboard_client`) restores the YAML to its prior state if the DB commit or a later step fails.

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
│   ├── retention.py    # ISM policy management + email cleanup
│   ├── onboarding.py   # Orchestrator: add/remove/move domains
│   └── offboarding.py  # Orchestrator: full client teardown
├── dns_providers/      # Pluggable DNS backends
│   ├── base.py         # Abstract DNSProvider + DNSRecord (get/create/delete/list)
│   ├── cloudflare.py   # Cloudflare (default, included in base deps)
│   ├── route53.py      # AWS Route 53 (optional extra)
│   ├── gcp.py          # Google Cloud DNS (optional extra)
│   └── azure.py        # Azure DNS (optional extra)
├── process/
│   └── docker.py       # Send SIGHUP to parsedmarc container
├── cli/                # Typer CLI (dmarcmsp)
│   ├── helpers.py      # Dependency wiring for CLI commands
│   ├── client.py       # client create/list/show/update/rename/offboard
│   ├── domain.py       # domain add/remove/move/verify/list/cleanup-dns/bulk-*
│   ├── tenant.py       # tenant provision/deprovision
│   ├── dashboard.py    # dashboard import / import-all
│   ├── retention.py    # retention cleanup-emails/ensure-default-policy
│   ├── parsedmarc.py   # parsedmarc reload
│   └── server.py       # serve command (API server)
└── api/                # FastAPI management API
    ├── dependencies.py # DI (settings, db session, services)
    ├── middleware.py    # IP allowlist
    ├── schemas.py      # Request/response models
    └── routers/        # One router per resource

deploy/
├── postfix/            # Custom receive-only Postfix container
│   ├── Dockerfile      # Alpine + Postfix
│   ├── main.cf.template # Receive-only config (envsubst'd)
│   ├── master.cf       # Port 25 + 587 listeners
│   └── entrypoint.sh   # TLS detection, envsubst, Maildir setup
├── nginx/              # TLS-terminating reverse proxy
│   ├── Dockerfile      # nginx:alpine
│   ├── nginx.conf.template              # Full HTTPS config
│   ├── nginx-http-only.conf.template    # Bootstrap config (no certs yet)
│   ├── mta-sts.conf.template            # MTA-STS HTTPS server block
│   ├── mta-sts-http-only.conf.template  # MTA-STS bootstrap (ACME only)
│   └── entrypoint.sh   # Cert detection, MTA-STS DNS check, auto-reload
├── certbot/            # Let's Encrypt config
│   ├── cli.ini         # Certbot defaults (webroot, agree-tos)
│   └── entrypoint.sh   # Cert requests (main + conditional MTA-STS), renewal loop
├── opensearch/         # OpenSearch node config
│   └── opensearch.yml
└── dashboards/         # Dashboards config
    └── opensearch_dashboards.yml
```

## Docker Services

| Service | Image | Purpose |
| --- | -- |- -- |
| `postfix` | Custom (Alpine + Postfix) | Receive-only SMTP for DMARC reports |
| `parsedmarc` | `ghcr.io/domainaware/parsedmarc:latest` | Report processing |
| `opensearch` | `opensearchproject/opensearch:3` | Data storage (backend only) |
| `opensearch-dashboards` | `opensearchproject/opensearch-dashboards:3` | Visualization (internal, behind nginx) |
| `nginx` | Custom (nginx:alpine) | TLS termination, reverse proxy, rate limiting |
| `certbot` | `certbot/certbot` | Let's Encrypt HTTP-01 certificate management |
| `dmarc-msp` | Custom (python:3.13-alpine) | Management CLI + API server |

### Network Layout

- **`frontend`** — services needing external connectivity. nginx, Postfix, certbot, parsedmarc, Dashboards, dmarc-msp.
- **`backend`** (`internal: true`) — no internet access. OpenSearch lives here exclusively. Dashboards, parsedmarc, and dmarc-msp bridge both networks.

### TLS Bootstrap Flow

1. nginx starts HTTP-only (no certs yet), serves ACME challenges on port 80
2. certbot obtains cert via HTTP-01, writes to shared `certs` volume
3. nginx's background poller detects the cert, swaps in HTTPS config, runs `nginx -s reload`
4. Postfix waits for certbot healthcheck (cert exists) before starting

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
- **Client create provisions OpenSearch** — the CLI and API both create the tenant, role, and import dashboards when creating a client.
- **Client rename** — changes display name only. `index_prefix` and `tenant_name` are immutable after creation.
- **parsedmarc is a separate project** — parsedmarc has its own config format, CLI flags, and environment variables (`PARSEDMARC_*`). Do not confuse parsedmarc's config keys (e.g., `user`, `hosts`) with this project's config classes (e.g., `OpenSearchConfig.username`, `OpenSearchConfig.hosts`). When configuring parsedmarc env vars in `docker-compose.yml`, always refer to parsedmarc's own documentation at https://domainaware.github.io/parsedmarc/usage.html, not this project's code.
- **Secrets** — most go in `.env` as env vars. GCP is the only provider using a Docker secret file. Never put secrets in config YAML or docker-compose.yml.
- **Postfix** — custom receive-only container (not a relay image). Accepts mail for one address only, delivers to Maildir. Postfix uses `home_mailbox = Maildir/` which appends to the dmarc user's home (`/var/mail/dmarc`), so mail lands in `/var/mail/dmarc/Maildir/`. parsedmarc and the retention CLI must point to that path, not the parent directory. The `maildir` named volume is shared between Postfix, parsedmarc, and dmarc-msp; Postfix's entrypoint ensures correct ownership (UID 1000).
- **nginx** — reverse proxy in front of Dashboards. Dashboards serves plain HTTP internally on port 5601; nginx terminates TLS.
- **Email cleanup** — handled by the dmarc-msp container's background loop (runs daily), configured via `retention.email_days` in the YAML config. No separate cron container.
- **OpenSearch string fields — always query `.keyword` for aggregations and terms filters.** parsedmarc's dynamic mapping stores every string field as `text` with a `.keyword` subfield. Composite aggregation sources, `terms` filters, and sorts on the bare text field fail with `search_phase_execution_exception: Text fields are not optimised for operations that require per-document field data…`. Use `<field>.keyword`. `exists` queries work on the base field and don't need the subfield.
- **OSD index-pattern field cache — refresh after any field-schema change.** Dashboards index-pattern saved objects cache `attributes.fields` at import time and never auto-refresh. Any operation that adds or renames fields on existing indices (parsedmarc upgrades, `migrate rename-asn-fields`, custom mapping changes) must call `DashboardService.refresh_index_pattern_fields(tenant_name)` per active tenant, or Discover shows "no cached mapping" warnings on the new/renamed fields. `migrate rename-asn-fields` and `migrate all` do this automatically via the `_refresh_tenant_index_patterns` helper in `cli/migrate.py`.
- **Don't use broad `except Exception` to make external calls "safe".** If the only thing a block does is call one external function, `except Exception` inside it almost certainly masks programming errors (bad kwargs, `ImportError`, `AttributeError`) as silent no-ops. `migrate refill-enrichment` silently produced zero updates for an entire release because a per-IP `try/except Exception` in the parsedmarc lookup script turned `TypeError: unexpected keyword argument 'parallel'` into `{ip: None}`. Only catch exceptions you have an expected recovery path for (e.g., `json.JSONDecodeError` when parsing untrusted input). Let the rest propagate so the traceback surfaces on the first failure.
- **Verify external library signatures before calling.** The `parallel=False` bug was a hallucinated kwarg — no such parameter exists on `parsedmarc.utils.get_ip_address_info`. When writing code that calls into parsedmarc or another library, confirm the function signature against the installed version (`python3 -c "import inspect, parsedmarc.utils; print(inspect.signature(parsedmarc.utils.get_ip_address_info))"`) rather than relying on memory or similar-looking code elsewhere.

## Concurrency Model

The system is designed for safe concurrent operation across CLI invocations, API requests, and background tasks.

### Parsedmarc YAML file lock

All mutations to the domain map YAML (`add_domain_mapping`, `remove_domain_mapping`, `move_domain_mapping`) are serialized with an exclusive file lock (`flock`) at `<domain_map_file>.lock`. This prevents concurrent domain operations from racing on the read-modify-write cycle. The lock is advisory (POSIX `flock`), blocking, and automatically released when the file descriptor closes (including process crash).

### Domain reservation (DB-first commit)

`add_domain` commits the domain row to SQLite (status `pending_dns`) **before** creating the DNS record. This ensures the domain is visible to other sessions (e.g., a concurrent `cleanup-dns`) before its external state exists. If a later step fails, the rollback handler:

- Deletes the domain row (new domains) or restores `offboarded` status (re-added domains)
- Deletes the DNS record if one was created
- Removes the parsedmarc YAML mapping if one was written
- Deletes an auto-created client if `create_client=True` was used

### YAML rollback

Every orchestrator method that mutates the parsedmarc YAML tracks whether the mutation succeeded and reverses it in the exception handler if the DB commit fails:

- `add_domain` → calls `remove_domain_mapping` on rollback
- `remove_domain` → calls `add_domain_mapping` on rollback
- `move_domain` → calls `move_domain_mapping` (reversed direction) on rollback
- `offboard_client` → calls `add_domain_mapping` for each removed domain on rollback

### What is NOT protected

- **OpenSearch API calls** (tenant provisioning, role mapping, user management) are not transactional. OpenSearch has no transaction support. These operations are idempotent (PUT-based) so concurrent calls produce correct results, but multi-step operations (e.g., create user + add to role mapping) can leave partial state on failure.
- **SQLite row-level locking** is not used. Duplicate protection relies on UNIQUE constraints, which produce clean `IntegrityError` exceptions rather than silent corruption.

## Running Tests

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

## Diagrams

When creating ASCII/Unicode box-drawing diagrams, never hand-draw them. Instead, write a Python script that generates the diagram programmatically and asserts every line is the same character width before outputting. Use helper functions for box creation, side-by-side layout, and nesting. Verify the output renders correctly before presenting.

## Common Tasks

### Adding a new DNS provider

1. Create `dmarc_msp/dns_providers/<provider>.py` implementing `DNSProvider` (must implement `create_txt_record`, `delete_txt_record`, `get_txt_records`, and `list_txt_records`).
2. Add the provider option to `cli/helpers.py:get_dns_provider()`.
3. Add optional dependency to `pyproject.toml` under `[project.optional-dependencies]`.
4. Add env vars to `docker-compose.yml` (commented out) and `.env.example`.
5. Add the provider to the dropdown in `.github/ISSUE_TEMPLATE/bug_report.yml`.
6. Document in README.md under "DNS Providers" and in `dmarc-msp.example.yml`.

### Adding a new CLI command

1. Add the command function in the appropriate `cli/*.py` module.
2. Wire dependencies using helpers from `cli/helpers.py`.
3. Follow the pattern: get settings → get db session → call service → print result → close db in `finally`.
4. Register the subcommand in `cli/__init__.py` if it's a new group.

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

- `.env` — Docker Compose env vars (contains passwords and API tokens)
- `secrets/` — Docker secret files (GCP key)
- `parsedmarc.ini` — legacy config (no longer required; parsedmarc uses env vars in docker-compose.yml)
- `dmarc-msp.yml` — local config (use `dmarc-msp.example.yml` as template)
- `domain_map.yaml` — auto-managed by the service layer
- `*.db` — SQLite database
