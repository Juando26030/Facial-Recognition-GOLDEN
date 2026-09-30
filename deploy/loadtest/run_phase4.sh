#!/usr/bin/env bash
# Fase 4 (docs/15 «Prueba de carga distribuida»): generadores de carga como Cloud Run Jobs CONTRA STAGING. Lo corre Juan David en Cloud Shell (Claude Code no crea ni ejecuta
# recursos de nube). Todo con tope: tareas y tiempo máximos por Job, sin reintentos, y los Jobs se borran al final. El ORDEN COMPLETO de la corrida, con el valor esperado de
# cada verificación, está en docs/15 («D2.3 · Corrida completa»).
#
#   bash deploy/loadtest/run_phase4.sh quota              # antes de todo: dónde ver/subir la cuota de CPU de la región (ver docs/15, «CPU simultánea»)
#   bash deploy/loadtest/run_phase4.sh build              # construye y sube la imagen del generador (Artifact Registry de staging)
#   bash deploy/loadtest/run_phase4.sh seed               # siembra el evento LOAD-STG y su formulario sintéticos (5.000 personas, cupo 4.000); se puede repetir: no duplica nada
#   bash deploy/loadtest/run_phase4.sh reset-data         # deja en cero las inscripciones e ingresos de una corrida (evento, formulario y personas se quedan)
#   bash deploy/loadtest/run_phase4.sh limits-up          # sube PUBLIC_LIMIT_FACTOR (los generadores comparten IP real); limits-down lo DEVUELVE
#   bash deploy/loadtest/run_phase4.sh scale-up           # sube min/max de instancias de web, publico y biometria; GUARDA los valores originales; scale-down los restaura
#   bash deploy/loadtest/run_phase4.sh run small          # MODO PEQUEÑO (~5 %): valida toda la cadena en ~3 min antes de la corrida completa
#   bash deploy/loadtest/run_phase4.sh run                # corrida completa: formularios 10.000/5.000, cédula 200×30 min y facial, AL MISMO TIEMPO
#   bash deploy/loadtest/run_phase4.sh report <EJECUCION_forms> <EJECUCION_cedula> <EJECUCION_face>   # une los logs y compara con los criterios
#   bash deploy/loadtest/run_phase4.sh verify             # cupo, duplicados e ingresos en la base (solo cifras)
#   bash deploy/loadtest/run_phase4.sh cleanup            # borra SOLO los 3 Jobs del generador (no los datos: para eso purge-data)
#   bash deploy/loadtest/run_phase4.sh purge-data         # borra el evento LOAD-STG y TODOS sus datos sintéticos de la base de staging (pide confirmación)
#   (scale-down / limits-down: devolver lo tocado)
#
# Proyecto, región, repositorio de imágenes y nombres salen de deploy/gcp/config.sh staging (REGION o `gcloud config set run/region`).
# Variables: WEB_URL (por defecto la URL pública de staging de config.sh; DEBE ser exactamente una de las de staging: se aborta con cualquier otra), LOAD_EVENT_ID (por defecto,
# el del último LOAD_SEED en los logs), TASKS_FORMS/TASKS_CEDULA/TASKS_FACE (6/4/4 tareas de 1 vCPU), CEDULA_MIN (30), SCALE_WEB/SCALE_PUBLICO/SCALE_BIO («min max»: 2 10 / 2 10 / 3 10; SCALE_PUB sigue valiendo como alias; el máximo por defecto es 10, el de producción; para probar con menos, p. ej. SCALE_PUBLICO='2 6'), SCALE_FILE (dónde se guardan los originales).
set -euo pipefail
export FIREBASE_DEPLOY="${FIREBASE_DEPLOY:-1}"             # staging con Firebase (proyecto propio): PUBLIC_BASE_URL = https://<sitio>.web.app
# CANDADO: la lista de destinos permitidos se calcula SOLO desde proyecto, región y nombres de staging (config.sh). Lo que traiga el entorno de la terminal
# (PUBLIC_BASE_URL/FIREBASE_SITE de otra sesión —quizá de producción—, GOLDEN_ENV, buckets, PROJECT_ID) no puede ensancharla. Si el sitio de Firebase de staging NO se
# llama golden-staging-<número de proyecto>, indícalo explícitamente con LOAD_FIREBASE_SITE=<nombre> (nunca por una variable heredada).
unset PUBLIC_BASE_URL FIREBASE_SITE GOLDEN_ENV APP_BUCKET BACKUP_BUCKET PROJECT_ID STAGING_BRANCH_REF
[ -z "${LOAD_FIREBASE_SITE:-}" ] || export FIREBASE_SITE="$LOAD_FIREBASE_SITE"
# shellcheck source=/dev/null
source "$(dirname "$0")/../gcp/config.sh" staging          # PROJECT_ID, REGION, AR_REPO, JOB_OPS, SVC_*: nada fijo aquí
PROJECT="$PROJECT_ID"; CEDULA_MIN="${CEDULA_MIN:-30}"
AR="$REGION-docker.pkg.dev/$PROJECT/$AR_REPO"; IMAGE="$AR/loadgen:latest"; APP_IMAGE_JOB="$JOB_OPS"
JOB="golden-loadgen-staging"
SCALE_FILE="${SCALE_FILE:-$HOME/.golden_phase4_scale_${PROJECT}.txt}"
LIMITS_FACTOR="${LIMITS_FACTOR:-200}"          # PUBLIC_LIMIT_FACTOR que pone limits-up y que exige la comprobación previa de `run`
say() { echo -e "\n== $*"; }
LAST_T0=""
ops_job() {   # ejecuta el Job de ops con un paso de scripts.seed_load_staging y espera; anota la hora para leer SOLO lo que imprima esta ejecución
  LAST_T0="$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%SZ)"
  gcloud run jobs execute "$APP_IMAGE_JOB" --project "$PROJECT" --region "$REGION" --args="-m,scripts.seed_load_staging,$1" --wait
}
# Lee una línea marcada (LOAD_SEED, LOAD_VERIFY…) de Cloud Logging. Los logs tardan en aparecer: reintenta cada 10 s hasta 2 minutos; si no sale, dice cómo leerla a mano y falla.
log_line() {
  local filter="resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$APP_IMAGE_JOB\" AND textPayload:\"$1\"" out="" waited=0
  [ -z "$LAST_T0" ] || filter="$filter AND timestamp>=\"$LAST_T0\""
  while :; do
    out="$(gcloud logging read "$filter" --project "$PROJECT" --limit 1 --freshness 3d --format='value(textPayload)' 2>/dev/null || true)"
    [ -z "$out" ] || { echo "$out"; return 0; }
    [ "$waited" -lt "${LOG_WAIT_SECONDS:-120}" ] || break
    sleep 10; waited=$((waited + 10))
  done
  echo "No apareció la línea $1 en los logs tras ${waited} s (la ejecución SÍ terminó; Cloud Logging a veces tarda más). Léela a mano:" >&2
  echo "  gcloud logging read '$filter' --project $PROJECT --limit 1 --freshness 3d --format='value(textPayload)'" >&2
  echo "  o en la consola: Logging → Explorador de registros → texto «$1» (recurso: Job de Cloud Run $APP_IMAGE_JOB)." >&2
  return 1
}
# Únicos destinos permitidos: los hosts EXACTOS de staging que calcula config.sh (el generador vuelve a comprobarlo con LOAD_ALLOWED_HOSTS).
allowed_hosts() { { echo "$PUBLIC_BASE_URL"; run_url "$SVC_WEB"; run_url "$SVC_PUBLICO"; run_url "$SVC_BIOMETRIA"; } | sed 's#^https://##; s#/.*$##' | sort -u | paste -sd, -; }
# Instancias de Cloud Run (API v2: el mínimo es a nivel de SERVICIO, como lo mueve app/warmup.py; el máximo va en la plantilla y crea una revisión nueva).
svc_url() { echo "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/services/$1"; }
get_scale() {   # servicio → «min max»
  curl -fsS -H "Authorization: Bearer $(gcloud auth print-access-token)" "$(svc_url "$1")" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("scaling") or {}).get("minInstanceCount", 0), (d.get("template", {}).get("scaling") or {}).get("maxInstanceCount", 10))'
}
set_min() { curl -fsS -X PATCH -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
              "$(svc_url "$1")?updateMask=scaling.minInstanceCount" -d "{\"scaling\":{\"minInstanceCount\":$2}}" >/dev/null; }
