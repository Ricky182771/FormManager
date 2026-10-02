#!/usr/bin/env bash
# Smoke test of a running stack: container isolation checks, then HTTP checks through Caddy.
# Usage: BASE_URL=https://localhost ADMIN_USER=... ADMIN_PASS=... CURL_INSECURE=1 scripts/smoke_test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BASE_URL:?}" "${ADMIN_USER:?}" "${ADMIN_PASS:?}"

fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

bindings() { docker inspect -f '{{json .HostConfig.PortBindings}}' "$(docker compose ps -q "$1")"; }
check "db publishes no host ports" '[ "$(bindings db)" = "{}" ]'
check "app publishes no host ports" '[ "$(bindings app)" = "{}" ]'
check "only caddy publishes ports" \
    '[ -z "$(docker compose ps --format "{{.Service}} {{.Ports}}" | grep -- "->" | grep -v "^caddy ")" ]'
check "app runs as uid 10001 (non-root)" '[ "$(docker compose exec -T app id -u)" = "10001" ]'
check "app root filesystem is read-only" '! docker compose exec -T app sh -c "touch /srv/x" 2>/dev/null'
check "FORMS_DIR is writable" 'docker compose exec -T app sh -c "touch /data/forms/.w && rm /data/forms/.w"'
check "app does not receive POSTGRES_PASSWORD" '! docker compose exec -T app env | grep -q "^POSTGRES_PASSWORD="'

python3 scripts/smoke_test.py || fail=1
exit "$fail"
