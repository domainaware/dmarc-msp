#!/bin/sh
set -e

if [ -z "$MSP_DOMAIN" ]; then
    echo "FATAL: MSP_DOMAIN environment variable is required" >&2
    exit 1
fi

CERT="/etc/letsencrypt/live/${MSP_DOMAIN}/fullchain.pem"
MTA_STS_CERT="/etc/letsencrypt/live/mta-sts.${MSP_DOMAIN}/fullchain.pem"

mkdir -p /etc/nginx/conf.d

# --- Main domain ---

if [ -f "$CERT" ]; then
    echo "TLS certificates found — starting with HTTPS"
    envsubst '$MSP_DOMAIN' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
else
    echo "No TLS certificates — starting HTTP-only (ACME challenges + waiting for certbot)"
    envsubst '$MSP_DOMAIN' < /etc/nginx/nginx-http-only.conf.template > /etc/nginx/nginx.conf
fi

# --- MTA-STS subdomain (conditional on DNS) ---

MTA_STS_ENABLED=false
if getent hosts "mta-sts.${MSP_DOMAIN}" >/dev/null 2>&1; then
    MTA_STS_ENABLED=true
    echo "mta-sts.${MSP_DOMAIN} resolves — enabling MTA-STS server block"

    if [ -f "$MTA_STS_CERT" ]; then
        echo "MTA-STS certificate found — serving with HTTPS"
        envsubst '$MSP_DOMAIN' < /etc/nginx/mta-sts.conf.template > /etc/nginx/conf.d/mta-sts.conf
    else
        echo "No MTA-STS certificate — serving HTTP-only (ACME challenges + waiting for certbot)"
        envsubst '$MSP_DOMAIN' < /etc/nginx/mta-sts-http-only.conf.template > /etc/nginx/conf.d/mta-sts.conf
    fi
else
    echo "mta-sts.${MSP_DOMAIN} does not resolve — MTA-STS server block disabled"
fi

# --- Background: poll for certs and reload when they appear ---

(
    NEED_MAIN=false
    NEED_MTA_STS=false

    [ ! -f "$CERT" ] && NEED_MAIN=true
    [ "$MTA_STS_ENABLED" = true ] && [ ! -f "$MTA_STS_CERT" ] && NEED_MTA_STS=true

    # Nothing to wait for
    if [ "$NEED_MAIN" = false ] && [ "$NEED_MTA_STS" = false ]; then
        exit 0
    fi

    while [ "$NEED_MAIN" = true ] || [ "$NEED_MTA_STS" = true ]; do
        sleep 5

        if [ "$NEED_MAIN" = true ] && [ -f "$CERT" ]; then
            echo "Certificates detected — switching to HTTPS"
            envsubst '$MSP_DOMAIN' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
            NEED_MAIN=false
            nginx -s reload
        fi

        if [ "$NEED_MTA_STS" = true ] && [ -f "$MTA_STS_CERT" ]; then
            echo "MTA-STS certificate detected — switching to HTTPS"
            envsubst '$MSP_DOMAIN' < /etc/nginx/mta-sts.conf.template > /etc/nginx/conf.d/mta-sts.conf
            NEED_MTA_STS=false
            nginx -s reload
        fi
    done
) &

exec nginx -g 'daemon off;'
