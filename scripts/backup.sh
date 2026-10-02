#!/usr/bin/env bash
# Compressed logical backup of the PostgreSQL database into ./backups (never served by Caddy).
# Covers PostgreSQL ONLY. FORMS_DIR (volume forms_data) is not included: in Hito 0 it holds
# no forms, but once the Form Loader exists a full backup must be PostgreSQL + FORMS_DIR.
# Usage: scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "No existe .env en $(pwd)" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

mkdir -p backups
chmod 700 backups
stamp="$(date +%Y-%m-%d_%H%M%S)"
target="backups/formmanager_${stamp}.sql.gz"
tmp="${target}.partial"

umask 077
docker compose exec -T db pg_dump \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --clean --if-exists --no-owner --no-privileges \
    | gzip -9 > "$tmp"

if ! gzip -t "$tmp"; then
    rm -f "$tmp"
    echo "El backup está dañado; se eliminó." >&2
    exit 1
fi
mv "$tmp" "$target"
echo "Backup de PostgreSQL creado: $target ($(du -h "$target" | cut -f1))"
echo "Nota: FORMS_DIR no está incluido en este backup."
