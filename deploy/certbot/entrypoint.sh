#!/bin/sh
trap exit TERM

# --- Main domain certificate ---

if [ ! -f "/etc/letsencrypt/live/${MSP_DOMAIN}/fullchain.pem" ]; then
    echo "No certificate found — requesting initial cert for ${MSP_DOMAIN}"
    certbot certonly --webroot -w /var/www/certbot \
        -d "$MSP_DOMAIN" \
        --non-interactive --agree-tos --email "$CERTBOT_EMAIL"
fi

# --- MTA-STS subdomain certificate (conditional on DNS) ---

if getent hosts "mta-sts.${MSP_DOMAIN}" >/dev/null 2>&1; then
    if [ ! -f "/etc/letsencrypt/live/mta-sts.${MSP_DOMAIN}/fullchain.pem" ]; then
        echo "mta-sts.${MSP_DOMAIN} resolves — requesting certificate"
        certbot certonly --webroot -w /var/www/certbot \
            -d "mta-sts.${MSP_DOMAIN}" \
            --non-interactive --agree-tos --email "$CERTBOT_EMAIL"
    fi
else
    echo "mta-sts.${MSP_DOMAIN} does not resolve — skipping MTA-STS certificate"
fi

# --- Renewal loop (handles all certificates) ---

while :; do
    certbot renew --quiet \
        --deploy-hook "docker kill -s HUP nginx && docker kill -s HUP postfix"
    sleep 12h &
    wait $!
done
