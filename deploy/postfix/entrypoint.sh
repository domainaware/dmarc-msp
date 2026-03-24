#!/bin/sh
set -e

# Require MSP_DOMAIN
if [ -z "$MSP_DOMAIN" ]; then
    echo "FATAL: MSP_DOMAIN environment variable is required" >&2
    exit 1
fi

# Conditionally build TLS config block
CERT="/etc/letsencrypt/live/${MSP_DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${MSP_DOMAIN}/privkey.pem"

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    echo "TLS certificates found — enabling TLS"
    export TLS_CONFIG="smtpd_tls_cert_file = ${CERT}
smtpd_tls_key_file = ${KEY}
smtpd_tls_security_level = may
smtpd_tls_loglevel = 1
smtpd_tls_protocols = >=TLSv1.2"
else
    echo "WARNING: TLS certificates not found at ${CERT} — starting without TLS"
    echo "         Restart this container after certbot obtains certificates."
    export TLS_CONFIG="# TLS disabled — certificates not yet available"
fi

# Render main.cf from template (only substitute our variables, not Postfix $vars)
envsubst '$MSP_DOMAIN $TLS_CONFIG' < /etc/postfix/main.cf.template > /etc/postfix/main.cf
chmod 644 /etc/postfix/main.cf

# Ensure Maildir ownership (volume may be freshly created)
chown -R dmarc:dmarc /var/mail/dmarc
chmod 700 /var/mail/dmarc

# Create aliases db (Postfix needs this even if empty)
postalias /etc/postfix/aliases 2>/dev/null || newaliases

# Start Postfix in foreground
exec postfix start-fg
