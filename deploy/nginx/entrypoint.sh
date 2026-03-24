#!/bin/sh
set -e

if [ -z "$MSP_DOMAIN" ]; then
    echo "FATAL: MSP_DOMAIN environment variable is required" >&2
    exit 1
fi

CERT="/etc/letsencrypt/live/${MSP_DOMAIN}/fullchain.pem"

if [ -f "$CERT" ]; then
    echo "TLS certificates found — starting with HTTPS"
    envsubst '$MSP_DOMAIN' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
else
    echo "No TLS certificates — starting HTTP-only (ACME challenges + waiting for certbot)"
    envsubst '$MSP_DOMAIN' < /etc/nginx/nginx-http-only.conf.template > /etc/nginx/nginx.conf

    # Background: poll for certs and reload with full config when they appear
    (
        while [ ! -f "$CERT" ]; do
            sleep 5
        done
        echo "Certificates detected — switching to HTTPS"
        envsubst '$MSP_DOMAIN' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
        nginx -s reload
    ) &
fi

exec nginx -g 'daemon off;'
