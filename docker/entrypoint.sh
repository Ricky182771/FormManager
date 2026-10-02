#!/bin/sh
# "serve" (default): wait for PostgreSQL, migrate, then run a single Uvicorn worker.
# FORMS_DIR is prepared by the app at startup (generic initialization); there is no seed.
# Any other command (e.g. python -m app.security.generate_hash) runs as given.
set -eu

if [ "${1:-serve}" != "serve" ]; then
    exec "$@"
fi

python -m app.wait_for_db
alembic upgrade head

# One worker keeps the in-memory rate limiter coherent.
# Proxy headers are trusted from any peer because only Caddy can reach this port
# (internal Docker network, no published port) and Caddy overwrites X-Forwarded-*.
exec uvicorn app.main:create_app --factory \
    --host 0.0.0.0 --port 8000 --workers 1 \
    --proxy-headers --forwarded-allow-ips '*' \
    --no-access-log --no-server-header --timeout-graceful-shutdown 10
