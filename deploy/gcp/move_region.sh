#!/usr/bin/env bash
# Mover un entorno de una región de Google Cloud a otra (docs/15 «Mover a otra región»). Lo corre Juan David en Cloud Shell; Claude Code no ejecuta nada en la nube.
#
#   OLD_REGION=us-east1 REGION=us-east4 bash deploy/gcp/move_region.sh <staging|production> plan      # 1) inventario: qué hay en la región vieja y qué falta en la nueva (solo lee)
#   ... <entorno> copy [--dry-run]                                                                    # 3) copia el contenido del bucket viejo al nuevo (solo staging; solo escribe en el NUEVO)
#   ... <entorno> verify                                                                              # 5) la región nueva responde (servicios, Jobs, cola, sitio público)
#   ... <entorno> cleanup                                                                             # 7) borra lo de la región vieja (pide escribir la región; se niega si la cola vieja no está vacía)
#
# El orden completo (bootstrap, GitHub, despliegue, Firebase, DNS…) está en docs/15. Este script NO crea nada en la región nueva: eso lo hacen bootstrap.sh y deploy.sh
# (idempotentes) con REGION=<nueva>. Producción no tiene nada en la región vieja si todavía no se corrió su bootstrap: solo se corre bootstrap con la región nueva.
# Lo que NUNCA toca: buckets de la VM (`data/`, `config/`, sus volcados), secretos, cuentas de servicio, Workload Identity, la base de Neon y el sitio de Firebase Hosting.
set -euo pipefail
cd "$(dirname "$0")/../.."
ENV_ARG="${1:-}"; ACTION="${2:-}"; shift 2 2>/dev/null || true
# shellcheck source=/dev/null
source deploy/gcp/config.sh "$ENV_ARG"                     # REGION (la NUEVA), PROJECT_ID, nombres, buckets nuevos
OLD_REGION="${OLD_REGION:-}"
[ -n "$OLD_REGION" ] || { echo "Falta OLD_REGION (la región de la que sales)." >&2; exit 2; }
[ "$OLD_REGION" != "$REGION" ] || { echo "OLD_REGION y REGION son la misma ($REGION): nada que mover." >&2; exit 2; }
# Bucket viejo (solo staging): su nombre NO llevaba la región. Producción no tiene bucket de Cloud Run en la región vieja (los de la VM no se tocan).
if [ "$GOLDEN_ENV" = staging ]; then OLD_APP_BUCKET="${OLD_APP_BUCKET:-${PROJECT_ID}-golden-staging}"; else OLD_APP_BUCKET="${OLD_APP_BUCKET:-}"; fi

say() { echo -e "\n== $*"; }
have() { "$@" >/dev/null 2>&1; }
# Recursos por NOMBRE (no por filtro: en producción «golden-*» también coincidiría con los de staging si comparten proyecto).
present() {  # región  -> imprime «servicio X / Job Y» de los que existen allí
  local r="$1" n
  for n in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do have gcloud run services describe "$n" --region "$r" && echo "  servicio $n"; done
  for n in "$JOB_MIGRATE" "$JOB_BULK" "$JOB_OPS"; do have gcloud run jobs describe "$n" --region "$r" && echo "  Job $n"; done
  return 0
}
count() { grep -c . || true; }

