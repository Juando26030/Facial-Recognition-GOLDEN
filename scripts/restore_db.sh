#!/usr/bin/env bash
# Restaura un backup (.sql.gz local o gs://...) en una base NUEVA (Sprint 4, ítem 1) y muestra conteos de las tablas
# principales para comprobar que los datos están completos.
#
# Uso:   scripts/restore_db.sh <archivo.sql.gz | gs://bucket/db/AAAA/MM/archivo.sql.gz> <base_destino>
# Ej.:   scripts/restore_db.sh gs://golden-backups-XXXX/db/2026/09/golden_db_20260923_030001.sql.gz golden_restore_test
#
# Por seguridad NO restaura sobre `golden_db` (la de producción) salvo que se pida explícitamente con
# FORCE_PRODUCTION=1 — y aun así primero hay que parar la app (`sudo systemctl stop facial-recognition`).
#
# Variables: PSQL (por defecto "sudo -u postgres psql"), CREATEDB ("sudo -u postgres createdb").
set -euo pipefail

SRC="${1:?Falta el archivo de backup (.sql.gz o gs://...)}"
TARGET="${2:?Falta el nombre de la base destino (ej. golden_restore_test)}"
PSQL="${PSQL:-sudo -u postgres psql}"
CREATEDB="${CREATEDB:-sudo -u postgres createdb}"

if [ "$TARGET" = "golden_db" ] && [ "${FORCE_PRODUCTION:-0}" != "1" ]; then
  echo "Me niego a restaurar sobre golden_db sin FORCE_PRODUCTION=1 (y con la app parada). Usa una base nueva para verificar."
  exit 2
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
file="$SRC"
if [[ "$SRC" == gs://* ]]; then
  file="$work/backup.sql.gz"
  if command -v gcloud >/dev/null 2>&1; then gcloud storage cp "$SRC" "$file" --quiet; else gsutil -q cp "$SRC" "$file"; fi
fi
gzip -t "$file"

echo "Creando base $TARGET y restaurando..."
# shellcheck disable=SC2086
$CREATEDB "$TARGET"
# shellcheck disable=SC2086
gzip -dc "$file" | $PSQL -v ON_ERROR_STOP=1 -q "$TARGET" > /dev/null

echo "Restauración lista. Conteos:"
# shellcheck disable=SC2086
$PSQL -At "$TARGET" -c "
  SELECT 'tenants', count(*) FROM tenants UNION ALL
  SELECT 'staff_users', count(*) FROM staff_users UNION ALL
  SELECT 'events', count(*) FROM events UNION ALL
  SELECT 'users', count(*) FROM users UNION ALL
  SELECT 'event_attendees', count(*) FROM event_attendees UNION ALL
  SELECT 'access_logs', count(*) FROM access_logs UNION ALL
  SELECT 'alembic_version', count(*) FROM alembic_version;"
echo "Versión de migración restaurada:"
# shellcheck disable=SC2086
$PSQL -At "$TARGET" -c "SELECT version_num FROM alembic_version;"
echo "Cuando termines de verificar:  sudo -u postgres dropdb $TARGET"
