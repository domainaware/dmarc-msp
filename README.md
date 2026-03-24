# DMARC for MSPs

A Python tool and Docker-based deployment stack for Managed Service Providers (MSPs) that automates DMARC monitoring across multiple client domains. It manages DNS authorization records, OpenSearch multi-tenancy provisioning, dashboard deployment, and index/email retention — integrating with [parsedmarc](https://github.com/domainaware/parsedmarc) as the underlying report processor.

The entire stack deploys via a single `docker compose up`: SMTP ingestion, parsedmarc processing, OpenSearch storage, dashboards, TLS certificates, and the management API/CLI.

> **Note:** This project is a work in progress generated with the assistance of [Claude](https://claude.ai), Anthropic's AI assistant.

## Features

- **Multi-client domain management** — onboard and offboard client domains with a single command. Each client gets isolated OpenSearch tenants, roles, and dashboards.
- **Automated DNS authorization** — creates RFC 7489 DMARC authorization TXT records on your MSP domain so report senders (Google, Microsoft, Yahoo, etc.) deliver reports to your shared mailbox.
- **Pluggable DNS providers** — ships with Cloudflare, AWS Route 53, Google Cloud DNS, and Azure DNS. Extend with your own by implementing a simple interface.
- **OpenSearch multi-tenancy** — each client gets a scoped tenant, role, and index prefix. Clients see only their own data in Dashboards.
- **Dashboard provisioning** — automatically rewrites and imports parsedmarc's bundled dashboards into each client's tenant with the correct index prefix.
- **Index retention policies** — manages ISM policies for automatic index cleanup. Supports a global default and per-client overrides (e.g., 2 years for healthcare clients).
- **Bulk operations** — import, remove, or move domains in bulk from a text file.
- **Domain moves** — move a domain between clients without touching DNS. Only the YAML mapping and database are updated.
- **CLI-first, server-optional** — the CLI calls the service layer directly by default. Optionally run as a FastAPI management API.
- **Idempotent operations** — running the same onboarding command twice is safe.
- **Audit trail** — every action is logged in an audit table with timestamps and details.
- **Full Docker Compose stack** — Postfix (SMTP), parsedmarc, OpenSearch, Dashboards, certbot (TLS), cron (email cleanup), and the management tool.

## Quick Start

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| vCPUs    | 2       | 4+          |
| RAM      | 4 GB    | 8 GB+       |
| Storage  | 20 GB   | 50–100 GB+  |

- **RAM** is primarily driven by OpenSearch. The default JVM heap is 1 GB, but production workloads with many clients benefit from 2–4 GB heap (adjust `OPENSEARCH_JAVA_OPTS` in `docker-compose.yml`).
- **Storage** depends on report volume and retention. At 180-day default retention, plan roughly 1 GB per 50 monitored domains. Clients with longer retention (e.g., 730 days for compliance) will need proportionally more.
- **vCPUs** — OpenSearch and parsedmarc are the heaviest consumers. 2 cores work for small deployments (<50 domains), but 4+ is recommended once you're managing 100+ domains across multiple clients.

### Prerequisites

- Docker and Docker Compose
- A domain for receiving DMARC reports (e.g., `dmarc.msp-example.com`)
- DNS provider API credentials (Cloudflare, Route 53, GCP, or Azure)

### 1. Clone and configure

```bash
git clone https://github.com/domainaware/dmarc-msp.git
cd dmarc-msp

# Copy templates
cp .env.example .env
cp parsedmarc.example.ini parsedmarc.ini
cp dmarc-msp.example.yaml dmarc-msp.yaml
chmod 600 .env parsedmarc.ini

# Set your MSP domain, OpenSearch password, and DNS provider credentials
# (see DNS Providers section for which env vars your provider needs)
$EDITOR .env

# Set the same OpenSearch password here (replace CHANGEME)
$EDITOR parsedmarc.ini

# Initialize the domain map (empty file — dmarc-msp will populate it)
touch domain_map.yaml

# Edit the config — set your MSP domain, DNS zone, and provider
$EDITOR dmarc-msp.yaml

# Uncomment the env vars for your DNS provider in docker-compose.yml
$EDITOR docker-compose.yml
```

### 2. Obtain TLS certificate

```bash
docker compose run --rm --entrypoint certbot certbot certonly \
  --standalone -d dmarc.msp-example.com \
  --agree-tos -m admin@msp-example.com
```

### 3. Start the stack

```bash
docker compose up -d
```

### 4. Validate

```bash
docker compose exec dmarc-msp dmarcmsp config-validate
```

## Usage

All commands are run via `docker compose exec dmarc-msp dmarcmsp` (or set up a shell alias):

**Bash / Zsh** (Linux, macOS):

```bash
alias dmarcmsp='docker compose exec dmarc-msp dmarcmsp'
```

Add to `~/.bashrc` or `~/.zshrc` to persist.

**Fish**:

```fish
alias dmarcmsp 'docker compose exec dmarc-msp dmarcmsp'
```

To persist, run `funcsave dmarcmsp` or add the alias to `~/.config/fish/config.fish`.

### Client management

```bash
# Create a client
dmarcmsp client create "Acme Corp" --contact acme@example.com

# Create with custom retention (e.g., 2 years for compliance)
dmarcmsp client create "HealthCo" --contact hc@example.com --retention-days 730

# List clients
dmarcmsp client list
dmarcmsp client list --all          # include offboarded

# Show full client status with domains
dmarcmsp client show "Acme Corp"

# Update contact or retention
dmarcmsp client update "Acme Corp" --contact new@acme.com
dmarcmsp client update "Acme Corp" --retention-days 365

# Rename a client (index prefix and tenant stay the same)
dmarcmsp client rename "Acme Corp" --new-name "Acme Inc"

# Offboard (preview first, then execute)
dmarcmsp client offboard "Acme Corp" --dry-run
dmarcmsp client offboard "Acme Corp"
dmarcmsp client offboard "Acme Corp" --purge-indices   # also delete data
```

### Domain management

```bash
# Add domains
dmarcmsp domain add --client "Acme Corp" --domain acme.com
dmarcmsp domain add --client "Acme Corp" --domain acme.net

# Remove a domain
dmarcmsp domain remove --domain acme.net
dmarcmsp domain remove --domain acme.net --keep-dns

# Move a domain to another client
dmarcmsp domain move --domain acme.net --to "Other Corp"

# Verify DNS propagation
dmarcmsp domain verify --domain acme.com

# List domains
dmarcmsp domain list
dmarcmsp domain list --client "Acme Corp"
```

### Bulk operations

Create a text file with one domain per line (blank lines and `#` comments are skipped):

```bash
dmarcmsp domain bulk-add --client "Acme Corp" --file domains.txt
dmarcmsp domain bulk-remove --file domains.txt
dmarcmsp domain bulk-move --to "Other Corp" --file domains.txt
```

### Granular operations

```bash
# Manually provision/deprovision an OpenSearch tenant
dmarcmsp tenant provision --client "Acme Corp"
dmarcmsp tenant deprovision --client "Acme Corp"

# Re-import dashboards (e.g., after a parsedmarc update)
dmarcmsp dashboard import --client "Acme Corp"

# Reload parsedmarc config
dmarcmsp parsedmarc reload
```

### Management API

The API server starts automatically with `docker compose up`. It binds to `127.0.0.1:8000` (localhost only) and is restricted by an IP allowlist.

```bash
# Or start manually
dmarcmsp serve --host 0.0.0.0 --port 8000

# Example API calls
curl localhost:8000/health
curl -X POST localhost:8000/api/v1/clients \
  -H 'Content-Type: application/json' \
  -d '{"name": "Acme Corp", "contact_email": "admin@acme.com"}'
curl localhost:8000/api/v1/clients
```

API docs are available at `http://localhost:8000/docs` (Swagger UI).

## How It Works

1. **One email address** (`reports@dmarc.msp-example.com`) receives all DMARC reports for all clients via Postfix.
2. **parsedmarc** processes the reports and routes them to per-client OpenSearch indices using a YAML domain-to-index-prefix mapping file.
3. **OpenSearch** stores the parsed reports. Each client is isolated via tenants, roles, and index prefixes.
4. **OpenSearch Dashboards** provides per-client views. Clients log in and see only their own tenant's data.
5. **dmarc-msp** manages the lifecycle: DNS records, YAML mappings, OpenSearch provisioning, dashboard imports, and retention policies.

### DNS Authorization (RFC 7489)

When a client's `_dmarc` record sends reports to your MSP's address, report senders check for an authorization record on your domain. Without it, reports are silently dropped. dmarc-msp automatically creates these records:

```text
client.example.com._report._dmarc.dmarc.msp-example.com.  TXT  "v=DMARC1"
```

## DNS Providers

Set `dns.provider` in `dmarc-msp.yaml` and configure credentials in `.env`. Then uncomment the matching environment variables in the `dmarc-msp` service in `docker-compose.yml`.

|Provider|`dns.provider`|Credentials (set in `.env`)|pip extra|
|--|--|--|--|
|Cloudflare|`cloudflare`|`CLOUDFLARE_API_TOKEN` — API token with Zone:DNS:Edit permission|*(included)*|
|Route 53|`route53`|`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`|`dmarc-msp[aws]`|
|GCP|`gcp`|`secrets/gcp_sa_key.json` — service account key file (Docker secret)|`dmarc-msp[gcp]`|
|Azure|`azure`|`AZURE_CLIENT_ID` + `AZURE_CLIENT_SECRET` + `AZURE_TENANT_ID`|`dmarc-msp[azure]`|

Most providers use environment variables in `.env`. GCP is the exception — it requires a JSON key file, configured as a Docker secret. Uncomment the `secrets:` entries in `docker-compose.yml` if using GCP.

Cloudflare is the default and its dependency is included in the base install. For other providers, install the corresponding pip extra (e.g., `pip install dmarc-msp[aws]`).

See `dmarc-msp.example.yaml` for the full set of provider-specific config options.

## Production Deployment

For a production server, create a dedicated system user and a systemd service so the stack starts at boot.

### System user setup

```bash
# Create a system user (don't create home dir — git clone will)
sudo useradd -r -d /opt/dmarc-msp -s /bin/bash dmarc-msp

# Add it to the docker group
sudo usermod -aG docker dmarc-msp

# Add your own user to the docker group so you can run docker commands
# without sudo (log out and back in for this to take effect)
sudo usermod -aG docker $USER

# Create the home directory and clone the repo
sudo mkdir /opt/dmarc-msp
sudo chown dmarc-msp:dmarc-msp /opt/dmarc-msp
sudo -u dmarc-msp git clone https://github.com/domainaware/dmarc-msp.git /opt/dmarc-msp
```

Then follow the [Quick Start](#quick-start) configuration steps (copy templates, set passwords, create secrets) inside `/opt/dmarc-msp`, running commands with `sudo -u dmarc-msp`:

```bash
cd /opt/dmarc-msp
sudo -u dmarc-msp cp .env.example .env
sudo -u dmarc-msp cp parsedmarc.example.ini parsedmarc.ini
sudo -u dmarc-msp cp dmarc-msp.example.yaml dmarc-msp.yaml
# ... edit files, create secrets, etc.
```

### systemd service

Create `/etc/systemd/system/dmarc-msp.service`:

```ini
[Unit]
Description=DMARC for MSPs
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=dmarc-msp
Group=dmarc-msp
WorkingDirectory=/opt/dmarc-msp
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dmarc-msp

# Check status
sudo systemctl status dmarc-msp
sudo -u dmarc-msp docker compose -C /opt/dmarc-msp ps
```

### Updating

```bash
sudo -u dmarc-msp git -C /opt/dmarc-msp pull
sudo systemctl restart dmarc-msp
```

## Development

```bash
# Create a virtual environment and install
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest

# Use dev compose (no TLS, security disabled)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Architecture

### Code Structure

```text
dmarc-msp/
├── dmarc_msp/
│   ├── config.py              # Pydantic Settings (YAML + env + secrets)
│   ├── models.py              # Pydantic models
│   ├── db.py                  # SQLAlchemy + SQLite
│   ├── services/              # Core business logic
│   │   ├── clients.py         # Client CRUD
│   │   ├── dns.py             # DNS record lifecycle
│   │   ├── opensearch.py      # Tenant/role provisioning
│   │   ├── dashboards.py      # Saved object rewrite + import
│   │   ├── parsedmarc.py      # YAML mapping management
│   │   ├── retention.py       # ISM policy management
│   │   ├── onboarding.py      # Onboarding orchestrator
│   │   └── offboarding.py     # Offboarding orchestrator
│   ├── dns_providers/         # Pluggable DNS backends
│   ├── cli/                   # Typer CLI
│   └── api/                   # FastAPI management API
├── docker-compose.yml         # Full production stack
├── docker-compose.dev.yml     # Dev overrides
└── tests/
```

The service layer contains all business logic. The CLI and API are thin wrappers that call services directly.

### Network Topology

The stack uses two Docker networks to separate public-facing services from internal infrastructure:

```text
                    Internet
                       │
┌──────────────────────────────────────────────────────────┐
│                  Docker Compose                          │
│                                                          │
│  ╔═══════════ frontend network ═══════════════════════╗  │
│  ║                                                    ║  │
│  ║  ┌────────────┐  ┌──────────────┐                  ║  │
│  ║  │ Postfix    │  │ Dashboards   │                  ║  │
│  ║  │ :25/:587   │  │ :443         │                  ║  │
│  ║  └────────────┘  └──────────────┘                  ║  │
│  ║                                                    ║  │
│  ║  ┌────────────┐  ┌──────────────┐                  ║  │
│  ║  │ certbot    │  │ dmarc-msp    │                  ║  │
│  ║  │ →LE API    │  │ →DNS APIs    │                  ║  │
│  ║  └────────────┘  │ :8000(lo)    │                  ║  │
│  ║                  └──────────────┘                  ║  │
│  ║                                                    ║  │
│  ║  ┌────────────────┐                                ║  │
│  ║  │ parsedmarc     │                                ║  │
│  ║  │ →reverse DNS   │                                ║  │
│  ║  └────────────────┘                                ║  │
│  ║                                                    ║  │
│  ╚══╤══╤══╤══╤══╤══╤══════════════════════════════════╝  │
│     │  │  │  │  │  │                                     │
│  ╔══╧══╧══╧══╧══╧══╧══════════════════════════════════╗  │
│  ║  backend network (internal: true)                  ║  │
│  ║                                                    ║  │
│  ║  ┌────────────────────────────┐                    ║  │
│  ║  │ OpenSearch (no host port)  │                    ║  │
│  ║  └────────────────────────────┘                    ║  │
│  ║                                                    ║  │
│  ║  ┌──────────┐  ┌──────────┐                        ║  │
│  ║  │ cron     │  │ Maildir  │                        ║  │
│  ║  └──────────┘  └──────────┘                        ║  │
│  ║                                                    ║  │
│  ╚════════════════════════════════════════════════════╝  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

- **`frontend`** — services that need external connectivity (inbound or outbound).
- **`backend`** — internal-only (`internal: true`). No service on this network can reach the internet. OpenSearch lives here exclusively.

Services that bridge both networks: Postfix, Dashboards, parsedmarc, dmarc-msp, certbot.

### Externally Reachable Ports

| Port       | Service    | Purpose                              |
|------------|------------|--------------------------------------|
| `:25`      | Postfix    | SMTP from DMARC report senders       |
| `:587`     | Postfix    | SMTP submission (STARTTLS)           |
| `:443`     | Dashboards | HTTPS for client browser access      |
| `lo:8000`  | dmarc-msp  | Management API (localhost only)      |

OpenSearch `:9200` is exposed only internally — no host port binding.

### Outbound Connections

| Service    | Destination              | Purpose                    |
|------------|--------------------------|----------------------------|
| dmarc-msp  | DNS provider APIs        | Create/delete TXT records  |
| certbot    | Let's Encrypt ACME       | TLS certificate management |
| parsedmarc | DNS resolvers (1.1.1.1)  | Reverse DNS lookups        |

## Security

### Secrets Management

Secrets are managed via two mechanisms — no external secrets manager required:

1. **`.env` file** — for values Docker Compose interpolates into service definitions (e.g., `OPENSEARCH_ADMIN_PASSWORD`). Gitignored, created during setup.
2. **Docker Compose `secrets`** — for values mounted as files at `/run/secrets/<name>`. These don't appear in `docker inspect`, process listings, or environment dumps.

The application resolves secrets in priority order: environment variable > Docker secret file > config YAML value.

**Files that must never be committed** (enforced via `.gitignore`):

- `.env` — Docker Compose environment variables
- `secrets/` — Docker secret files (API tokens, credentials)
- `parsedmarc.ini` — contains the OpenSearch password
- `domain_map.yaml` — auto-managed, contains client domain mappings
- `*.db` — SQLite database (client list, audit trail)

### Attack Surface

#### What's exposed to the internet

| Surface | Risk | Mitigation |
| -- | -- | -- |
| **Postfix SMTP** (`:25/:587`) | Spam, malformed reports, resource exhaustion | Postfix accepts mail only for the configured reporting address. Message size is capped at 10 MB. parsedmarc validates report format before processing. STARTTLS is enabled via certbot-managed certificates. |
| **OpenSearch Dashboards** (`:443`) | Unauthorized data access, credential brute-force | Clients authenticate via OpenSearch Security. Each client's role is scoped to their own tenant and index prefix — they cannot access other clients' data. The `kibanaserver` service account proxies requests internally. |

#### What's exposed to the local host only

| Surface | Risk | Mitigation |
| -- | -- | -- |
| **Management API** (`127.0.0.1:8000`) | Unauthorized admin operations | Binds to localhost only — not reachable from the network. An IP allowlist middleware provides a second layer. No token auth in v1; access control relies on network-level restrictions. |
| **Docker socket** (`/var/run/docker.sock`) | Container escape, host compromise | Mounted into the dmarc-msp container for sending SIGHUP to parsedmarc. Only the dmarc-msp container has access. This is a privileged surface — restrict host access to the Docker socket accordingly. |

#### What's internal only (no internet, no host ports)

| Surface | Risk | Mitigation |
| -- | -- | -- |
| **OpenSearch** (`:9200`) | Full cluster access if compromised | Lives exclusively on the `backend` network (`internal: true`). No host port binding, no outbound internet. Only reachable by sibling containers. Admin password never leaves the Docker network. |
| **SQLite database** | Client list and audit trail disclosure | Stored on a Docker volume (`msp-data`). Contains client names, domains, and audit logs — no credentials. Access requires host filesystem or container access. |

### Client Isolation Model

Each client gets:

- **OpenSearch tenant** — a namespaced workspace in Dashboards
- **Scoped role** — read access restricted to `{index_prefix}-*` indices and their own tenant
- **Index prefix** — all report data lands in `{prefix}-aggregate-*`, `{prefix}-forensic-*`, etc.

Clients authenticate to Dashboards, not to OpenSearch directly. The `kibanaserver` service account proxies queries internally. A client cannot:

- See another client's tenant or indices
- Access the OpenSearch API directly
- Modify their own role or tenant configuration

### Hardening Recommendations

- **Restrict Docker socket access** on the host. Consider using a Docker socket proxy like [Tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) to limit the dmarc-msp container to only the `containers/kill` endpoint.
- **Set file permissions** during setup: `chmod 600 .env parsedmarc.ini` and `chmod 700 secrets/`.
- **Enable a firewall** — only ports 25, 587, and 443 need to be open to the internet. Port 8000 should never be exposed beyond localhost.
- **Rotate secrets** by updating `.env`, the matching secret file, and `parsedmarc.ini`, then restarting affected services. No code changes required.
- **Use a reverse proxy** (e.g., nginx, Caddy) in front of Dashboards for additional access controls, rate limiting, or IP restrictions.
- **Monitor the audit log** — every onboarding, offboarding, and provisioning action is recorded with timestamps in the `audit_log` table.
- **Keep images updated** — pin OpenSearch and parsedmarc to specific versions in `docker-compose.yml` and update deliberately.

## License

Apache 2.0
