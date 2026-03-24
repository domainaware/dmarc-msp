#!/bin/sh
set -e

# Run email cleanup daily in the background
(
    while true; do
        sleep 86400
        dmarcmsp retention cleanup-emails 2>&1 || true
    done
) &

# Run the provided command (default: dmarcmsp serve)
exec "$@"
