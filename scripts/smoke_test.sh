#!/usr/bin/env bash
# Smoke test of a running stack: container isolation checks, then HTTP checks through Caddy.
# A synthetic form (slug room-booking) is created in FORMS_DIR, loaded by restarting the app,
# checked over HTTP, then removed and the app restarted again.
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
check "app drops all capabilities" \
    '[ "$(docker inspect -f "{{json .HostConfig.CapDrop}}" "$(docker compose ps -q app)")" = "[\"ALL\"]" ]'
check "FORMS_DIR is writable" 'docker compose exec -T app sh -c "touch /data/forms/.w && rm /data/forms/.w"'
check "app does not receive POSTGRES_PASSWORD" '! docker compose exec -T app env | grep -q "^POSTGRES_PASSWORD="'

wait_healthy() {
    for _ in $(seq 1 60); do
        status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q app)")
        [ "$status" = "healthy" ] && return 0
        sleep 2
    done
    echo "app did not become healthy" >&2
    return 1
}

form_id=$(docker compose exec -T app python -c '
from app.config import get_settings
from app.forms.creator import create_form_package
s = get_settings()
p = create_form_package(s.forms_dir, slug="room-booking", title="Reserva de sala",
                        subtitle="Formulario sintético de smoke test",
                        max_bytes=s.form_definition_max_bytes)
print(p.id)
' | tr -d '\r')
if ! [[ "$form_id" =~ ^[A-Za-z0-9_-]{16}$ ]]; then
    echo "FAIL synthetic form creation"
    exit 1
fi
echo "PASS synthetic form created ($form_id)"

cleanup() {
    docker compose exec -T app python -c '
import shutil, sys
from app.config import get_settings
shutil.rmtree(get_settings().forms_dir / sys.argv[1])
' "$form_id" || true
    docker compose restart app >/dev/null && wait_healthy || true
}
trap cleanup EXIT

docker compose restart app >/dev/null
wait_healthy
check "no .tmp-* staging left in FORMS_DIR" \
    '[ -z "$(docker compose exec -T app sh -c "ls -A /data/forms | grep ^.tmp- || true")" ]'

SMOKE_FORM_ID="$form_id" SMOKE_FORM_SLUG=room-booking python3 scripts/smoke_test.py || fail=1
exit "$fail"
