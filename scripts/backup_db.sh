#!/usr/bin/env bash
# Backup diario de la base de datos (Sprint 4, ítem 1): copia local con rotación + copia EXTERNA en un bucket de
# Google Cloud Storage (así un fallo de la VM no se lleva también los backups).
#
# Uso (cron de la VM, 3 a.m.):   GCS_BUCKET=gs://golden-backups-XXXX /home/juando02603/Facial-Recognition/scripts/backup_db.sh
#
# Variables (todas opcionales salvo GCS_BUCKET para la copia externa):
#   GCS_BUCKET       bucket destino, ej. gs://golden-backups-XXXX. Vacío = solo copia local (y se avisa por log).
#   DB_NAME          base a respaldar (golden_db).
#   BACKUP_DIR       carpeta local (~/backups).
#   LOCAL_KEEP_DAYS  días que se conserva la copia local (7). La retención en el bucket la define su regla de
#                    ciclo de vida (deploy/gcs-lifecycle.json, 60 días), no este script.
#   PG_DUMP          comando de pg_dump (por defecto "pg_dump -U golden_app -h localhost", el mismo que ya usaba el
#                    cron de la VM; la contraseña sale de ~/.pgpass). No usa sudo: un cron no lo necesita.
#
# Cada corrida: (1) vuelca la base a .sql.gz de forma atómica, (2) verifica que el archivo sea válido y esté
# completo, (3) lo sube a  <bucket>/db/AAAA/MM/  y confirma que el objeto existe y pesa lo mismo, (4) rota lo local.
# Si la subida falla, sale con error (código 1) para que se note en el log/cron, pero la copia local queda.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
DB_NAME="${DB_NAME:-golden_db}"
LOCAL_KEEP_DAYS="${LOCAL_KEEP_DAYS:-7}"
GCS_BUCKET="${GCS_BUCKET:-}"
PG_DUMP="${PG_DUMP:-pg_dump -U golden_app -h localhost}"

mkdir -p "$BACKUP_DIR"
LOG="$BACKUP_DIR/backup.log"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

stamp="$(date +%Y%m%d_%H%M%S)"
final="$BACKUP_DIR/${DB_NAME}_${stamp}.sql.gz"
tmp="$final.partial"
trap 'rm -f "$tmp"' EXIT

log "Respaldando $DB_NAME -> $final"
# shellcheck disable=SC2086  # PG_DUMP puede llevar varias palabras a propósito
$PG_DUMP "$DB_NAME" | gzip > "$tmp"

# Verificación: gzip íntegro, y el volcado termina con la marca de pg_dump (si se cortó a la mitad no está).
gzip -t "$tmp"
if ! gzip -dc "$tmp" | tail -n 5 | grep -q "PostgreSQL database dump complete"; then
  log "ERROR: el volcado no terminó bien (falta la marca de fin de pg_dump). No se conserva."
  exit 1
fi
mv "$tmp" "$final"
size="$(wc -c < "$final" | tr -d ' ')"
log "Copia local lista ($size bytes)"

status=0
if [ -z "$GCS_BUCKET" ]; then
  log "AVISO: GCS_BUCKET no está definido — solo quedó la copia LOCAL (no protege contra la pérdida de la VM)."
  status=1
else
  dest="${GCS_BUCKET%/}/db/$(date +%Y)/$(date +%m)/$(basename "$final")"
  if command -v gcloud >/dev/null 2>&1; then
    gcloud storage cp "$final" "$dest" --quiet
    remote_size="$(gcloud storage ls -L "$dest" | awk '/Content-Length:/ {print $2}')"
  else
    gsutil -q cp "$final" "$dest"
    remote_size="$(gsutil ls -l "$dest" | awk 'NR==1 {print $1}')"
  fi
  if [ "$remote_size" != "$size" ]; then
    log "ERROR: el objeto en el bucket pesa $remote_size y el local $size — la subida no es confiable."
    status=1
  else
    log "Copia EXTERNA subida y verificada: $dest"
  fi
fi

# Rotación local (solo los volcados de este script; los pre_deploy_* manuales no se tocan).
find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}_*.sql.gz" -mtime +"$LOCAL_KEEP_DAYS" -print -delete | sed 's/^/Rotado: /' | tee -a "$LOG" || true

exit "$status"