set_max() { gcloud run services update "$1" --project "$PROJECT" --region "$REGION" --max-instances "$2" --quiet >/dev/null; }

# COMPROBACIÓN PREVIA de `run`: un despliegue de CI (`--env-vars-file` reemplaza TODAS las variables; `--max-instances` vuelve a 10) borra lo que puso limits-up/scale-up. Lee los tres
# servicios de staging y aborta, con el comando que lo arregla, si PUBLIC_LIMIT_FACTOR de publico no es $LIMITS_FACTOR o si algún máximo de instancias no es el de SCALE_*.
preflight() {
  local bad=0 pair svc max
  for pair in "$SVC_WEB:${SCALE_WEB:-2 10}" "$SVC_PUBLICO:${SCALE_PUBLICO:-${SCALE_PUB:-2 10}}" "$SVC_BIOMETRIA:${SCALE_BIO:-3 10}"; do
    svc="${pair%%:*}"; read -r _ max <<<"${pair#*:}"
    if [ "$svc" = "$SVC_PUBLICO" ]; then
      gcloud run services describe "$svc" --project "$PROJECT" --region "$REGION" --format=json | "${PYTHON3:-python3}" "$(dirname "$0")/preflight.py" "$svc" "$max" "$LIMITS_FACTOR" || bad=1
    else
      gcloud run services describe "$svc" --project "$PROJECT" --region "$REGION" --format=json | "${PYTHON3:-python3}" "$(dirname "$0")/preflight.py" "$svc" "$max" || bad=1
    fi
  done
  [ "$bad" = 0 ] || { echo "No se lanzó nada: arregla lo de arriba y repite «run» (PREFLIGHT_SKIP=1 lo omite a propósito, p. ej. para una línea base sin scale-up)." >&2; exit 1; }
}

