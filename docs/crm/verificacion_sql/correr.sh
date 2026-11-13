#!/usr/bin/env bash
# Corre toda la verificación SQL contra un PostgreSQL temporal (como usuario NO root). Uso: ./correr.sh   (necesita initdb/pg_ctl de PostgreSQL 14+ en /usr/lib/postgresql/*/bin)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)"
D=/tmp/pgc
if [ ! -d "$D/d" ]; then mkdir -p "$D" && "$BIN/initdb" -D "$D/d" -A trust >/dev/null; fi
"$BIN/pg_ctl" -D "$D/d" -o "-p 55432 -k $D" -l "$D/log" -w start >/dev/null
P="psql -h $D -p 55432 -U $(whoami)"
$P -d postgres -qc "DROP DATABASE IF EXISTS crmtest" -c "CREATE DATABASE crmtest"
Q="$P -d crmtest -q"
$Q -v ON_ERROR_STOP=1 -f "$HERE/00_base_minima.sql" -f "$HERE/01_migracion_0130_subida.sql" -f "$HERE/03_next_code_espejo.sql" && echo "== SUBIDA OK"
$Q -f "$HERE/04_pruebas.sql" 2>&1
PSQL="$P -d crmtest -q -tA" "$HERE/05_concurrencia.sh" 40
$Q -c "UPDATE tenants SET legacy_client_code='HEX1', client_code='999' WHERE id='t1'" -c "SELECT id, client_code FROM tenants WHERE id='t1'"
$Q -v ON_ERROR_STOP=1 -f "$HERE/02_migracion_0130_reversa.sql" && echo "== REVERSA OK" && $Q -c "SELECT id, client_code FROM tenants WHERE id='t1'" -c "SELECT count(*) AS tablas_crm_que_quedan FROM information_schema.tables WHERE table_name LIKE 'crm_%'"
"$BIN/pg_ctl" -D "$D/d" stop -m fast >/dev/null