case "$ACTION" in
  plan)
    say "Entorno $GOLDEN_ENV · $OLD_REGION → $REGION · proyecto $PROJECT_ID"
    say "Región VIEJA ($OLD_REGION): lo que hay (esto es lo que genera costo o estorba)"
    present "$OLD_REGION"
    echo "cola de Cloud Tasks ($QUEUE): tareas pendientes = $(gcloud tasks list --queue "$QUEUE" --location "$OLD_REGION" --format 'value(name)' 2>/dev/null | count)"
    echo "tarea de Scheduler ($SCHEDULER_OPS): $(gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$OLD_REGION" --format 'value(state)' 2>/dev/null || echo 'no existe')"
    echo "repositorio de imágenes ($AR_REPO): $(gcloud artifacts repositories describe "$AR_REPO" --location "$OLD_REGION" --format 'value(sizeBytes)' 2>/dev/null || echo 'no existe') bytes"
    [ -z "$OLD_APP_BUCKET" ] || echo "bucket viejo gs://$OLD_APP_BUCKET: $(gcloud storage buckets describe "gs://$OLD_APP_BUCKET" --format 'value(location)' 2>/dev/null || echo 'no existe'), $(gcloud storage du -s "gs://$OLD_APP_BUCKET" 2>/dev/null | awk '{print $1}' || true) bytes"
    say "Región NUEVA ($REGION): lo que ya existe"
    present "$REGION"
    echo "cola: $(have gcloud tasks queues describe "$QUEUE" --location "$REGION" && echo sí || echo no) · repositorio: $(have gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" && echo sí || echo no) · bucket nuevo gs://$APP_BUCKET: $(have gcloud storage buckets describe "gs://$APP_BUCKET" && echo sí || echo no)"
    ;;

  copy)
    [ -n "$OLD_APP_BUCKET" ] || { echo "Este entorno no tiene bucket viejo que copiar (producción arranca vacío en la región nueva; los archivos de la VM se suben con scripts/migrate_files_to_gcs.py)."; exit 0; }
    have gcloud storage buckets describe "gs://$OLD_APP_BUCKET" || { echo "gs://$OLD_APP_BUCKET no existe: nada que copiar."; exit 0; }
    have gcloud storage buckets describe "gs://$APP_BUCKET" || { echo "Primero corre bootstrap.sh con REGION=$REGION (crea gs://$APP_BUCKET)." >&2; exit 1; }
    say "Copiando gs://$OLD_APP_BUCKET → gs://$APP_BUCKET (solo versiones vigentes; sin uploads/ temporales). Cobra tráfico entre regiones UNA vez (centavos por GB)."
    gcloud storage rsync --recursive --exclude '(^|.*/)uploads/.*' "$@" "gs://$OLD_APP_BUCKET" "gs://$APP_BUCKET"
    if [ "${1:-}" != "--dry-run" ]; then
      a="$(gcloud storage ls -r "gs://$OLD_APP_BUCKET/**" 2>/dev/null | grep -v '/uploads/' | grep -vc ':$' || true)"; b="$(gcloud storage ls -r "gs://$APP_BUCKET/**" 2>/dev/null | grep -vc ':$' || true)"
      echo "objetos (sin uploads/): viejo=$a nuevo=$b"; [ "$b" -ge "$a" ] && echo "OK: el bucket nuevo tiene todo" || { echo "FALTAN objetos en el nuevo: repite el copy" >&2; exit 1; }
    fi
    ;;

  verify)
    fail=0
    chk() { if "${@:2}" >/dev/null 2>&1; then echo "  OK    $1"; else echo "  FALTA $1"; fail=1; fi; }
    say "Región nueva ($REGION)"
    for s in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do chk "servicio $s" gcloud run services describe "$s" --region "$REGION"; done
    for j in "$JOB_MIGRATE" "$JOB_BULK" "$JOB_OPS"; do chk "Job $j" gcloud run jobs describe "$j" --region "$REGION"; done
    chk "cola $QUEUE" gcloud tasks queues describe "$QUEUE" --location "$REGION"
    chk "repositorio de imágenes $AR_REPO" gcloud artifacts repositories describe "$AR_REPO" --location "$REGION"
    chk "bucket gs://$APP_BUCKET" gcloud storage buckets describe "gs://$APP_BUCKET"
    [ "$GOLDEN_ENV" = production ] && chk "tarea $SCHEDULER_OPS" gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION"
    for path in health ready; do chk "GET $(run_url "$SVC_WEB")/$path" curl -fsS --max-time 60 "$(run_url "$SVC_WEB")/$path"; done
    [ -z "$FIREBASE_SITE" ] || chk "sitio público $PUBLIC_BASE_URL/health (las reglas de Firebase ya apuntan a $REGION)" curl -fsS --max-time 60 "$PUBLIC_BASE_URL/health"
    # El Job de operaciones debe estar en la región nueva Y el servicio web debe llamar a la cola nueva (variables calculadas por deploy.sh):
    got="$(gcloud run services describe "$SVC_WEB" --region "$REGION" --format 'value(spec.template.spec.containers[0].env)' 2>/dev/null | tr ';' '\n' | grep -c "locations/${REGION}/" || true)"
    [ "$got" -ge 1 ] && echo "  OK    las variables del servicio web apuntan a locations/$REGION" || { echo "  FALTA las variables del servicio web no apuntan a locations/$REGION (¿falta redesplegar?)"; fail=1; }
    [ "$fail" = 0 ] && echo -e "\nTodo listo para limpiar la región vieja." || { echo -e "\nFaltan cosas: NO limpies la región vieja todavía." >&2; exit 1; }
    ;;

  cleanup)
    say "Se borrará de $OLD_REGION (entorno $GOLDEN_ENV, proyecto $PROJECT_ID): servicios y Jobs golden-*${SUFFIX}, la cola $QUEUE, la tarea $SCHEDULER_OPS, el repositorio $AR_REPO${OLD_APP_BUCKET:+ y el bucket gs://$OLD_APP_BUCKET (con todas sus versiones)}."
    pending="$(gcloud tasks list --queue "$QUEUE" --location "$OLD_REGION" --format 'value(name)' 2>/dev/null | count)"
    if [ "$pending" != 0 ] && [ "${FORCE:-0}" != 1 ]; then
      echo "La cola vieja tiene $pending tarea(s) pendientes (llamarían a un servicio que se va a borrar). Espera a que se vacíe o FORCE=1: la tabla \`jobs\` de la base sigue siendo la fuente de verdad y el paso «sweep» del Job de ops en la región nueva las retoma." >&2; exit 1
    fi
    read -rp "Escribe la región vieja ($OLD_REGION) para confirmar: " typed
    [ "$typed" = "$OLD_REGION" ] || { echo "No coincide: no se borró nada."; exit 1; }
    [ "$GOLDEN_ENV" != production ] || { read -rp "ES PRODUCCIÓN. Escribe «produccion» para seguir: " p2; [ "$p2" = produccion ] || { echo "Cancelado."; exit 1; }; }
    del() { echo "  - $*"; "$@" --quiet || echo "    (no existía o ya estaba borrado)"; }
    gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$OLD_REGION" >/dev/null 2>&1 && del gcloud scheduler jobs delete "$SCHEDULER_OPS" --location "$OLD_REGION"
    for s in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do gcloud run services describe "$s" --region "$OLD_REGION" >/dev/null 2>&1 && del gcloud run services delete "$s" --region "$OLD_REGION"; done
    for j in "$JOB_MIGRATE" "$JOB_BULK" "$JOB_OPS"; do gcloud run jobs describe "$j" --region "$OLD_REGION" >/dev/null 2>&1 && del gcloud run jobs delete "$j" --region "$OLD_REGION"; done
    gcloud tasks queues describe "$QUEUE" --location "$OLD_REGION" >/dev/null 2>&1 && del gcloud tasks queues delete "$QUEUE" --location "$OLD_REGION"
    gcloud artifacts repositories describe "$AR_REPO" --location "$OLD_REGION" >/dev/null 2>&1 && del gcloud artifacts repositories delete "$AR_REPO" --location "$OLD_REGION"
    if [ -n "$OLD_APP_BUCKET" ] && gcloud storage buckets describe "gs://$OLD_APP_BUCKET" >/dev/null 2>&1; then
      read -rp "¿Borrar gs://$OLD_APP_BUCKET con todas sus versiones? Escribe el nombre del bucket: " bname
      [ "$bname" = "$OLD_APP_BUCKET" ] && gcloud storage rm --recursive --all-versions "gs://$OLD_APP_BUCKET" || echo "  bucket viejo conservado"
    fi
    echo -e "\nLimpio. Revisa en la consola de Cloud Run/Artifact Registry/Storage que no quede nada de $OLD_REGION, y en Facturación → Informes (agrupa por SKU) al día siguiente."
    ;;

  *) sed -n 2,10p "$0"; exit 2 ;;
esac
