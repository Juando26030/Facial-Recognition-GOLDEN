#!/usr/bin/env bash
# Copia el contenido de los buckets de la VM a los buckets NUEVOS de producción (los de la región de config.sh), con comprobación de conteos.
# Lo corre Juan David en Cloud Shell (no hace falta la VM). Solo LEE los buckets viejos y solo ESCRIBE en los nuevos. Repetible: rsync solo copia lo que falta o cambió.
#
#   bash deploy/gcp/copy_vm_buckets.sh --dry-run     # 1) qué copiaría (y cuántos objetos hay)
#   bash deploy/gcp/copy_vm_buckets.sh               # 2) copia y comprueba
#   bash deploy/gcp/copy_vm_buckets.sh --verify      # 3) solo comprueba (conteos por grupo + rsync en seco sin diferencias)
#
# Mapa (las claves nuevas son las que usa la app, ver app/storage.py y docs/15 R4):
#   VIEJO gs://<datos>/data/<cliente>/known_people/…   → NUEVO gs://<app>/app/biometric/<cliente>/known_people/…   (fotos biométricas: prefijo propio, ciclo de vida de 1 día en versiones viejas)
#   VIEJO gs://<datos>/data/<cliente>/… (lo demás)      → NUEVO gs://<app>/app/<cliente>/…
#   VIEJO gs://<respaldos>/db/…  (volcados de la VM)     → NUEVO gs://<respaldos>/db/vm/…   (historia de la VM; el Job de ops escribe en db/hourly y db/daily; el ciclo de vida los borra a los 30 días)
#   NO se copia: config/.env (tiene secretos: viven en Secret Manager), uploads/ ni temporales (*.part, .readyz).
# Nombres de los buckets viejos: OLD_DATA_BUCKET y OLD_BACKUP_BUCKET (por defecto los de la VM). Los nuevos salen de deploy/gcp/config.sh production.
# Alternativa equivalente y con MD5 desde el disco: scripts/migrate_files_to_gcs.py (runbook D2.4, paso 3); esta copia sirve para adelantar trabajo días antes o si la VM ya no está.
set -euo pipefail
cd "$(dirname "$0")/../.."
MODE="${1:-copy}"
# shellcheck source=/dev/null
source deploy/gcp/config.sh production                    # REGION, APP_BUCKET, APP_PREFIX (app), BACKUP_BUCKET: los NUEVOS
OLD_DATA="${OLD_DATA_BUCKET:-golden-datos-analisis-de-imagen-id}"; OLD_BACKUP="${OLD_BACKUP_BUCKET:-golden-backups-analisis-de-imagen-id}"
EXCL_TMP='(^|.*/)(uploads/.*|.*\.part|\.readyz)$'
KNOWN='(^|.*/)known_people/.*'
for b in "$OLD_DATA" "$OLD_BACKUP" "$APP_BUCKET" "$BACKUP_BUCKET"; do
  gcloud storage buckets describe "gs://$b" >/dev/null 2>&1 || { echo "No existe gs://$b (¿corriste bootstrap.sh production con la región nueva?)." >&2; exit 1; }
done
[ "$OLD_DATA" != "$APP_BUCKET" ] && [ "$OLD_BACKUP" != "$BACKUP_BUCKET" ] || { echo "El bucket viejo y el nuevo son el mismo: nada que copiar." >&2; exit 1; }

n() { grep -vc ':$' || true; }                            # cuenta objetos (las líneas «carpeta:» del listado no cuentan)
lsall() { gcloud storage ls -r "$1" 2>/dev/null | { grep -v "$2" || true; } | n; }

case "$MODE" in
  --dry-run|copy)
    DRY=""; [ "$MODE" = "--dry-run" ] && DRY="--dry-run"
    echo "== Archivos (sin biometría): gs://$OLD_DATA/data → gs://$APP_BUCKET/$APP_PREFIX"
    gcloud storage rsync --recursive $DRY --exclude "($EXCL_TMP)|($KNOWN)" "gs://$OLD_DATA/data" "gs://$APP_BUCKET/$APP_PREFIX"
    echo "== Fotos biométricas → gs://$APP_BUCKET/$APP_PREFIX/biometric/<cliente>/known_people"
    for t in $(gcloud storage ls "gs://$OLD_DATA/data/" | sed -n 's#^gs://[^/]*/data/\([^/]*\)/$#\1#p'); do
      if gcloud storage ls "gs://$OLD_DATA/data/$t/known_people/" >/dev/null 2>&1; then
        gcloud storage rsync --recursive $DRY "gs://$OLD_DATA/data/$t/known_people" "gs://$APP_BUCKET/$APP_PREFIX/biometric/$t/known_people"
      fi
    done
    echo "== Volcados de la VM: gs://$OLD_BACKUP/db → gs://$BACKUP_BUCKET/db/vm"
    gcloud storage rsync --recursive $DRY "gs://$OLD_BACKUP/db" "gs://$BACKUP_BUCKET/db/vm"
    [ -z "$DRY" ] || { echo "(en seco: no se copió nada)"; exit 0; }
    ;;
  --verify) ;;
  *) sed -n 2,6p "$0"; exit 2 ;;
esac

echo -e "\n== Comprobación de conteos"
fail=0
cmp_count() {   # etiqueta  viejo  nuevo
  if [ "$2" = "$3" ]; then echo "  OK    $1: $2 = $3"; else echo "  DIFIERE $1: viejo=$2 nuevo=$3"; fail=1; fi
}
old_all="$(gcloud storage ls -r "gs://$OLD_DATA/data/**" 2>/dev/null | grep -Ev "/(uploads/|\.readyz)|\.part$" | n)"
old_bio="$(gcloud storage ls -r "gs://$OLD_DATA/data/**" 2>/dev/null | grep -E "/known_people/" | n)"
new_all="$(gcloud storage ls -r "gs://$APP_BUCKET/$APP_PREFIX/**" 2>/dev/null | grep -Ev "/(uploads/|\.readyz)|\.part$" | n)"
new_bio="$(gcloud storage ls -r "gs://$APP_BUCKET/$APP_PREFIX/biometric/**" 2>/dev/null | n)"
cmp_count "fotos biométricas (data/*/known_people → app/biometric)" "$old_bio" "$new_bio"
cmp_count "archivos en total (biometría incluida)" "$old_all" "$new_all"
cmp_count "volcados de la VM (db → db/vm)" "$(lsall "gs://$OLD_BACKUP/db/**" '/vm/')" "$(gcloud storage ls -r "gs://$BACKUP_BUCKET/db/vm/**" 2>/dev/null | n)"
echo "  Comprobación por contenido: un rsync en seco no debe listar nada por copiar (rsync compara tamaño y suma de verificación)."
pending="$(gcloud storage rsync --recursive --dry-run --exclude "($EXCL_TMP)|($KNOWN)" "gs://$OLD_DATA/data" "gs://$APP_BUCKET/$APP_PREFIX" 2>&1 | grep -ci 'would copy' || true)"
[ "$pending" = 0 ] && echo "  OK    archivos: nada pendiente" || { echo "  DIFIERE archivos: $pending por copiar"; fail=1; }
[ "$fail" = 0 ] && echo -e "\nTodo coincide." || { echo -e "\nHay diferencias: repite la copia (es segura) y vuelve a comprobar." >&2; exit 1; }
