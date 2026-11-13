#!/usr/bin/env bash
# Verifica las migraciones 0131..0134 de la etapa C1c–C4 contra un PostgreSQL temporal: sube cada archivo REAL de alembic/versions (convertido a SQL por alembic_a_sql.py), corre las pruebas de
# 06_pruebas_etapa.sql y baja todo en orden inverso comprobando que no queda ninguna tabla nueva. Uso: ./correr_etapa.sh   (necesita initdb/pg_ctl de PostgreSQL 14+ en /usr/lib/postgresql/*/bin)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
BIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)"
D=/tmp/pgc
if [ ! -d "$D/d" ]; then mkdir -p "$D" && "$BIN/initdb" -D "$D/d" -A trust >/dev/null; fi
"$BIN/pg_ctl" -D "$D/d" -o "-p 55432 -k $D" -l "$D/log" -w start >/dev/null 2>&1
P="psql -h $D -p 55432 -U $(whoami)"
$P -d postgres -qc "DROP DATABASE IF EXISTS etapatest" -c "CREATE DATABASE etapatest"
Q="$P -d etapatest -q"
MIGS=$(ls "$REPO"/alembic/versions/013[1-9]_*.py 2>/dev/null)
$Q -v ON_ERROR_STOP=1 -f "$HERE/00_base_minima.sql" -f "$HERE/01_migracion_0130_subida.sql" >/dev/null || exit 1
for f in $MIGS; do
  python3 "$HERE/alembic_a_sql.py" "$f" upgrade > /tmp/up.sql && $Q -v ON_ERROR_STOP=1 -f /tmp/up.sql && echo "== SUBIDA OK $(basename "$f")" || { echo "== SUBIDA FALLÓ $(basename "$f")"; exit 1; }
done
$Q -v ON_ERROR_STOP=0 -f "$HERE/06_pruebas_etapa.sql" 2>&1
for f in $(echo "$MIGS" | sort -r); do
  python3 "$HERE/alembic_a_sql.py" "$f" downgrade > /tmp/down.sql && $Q -v ON_ERROR_STOP=1 -f /tmp/down.sql && echo "== REVERSA OK $(basename "$f")" || { echo "== REVERSA FALLÓ $(basename "$f")"; exit 1; }
done
$Q -tA -c "SELECT 'tablas_crm_que_quedan: ' || string_agg(table_name, ',' ORDER BY table_name) FROM information_schema.tables WHERE table_name LIKE 'crm_%'"
# la subida otra vez, para comprobar que la reversa deja todo limpio
for f in $MIGS; do python3 "$HERE/alembic_a_sql.py" "$f" upgrade > /tmp/up.sql && $Q -v ON_ERROR_STOP=1 -f /tmp/up.sql || { echo "== SEGUNDA SUBIDA FALLÓ $(basename "$f")"; exit 1; }; done && echo "== SEGUNDA SUBIDA OK"
"$BIN/pg_ctl" -D "$D/d" stop -m fast >/dev/null