case "${1:-}" in
  quota)
    echo "CPU simultánea máxima de toda la prueba (docs/15): servicios hasta 10 instancias (web 1 vCPU, publico 1, biometria 2 = hasta 40 vCPU) + generadores (6+4+4 tareas × 1 vCPU = 14) + Job de ops 1."
    echo "Cuota de Cloud Run («Total CPU allocation» por región); para confirmarla:"
    echo "  https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT&service=run.googleapis.com   (región: $REGION)"
    echo "Dato de Juan David (2026-09-29): us-east4 tiene 200 vCPU y ~400 GiB; uso actual 3,75 vCPU y 4 GB. La prueba pide hasta 55 vCPU y ~54 GiB en el peor caso (docs/15): cabe con margen." ;;
  build)
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
    docker build -f deploy/loadtest/Dockerfile -t "$IMAGE" . || { echo "FALLÓ el build del generador: no sigas con seed/run." >&2; exit 1; }
    docker push "$IMAGE" || { echo "FALLÓ el push de la imagen: no sigas con seed/run." >&2; exit 1; } ;;
  seed)
    say "Sembrando (Job existente $APP_IMAGE_JOB, con DEPLOY_ENV=staging)"
    ops_job "--people,5000,--capacity,4000"
    line="$(log_line LOAD_SEED)" || { echo "El seed terminó bien; solo falta leer event_id. Cuando aparezca la línea, usa LOAD_EVENT_ID=<id> en «run» (o corre «verify», que también lo imprime)." >&2; exit 1; }
    echo "LOAD_SEED (event_id y form_slug): $line" ;;
  reset-data)
    say "Dejando en cero inscripciones e ingresos de LOAD-STG"; ops_job "--reset-runs"; log_line LOAD_RESET ;;
  purge-data)
    say "Se borrará el evento LOAD-STG y TODOS sus datos sintéticos (personas, formulario, inscripciones, ingresos, cuenta carga_dig, cliente carga-staging) de la base de STAGING."
    read -rp "Escribe LOAD-STG para confirmar: " ok; [ "$ok" = "LOAD-STG" ] || { echo "Cancelado."; exit 1; }
    ops_job "--delete-all"; log_line LOAD_DELETED ;;
  run)
    MODE="${2:-full}"
    WEB_URL="${WEB_URL:-$PUBLIC_BASE_URL}"
    host="$(echo "$WEB_URL" | sed 's#^https://##; s#/.*$##')"
    case ",$(allowed_hosts)," in *",$host,"*) ;; *) echo "WEB_URL=$WEB_URL NO es un destino de staging permitido. Permitidos: $(allowed_hosts | tr ',' ' ')" >&2; exit 1;; esac
    if [ "${PREFLIGHT_SKIP:-0}" = 1 ]; then echo "AVISO: PREFLIGHT_SKIP=1, no se comprobaron límites ni instancias." >&2; else preflight; fi
    LOAD_EVENT_ID="${LOAD_EVENT_ID:-$(log_line LOAD_SEED | sed -n 's/.*"event_id": *\([0-9]*\).*/\1/p')}"
    [ -n "$LOAD_EVENT_ID" ] || { echo "Define LOAD_EVENT_ID (de la línea LOAD_SEED de los logs; corre «seed» primero)." >&2; exit 1; }
    if [ "$MODE" = small ]; then     # ~5 % de la escala: 1 tarea por escenario, 500 aperturas (~250 envíos), 10 estaciones de cédula 2 min, 3 usuarios faciales 1 min
      TF=1; TC=1; TX=1; FU=500; FR=9; FD=180; CU=10; CR=5; CD=120; XU=3; XR=3; XD=60
    else
      TF="${TASKS_FORMS:-6}"; TC="${TASKS_CEDULA:-4}"; TX="${TASKS_FACE:-4}"; FU=10000; FR=170; FD=360; CU=200; CR=20; CD=$(( CEDULA_MIN * 60 )); XU=60; XR=10; XD=300
    fi
    echo "Modo: $MODE · destino: $WEB_URL · evento $LOAD_EVENT_ID · región $REGION · tareas forms/cédula/facial: $TF/$TC/$TX"
    mk() {  # nombre escenario usuarios tasa duración tareas
      # Variables en un ARCHIVO (--env-vars-file), no en --set-env-vars: LOAD_ALLOWED_HOSTS lleva comas y gcloud las tomaría como separador de variables.
      local envfile; envfile="$(mktemp)"
      "${PYTHON3:-python3}" "$(dirname "$0")/job_env.py" "$envfile" "LOAD_SCENARIO=$2" "LOAD_HOST=$WEB_URL" "LOAD_ALLOWED_HOSTS=$(allowed_hosts)" "LOAD_USERS=$3" "LOAD_RATE=$4" \
        "LOAD_DURATION=$5" "LOAD_EVENT_ID=$LOAD_EVENT_ID" "LOAD_FORM_SLUG=carga" "LOAD_PEOPLE=5000" "LOAD_THINK_MAX=${LOAD_THINK_MAX:-30}" \
        || { rm -f "$envfile"; return 1; }
      gcloud run jobs deploy "$JOB-$1" --project "$PROJECT" --region "$REGION" --image "$IMAGE" --tasks "$6" --parallelism "$6" --max-retries 0 \
        --task-timeout "$(( $5 + 240 ))s" --cpu 1 --memory 1Gi \
        --set-secrets "OPS_TOKEN=$(secret_name ops-token):latest" \
        --env-vars-file "$envfile" --quiet || { rm -f "$envfile"; return 1; }
      rm -f "$envfile"
    }
    ONLY="${ONLY:-forms,cedula,face}"           # p. ej. ONLY=forms,cedula para el simulacro de Neon
    has() { case ",$ONLY," in *",$1,"*) return 0;; *) return 1;; esac; }
    if has forms;  then mk forms  forms  "$FU" "$FR" "$FD" "$TF" || { echo "FALLÓ el despliegue del Job forms: no se lanzó nada." >&2; exit 1; }; fi
    if has cedula; then mk cedula cedula "$CU" "$CR" "$CD" "$TC" || { echo "FALLÓ el despliegue del Job cedula: no se lanzó nada." >&2; exit 1; }; fi
    if has face;   then mk face   face   "$XU" "$XR" "$XD" "$TX" || { echo "FALLÓ el despliegue del Job face: no se lanzó nada." >&2; exit 1; }; fi
    say "Lanzando ($ONLY) a la vez, sin --wait; sigue con «report» cuando terminen"
    for s in forms cedula face; do
      has "$s" && echo "$s: $(gcloud run jobs execute "$JOB-$s" --project "$PROJECT" --region "$REGION" --async --format='value(metadata.name)')"
    done
    echo "Anota los nombres de ejecución de arriba (se usan en «report»; pon - en el escenario que no corriste)." ;;
  report)
    shift; [ "$#" -eq 3 ] || { echo "Uso: report <exec_forms|-> <exec_cedula|-> <exec_face|->"; exit 1; }
    files=(); i=0; for s in forms cedula face; do
      i=$((i+1)); exec_name="${!i}"
      [ "$exec_name" != "-" ] || continue                   # «-» = ese escenario no se corrió
      files+=("/tmp/loadgen_$s.json")
      gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB-$s\" AND labels.\"run.googleapis.com/execution_name\"=\"$exec_name\" AND textPayload:\"LOADGEN_RESULT\"" \
        --project "$PROJECT" --format=json --limit 1000 > "/tmp/loadgen_$s.json"
    done
    python3 scripts/loadgen_report.py "${files[@]}" ;;
  verify)
    ops_job "--verify"; line="$(log_line LOAD_VERIFY)" || exit 1; echo "LOAD_VERIFY: $line"
    echo "Esperado tras la corrida completa: oversold=0, duplicate_persons=0, duplicate_sids=0, confirmed_submissions=capacity (4000: hubo ~5.000 intentos), access_logs_in_event ≥ las respuestas 200 de «POST checkin-cedula» del informe." ;;
  limits-up|limits-down)   # los generadores están en Google Cloud y la app ya no cree su X-Forwarded-For: sube el límite por IP de los formularios SOLO durante la prueba y devuélvelo
    if [ "$1" = limits-up ]; then
      gcloud run services update "$SVC_PUBLICO" --project "$PROJECT" --region "$REGION" --update-env-vars PUBLIC_LIMIT_FACTOR=$LIMITS_FACTOR --quiet
    else
      gcloud run services update "$SVC_PUBLICO" --project "$PROJECT" --region "$REGION" --remove-env-vars PUBLIC_LIMIT_FACTOR --quiet   # vuelve al valor de common.yaml (1)
    fi ;;
  scale-up)
    [ ! -e "$SCALE_FILE" ] || { echo "scale-up SE NIEGA: ya hay valores ORIGINALES guardados en $SCALE_FILE. Si se repitiera, reescribiría los originales con los valores YA subidos y scale-down restauraría lo equivocado. Corre primero: bash deploy/loadtest/run_phase4.sh scale-down (si ya restauraste a mano, borra ese archivo)." >&2; exit 1; }
    for pair in "$SVC_WEB:${SCALE_WEB:-2 10}" "$SVC_PUBLICO:${SCALE_PUBLICO:-${SCALE_PUB:-2 10}}" "$SVC_BIOMETRIA:${SCALE_BIO:-3 10}"; do
      svc="${pair%%:*}"; read -r want_min want_max <<<"${pair#*:}"
      read -r cur_min cur_max <<<"$(get_scale "$svc")"
      echo "$svc $cur_min $cur_max" >> "$SCALE_FILE"                   # ORIGINALES (mínimo de servicio, máximo de plantilla)
      echo "  $svc: min $cur_min → $want_min, max $cur_max → $want_max"
      set_min "$svc" "$want_min"; set_max "$svc" "$want_max"
    done
    echo "Originales guardados en $SCALE_FILE. Al terminar: bash deploy/loadtest/run_phase4.sh scale-down" ;;
  scale-down)
    [ -e "$SCALE_FILE" ] || { echo "No hay $SCALE_FILE: nada que restaurar (¿ya hiciste scale-down?)." >&2; exit 1; }
    while read -r svc orig_min orig_max; do
      echo "  $svc: restaurando min $orig_min, max $orig_max"
      set_max "$svc" "$orig_max"; set_min "$svc" "$orig_min"
    done < "$SCALE_FILE"
    rm -f "$SCALE_FILE"; echo "Restaurado." ;;
  cleanup)
    for s in forms cedula face; do gcloud run jobs delete "$JOB-$s" --project "$PROJECT" --region "$REGION" --quiet || true; done
    echo "Borrados los 3 Jobs del generador en $REGION. NO se tocó: los datos LOAD-STG (purge-data), la imagen loadgen en Artifact Registry, los logs, ni los límites/instancias (limits-down, scale-down)." ;;
  *) sed -n 2,26p "$0"; exit 1 ;;
esac
