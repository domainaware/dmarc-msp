# Extra nginx server blocks

Drop `.conf` files here to add nginx server blocks for other domains or services
running on the same host. The main `nginx.conf` already includes everything in
`/etc/nginx/conf.d/` via:

```nginx
include /etc/nginx/conf.d/*.conf;
```

## Adding a new domain — step by step

### Step 1 — HTTP-only config (before the certificate exists)

Create `deploy/nginx/extra/myapp.conf` with an HTTP-only server block that serves
the ACME challenge path. Do not add the HTTPS block yet — nginx will fail to start
if the certificate files don't exist.

```nginx
server {
    listen 80;
    server_name myapp.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 503 "Waiting for TLS certificate — try again shortly.\n";
        default_type text/plain;
    }
}
```

### Step 2 — Mount the config file

Add a volume entry for the new config to `docker-compose.override.yml`. If the
file doesn't exist yet, copy the example first:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
```

Then add (or append) a bind-mount for your config under the `nginx` service
volumes:

```yaml
services:
  nginx:
    volumes:
      - ./deploy/nginx/extra/myapp.conf:/etc/nginx/conf.d/myapp.conf:ro
```

Apply the change so the file is visible inside the container:

```bash
docker compose up -d nginx
```

Verify that nginx accepted the config with no errors:

```bash
docker compose logs --tail=20 nginx
```

### Step 3 — Request the certificate

Use the certbot container that is already running in this stack:

```bash
docker compose exec certbot certbot certonly \
    --webroot -w /var/www/certbot \
    -d myapp.example.com \
    --non-interactive --agree-tos --email you@example.com
```

Certbot writes the certificate to the shared `certs` volume at
`/etc/letsencrypt/live/myapp.example.com/`.

### Step 4 — Update the config to HTTPS

Replace the contents of `deploy/nginx/extra/myapp.conf` with a full HTTP + HTTPS
config. Use `resolver 127.0.0.11` and a `set $backend` variable for the upstream
so that nginx can start (or reload) even if the upstream container is not yet
running.

```nginx
server {
    listen 80;
    server_name myapp.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name myapp.example.com;

    ssl_certificate     /etc/letsencrypt/live/myapp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/myapp.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_MYAPP:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    # Resolve the upstream at request time via Docker's embedded DNS resolver.
    # This allows nginx to reload even if the upstream container is not yet running.
    resolver 127.0.0.11 valid=30s;
    set $backend http://myapp:8080;

    location / {
        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Replace `myapp` with the Docker Compose service name of your backend and `8080`
with the port it listens on. The `shared:SSL_MYAPP:10m` cache zone name must be
unique — choose a name that does not conflict with other server blocks.

### Step 5 — Reload nginx to apply the HTTPS config

```bash
docker compose kill -s HUP parsedmarc-nginx
```
