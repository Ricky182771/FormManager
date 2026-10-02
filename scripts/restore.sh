#!/usr/bin/env bash
# Restore a PostgreSQL backup created by backup.sh. OVERWRITES the current database contents.
# Does not touch FORMS_DIR.
# Usage: scripts/restore.sh backups/formmanager_2026-10-02_213000.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."

file="${1:-}"
if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "Uso: $0 backups/formmanager_AAAA-MM-DD_HHMMSS.sql.gz" >&2
    ls -1 backups/*.sql.gz 2>/dev/null || true
    exit 1
fi
gzip -t "$file"

set -a
# shellcheck disable=SC1091
. ./.env
set +a

echo "ATENCIÓN: se reemplazará TODO el contenido de la base de datos '$POSTGRES_DB'"
echo "con el respaldo: $file"
echo "Recomendación: ejecuta antes scripts/backup.sh para conservar el estado actual."
read -r -p "Escribe RESTAURAR para continuar: " answer
if [ "$answer" != "RESTAURAR" ]; then
    echo "Cancelado."
    exit 1
fi

echo "Deteniendo la aplicación..."
docker compose stop app
# Bring the app back even if the restore fails part-way (the transaction rolls back).
trap 'echo "Iniciando la aplicación..."; docker compose start app' EXIT

# Restore as the application role (owner of the database) so restored objects keep the
# same owner as the originals. The db container trusts local socket connections.
gunzip -c "$file" | docker compose exec -T db psql \
    --username "${APP_DB_USER:-formmanager_app}" --dbname "$POSTGRES_DB" \
    --single-transaction -v ON_ERROR_STOP=1 --quiet

echo "Restauración completada."
