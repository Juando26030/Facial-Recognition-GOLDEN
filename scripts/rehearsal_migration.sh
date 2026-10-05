#!/usr/bin/env bash
# Ensayo de la migración de datos VM → Neon + Cloud Storage (docs/15, «D2.5 · Ensayo de datos»). Lo corre Juan David; NO toca producción ni la VM
# (solo lee de ella). Cada paso imprime su duración y deja una línea en ensayo_<fecha>.log; el ensayo vale si los TRES pasos terminan en OK.
#
#   1) EN LA VM (solo lectura):      bash scripts/rehearsal_migration.sh vm-dump
#   2) DONDE HAYA psql/pg_dump 18:   TARGET_ENV_FILE=.env.ensayo bash scripts/rehearsal_migration.sh restore <golden_vm_....sql.gz>
#   3) EN LA VM (solo lectura):      BUCKET=<bucket de ENSAYO> bash scripts/rehearsal_migration.sh files
#
# `.env.ensayo` = copia de .env.staging apuntando a UNA RAMA NUEVA de Neon (crearla desde la consola: rama del proyecto, vacía o hija de staging; con
# golden_app creado por `python scripts/neon_app_role.py --env-file .env.ensayo`). El destino se VACÍA (--wipe): nunca apuntes a producción.
# `BUCKET` = un bucket de ensayo (p. ej. el de staging con PREFIX=ensayo); NUNCA el bucket de producción.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="ensayo_$(date +%Y%m%d).log"
PY="${PYTHON:-python}"

step() { # step <nombre> <comando...>: mide, registra y propaga el código de salida
  local name="$1"; shift
  local t0=$SECONDS
  echo "== $name"
  if "$@"; then local rc=0; else local rc=$?; fi
  echo "$(date -Is) $name rc=$rc $((SECONDS - t0))s" | tee -a "$LOG"
  return $rc
}

case "${1:-}" in
vm-dump)
  # Volcado completo + filas por tabla EN LA VM (para comparar con el destino) + tamaño y número de archivos de data/.
  DB_NAME="${DB_NAME:-golden_db}"; OUT="${OUT:-$HOME/ensayo}"; mkdir -p "$OUT"
  F="$OUT/golden_vm_$(date +%Y%m%d_%H%M).sql.gz"
  step "pg_dump" bash -c "${PG_DUMP:-pg_dump -U golden_app -h localhost} --no-owner --no-privileges '$DB_NAME' | gzip > '$F'"
  gzip -t "$F" && echo "volcado válido: $F ($(du -h "$F" | cut -f1))" | tee -a "$LOG"
  # conteo EXACTO por tabla (no n_live_tup, que es una estimación): una consulta generada con count(*) por tabla
  step "filas por tabla (origen)" bash -c "psql -U golden_app -h localhost -At '$DB_NAME' -c \"select string_agg(format('select %L||''=''||count(*) from %I', relname, relname), ' union all ' order by relname) from pg_stat_user_tables\" | psql -U golden_app -h localhost -At '$DB_NAME' > '$OUT/filas_origen.txt'"
  DATA="${DATA:-$HOME/Facial-Recognition/data}"
  echo "archivos en data/: $(find "$DATA" -type f ! -path '*/uploads/*' | wc -l)  tamaño: $(du -sh "$DATA" | cut -f1)" | tee -a "$LOG"
  echo "Siguiente: copia $F a donde correrás «restore»."
  ;;
restore)
  # Restaura en la rama de ensayo: migrate_db_to_neon.py cuenta filas por tabla en el volcado y en el destino (una diferencia = código 1), corre alembic hasta head y aplica permisos.
  : "${TARGET_ENV_FILE:?define TARGET_ENV_FILE (p. ej. .env.ensayo, una rama de Neon DE ENSAYO)}"
  DUMP="${2:?uso: restore <volcado.sql.gz>}"
  step "restaurar + contar + alembic" "$PY" scripts/migrate_db_to_neon.py --source-dump "$DUMP" --target-env-file "$TARGET_ENV_FILE" --wipe --migrate
  ;;
files)
  : "${BUCKET:?define BUCKET (bucket de ENSAYO, nunca el de producción)}"
  DATA="${DATA:-$HOME/Facial-Recognition/data}"; PREFIX="${PREFIX:-ensayo}"
  step "subir fotos y archivos (MD5)" "$PY" scripts/migrate_files_to_gcs.py --source "$DATA" --bucket "$BUCKET" --prefix "$PREFIX" --biometric-prefix biometric
  step "verificar (solo comparar)" "$PY" scripts/migrate_files_to_gcs.py --source "$DATA" --bucket "$BUCKET" --prefix "$PREFIX" --biometric-prefix biometric --verify-only
  ;;
*) echo "uso: $0 vm-dump | restore <volcado.sql.gz> | files" >&2; exit 2 ;;
esac
echo "OK — resultados en $LOG"
