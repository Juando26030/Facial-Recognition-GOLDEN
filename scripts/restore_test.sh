#!/usr/bin/env bash
# Prueba de RESTAURACIÓN de un respaldo real (docs/15 D2.5j): último respaldo DIARIO del bucket → RAMA TEMPORAL de Neon → conteos por tabla → compara con la base viva → tiempos.
# Lo corre Juan David; no toca la base viva (solo la lee) ni el bucket (solo lo lee). La rama de Neon se crea y se borra a mano en la consola.
#
#   1) Neon (consola): rama temporal «restore-test» del proyecto de producción (vacía o hija: el script la VACÍA). Copia su cadena DIRECTA del dueño en `.env.restore`
#      (DIRECT_DATABASE_URL=…) y crea el rol de la app:  python scripts/neon_app_role.py --env-file .env.restore
#   2) BACKUP_BUCKET=<bucket de respaldos> TARGET_ENV_FILE=.env.restore [LIVE_ENV_FILE=.env.live] bash scripts/restore_test.sh
#      LIVE_ENV_FILE (opcional): DIRECT_DATABASE_URL de la base VIVA (solo lectura) para comparar los conteos del respaldo con los de ahora.
#   3) Borra la rama «restore-test» en la consola de Neon.
# El resultado vale si: restauración OK (migrate_db_to_neon.py cuenta filas en el volcado y en el destino; una diferencia = fallo) y los conteos vivos no son MENORES que los del respaldo
# salvo por lo borrado desde entonces. Deja `restore_test_AAAAMMDD.log` con la duración de cada paso.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BACKUP_BUCKET:?define BACKUP_BUCKET (bucket de respaldos)}" "${TARGET_ENV_FILE:?define TARGET_ENV_FILE (.env.restore: rama TEMPORAL de Neon, nunca la viva)}"
PY="${PYTHON:-python}"; LOG="restore_test_$(date +%Y%m%d).log"
step() { local n="$1"; shift; local t=$SECONDS; echo "== $n"; "$@"; echo "$(date -Is) $n rc=$? $((SECONDS - t))s" | tee -a "$LOG"; }

OBJ="$(gcloud storage ls -l "gs://$BACKUP_BUCKET/db/daily/**" | grep '\.sql\.gz$' | sort -k2 | tail -1 | awk '{print $3}')"
[ -n "$OBJ" ] || { echo "No hay respaldos diarios en gs://$BACKUP_BUCKET/db/daily/" >&2; exit 1; }
echo "respaldo: $OBJ" | tee -a "$LOG"
FILE="restore_test_dump.sql.gz"
step "descargar" gcloud storage cp "$OBJ" "$FILE"
gzip -t "$FILE" && echo "gzip íntegro ($(du -h "$FILE" | cut -f1))" | tee -a "$LOG"
step "restaurar + contar + alembic" "$PY" scripts/migrate_db_to_neon.py --source-dump "$FILE" --target-env-file "$TARGET_ENV_FILE" --wipe --migrate
if [ -n "${LIVE_ENV_FILE:-}" ]; then
  echo "== conteos de la base viva (solo lectura): compáralos con los de arriba" | tee -a "$LOG"
  "$PY" - "$LIVE_ENV_FILE" <<'EOF' | tee -a "$LOG"
import sys
import psycopg2
from scripts.neon_app_role import env_value, read_env
raw, _ = read_env(sys.argv[1])
url = env_value(raw, "DIRECT_DATABASE_URL")
with psycopg2.connect(url) as c, c.cursor() as cur:
    c.set_session(readonly=True)
    cur.execute("select relname from pg_stat_user_tables order by 1")
    for (t,) in cur.fetchall():
        cur.execute(f'select count(*) from "{t}"'); print(f"  vivo {t}={cur.fetchone()[0]}")
EOF
fi
rm -f "$FILE"
echo "OK — duraciones en $LOG. Borra la rama temporal de Neon."
