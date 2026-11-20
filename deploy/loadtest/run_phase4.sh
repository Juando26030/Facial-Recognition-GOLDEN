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
#   LOAD_PEOPLE=40000 bash deploy/loadtest/run_phase4.sh seed   # (para «rush») evento sintético de 40.000 personas
#   LOAD_PEOPLE=40000 bash deploy/loadtest/run_phase4.sh run rush   # 40.000 escaneos de cédula SIN pausa (400 estaciones; 20 % sin cédula conocida → búsqueda por nombre)
#   bash deploy/loadtest/run_phase4.sh report-rush <EJECUCION_rush>
#   bash deploy/loadtest/run_phase4.sh report <EJECUCION_forms> <EJECUCION_cedula> <EJECUCION_face>   # une los logs y compara con los criterios
#   bash deploy/loadtest/run_phase4.sh verify             # cupo, duplicados e ingresos en la base (solo cifras)
#   bash deploy/loadtest/run_phase4.sh cleanup            # borra SOLO los 3 Jobs del generador (no los datos: para eso purge-data)
#   bash deploy/loadtest/run_phase4.sh purge-data         # borra el evento LOAD-STG y TODOS sus datos sintéticos de la base de staging (pide confirmación)
#   (scale-down / limits-down: devolver lo tocado)
#
# PRODUCCIÓN (solo con orden expresa; ver docs/PRUEBA_CARGA_PRODUCCION.md): LOAD_TARGET=production LOAD_PROD_CONFIRM=<ID del proyecto> SCALE_WEB='<mín> <máx>' bash deploy/loadtest/run_phase4.sh <paso>
#   pasos permitidos: build seed run rush report-rush verify reset-data purge-data limits-up limits-down scale-up scale-down cleanup (solo el servicio web, solo «rush»).
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
# DESTINO. Por defecto STAGING. PRODUCCIÓN (19-nov-2026, orden expresa de Juan David: probar 40.000 escaneos en un evento sintético y borrarlo después) solo con LOAD_TARGET=production
# Y LOAD_PROD_CONFIRM=<ID exacto del proyecto de producción>, y entonces SOLO: el escenario «rush», el servicio WEB por su URL de Cloud Run (nunca app.golden-eventos.com ni Cloudflare),
# el evento sintético LOAD-STG (la siembra se niega si hay un evento real en proceso) y el apagado temporal de los dos controles de ingreso del servicio web (limits-up / limits-down).
TARGET="${LOAD_TARGET:-staging}"
case "$TARGET" in staging|production) ;; *) echo "LOAD_TARGET debe ser staging o production (recibí '$TARGET')." >&2; exit 2;; esac
# shellcheck source=/dev/null
source "$(dirname "$0")/../gcp/config.sh" "$TARGET"          # PROJECT_ID, REGION, AR_REPO, JOB_OPS, SVC_*: nada fijo aquí
PROJECT="$PROJECT_ID"; CEDULA_MIN="${CEDULA_MIN:-30}"
if [ "$TARGET" = production ]; then
  case "$PROJECT" in *staging*) echo "LOAD_TARGET=production pero el proyecto activo es '$PROJECT' (de staging). export CLOUDSDK_CORE_PROJECT=<proyecto de producción> y repite." >&2; exit 2;; esac
  [ "${LOAD_PROD_CONFIRM:-}" = "$PROJECT" ] || { echo "PRODUCCIÓN ($PROJECT): para continuar escribe el ID exacto del proyecto: LOAD_PROD_CONFIRM=$PROJECT (junto al comando). No se hizo nada." >&2; exit 2; }
  case "${1:-}" in
    build|seed|info|reset-data|purge-data|verify|limits-up|limits-down|scale-up|scale-down|run|report-rush|cleanup) ;;
    *) echo "En producción solo existen: build seed info run rush report-rush verify reset-data purge-data limits-up limits-down scale-up scale-down cleanup (no '${1:-}')." >&2; exit 2;;
  esac
  [ "${1:-}" != run ] || [ "${2:-}" = rush ] || { echo "En producción «run» solo admite «rush»." >&2; exit 2; }
fi
AR="$REGION-docker.pkg.dev/$PROJECT/$AR_REPO"; IMAGE="$AR/loadgen:latest"; APP_IMAGE_JOB="$JOB_OPS"
if [ "$TARGET" = production ]; then JOB="golden-loadgen-prod"; else JOB="golden-loadgen-staging"; fi
SCALE_FILE="${SCALE_FILE:-$HOME/.golden_phase4_scale_${PROJECT}.txt}"
LIMITS_FACTOR="${LIMITS_FACTOR:-200}"          # PUBLIC_LIMIT_FACTOR que pone limits-up y que exige la comprobación previa de `run`
say() { echo -e "\n== $*"; }
LAST_T0=""
ops_job() {   # ejecuta el Job de ops con un paso de scripts.seed_load_staging y espera; anota la hora para leer SOLO lo que imprima esta ejecución
  LAST_T0="$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%SZ)"
  local extra=""
  if [ "$TARGET" = production ]; then extra=",--production-ok,$PROJECT"; [ "${LOAD_ALLOW_LIVE:-0}" != 1 ] || extra="$extra,--allow-live-events"; fi
  if [ -n "${LOAD_TENANT:-}" ]; then   # la prueba vive en un cliente EXISTENTE (id del cliente; mira `info`): no se crea ni se borra el cliente, solo lo sintético
    [[ "$LOAD_TENANT" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "LOAD_TENANT='$LOAD_TENANT' no es un id válido." >&2; return 1; }
    extra="$extra,--tenant,$LOAD_TENANT"
  fi
  gcloud run jobs execute "$APP_IMAGE_JOB" --project "$PROJECT" --region "$REGION" --args="-m,scripts.seed_load_staging,$1$extra" --wait
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
allowed_hosts() {
  if [ "$TARGET" = production ]; then run_url "$SVC_WEB" | sed 's#^https://##; s#/.*$##'; return; fi      # producción: SOLO el servicio web por su URL de Cloud Run
  { echo "$PUBLIC_BASE_URL"; run_url "$SVC_WEB"; run_url "$SVC_PUBLICO"; run_url "$SVC_BIOMETRIA"; } | sed 's#^https://##; s#/.*$##' | sort -u | paste -sd, -
}
# Servicios que tocan scale-up/down, limits y la comprobación previa: en staging los tres; en producción SOLO el web (rush solo usa el web) y con SCALE_WEB explícito.
scale_pairs() {
  if [ "$TARGET" = production ]; then
    [ -n "${SCALE_WEB:-}" ] || { echo "En producción define SCALE_WEB='<mín> <máx>' (p. ej. SCALE_WEB='4 20'): no se toca el escalado de producción sin un valor tuyo." >&2; return 1; }
    echo "$SVC_WEB:$SCALE_WEB"
  else
    echo "$SVC_WEB:${SCALE_WEB:-2 10}"; echo "$SVC_PUBLICO:${SCALE_PUBLICO:-${SCALE_PUB:-2 10}}"; echo "$SVC_BIOMETRIA:${SCALE_BIO:-3 10}"
  fi
}
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
  while read -r pair; do
    svc="${pair%%:*}"; read -r _ max <<<"${pair#*:}"
    if [ "$svc" = "$SVC_PUBLICO" ]; then
      gcloud run services describe "$svc" --project "$PROJECT" --region "$REGION" --format=json | "${PYTHON3:-python3}" "$(dirname "$0")/preflight.py" "$svc" "$max" "$LIMITS_FACTOR" || bad=1
    else
      gcloud run services describe "$svc" --project "$PROJECT" --region "$REGION" --format=json | "${PYTHON3:-python3}" "$(dirname "$0")/preflight.py" "$svc" "$max" || bad=1
    fi
  done < <(scale_pairs)
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
    say "Sembrando (Job existente $APP_IMAGE_JOB, destino: $TARGET)"
    ops_job "--people,${LOAD_PEOPLE:-5000},--capacity,4000"
    line="$(log_line LOAD_SEED)" || { echo "El seed terminó bien; solo falta leer event_id. Cuando aparezca la línea, usa LOAD_EVENT_ID=<id> en «run» (o corre «verify», que también lo imprime)." >&2; exit 1; }
    echo "LOAD_SEED (event_id y form_slug): $line" ;;
  info)   # SOLO LECTURA: clientes llamados «prueba» y eventos reales en proceso (ver scripts/seed_load_staging.py --info)
    say "Consultando (solo lectura) clientes «prueba» y eventos en proceso"; ops_job "--info"; log_line LOAD_INFO ;;
  reset-data)
    say "Dejando en cero inscripciones e ingresos de LOAD-STG"; ops_job "--reset-runs"; log_line LOAD_RESET ;;
  purge-data)
    say "Se borrará el evento LOAD-STG y TODOS sus datos sintéticos (personas, formulario, inscripciones, ingresos, cuenta carga_dig, cliente carga-staging) de la base de $TARGET ($PROJECT)."
    read -rp "Escribe LOAD-STG para confirmar: " ok; [ "$ok" = "LOAD-STG" ] || { echo "Cancelado."; exit 1; }
    ops_job "--delete-all"; log_line LOAD_DELETED ;;
  run)
    MODE="${2:-full}"
    if [ "$TARGET" = production ]; then WEB_URL="${WEB_URL:-$(run_url "$SVC_WEB")}"; else WEB_URL="${WEB_URL:-$PUBLIC_BASE_URL}"; fi
    SUBMIT_RATIO="${LOAD_SUBMIT_RATIO:-0.5}"     # proporción de los que abren el formulario que además envían (0.5 = ~5.000 envíos de 10.000; 1 = 10.000 envíos)
    QUOTES="${LOAD_QUOTES:-0}"                   # cotizaciones por usuario al formulario con pago (0 = ninguna; ejemplo: LOAD_QUOTES=5)
    [[ "$QUOTES" =~ ^[0-9]+$ && "$QUOTES" -le 50 ]] || { echo "LOAD_QUOTES=$QUOTES no es válido: un entero entre 0 y 50. No se lanzó nada." >&2; exit 1; }
    [[ "$SUBMIT_RATIO" =~ ^(0(\.[0-9]+)?|1(\.0+)?)$ ]] || { echo "LOAD_SUBMIT_RATIO=$SUBMIT_RATIO no es válido: un número entre 0 y 1 (0.5 o 1). No se lanzó nada." >&2; exit 1; }
    host="$(echo "$WEB_URL" | sed 's#^https://##; s#/.*$##')"
    case ",$(allowed_hosts)," in *",$host,"*) ;; *) echo "WEB_URL=$WEB_URL NO es un destino permitido ($TARGET). Permitidos: $(allowed_hosts | tr ',' ' ')" >&2; exit 1;; esac
    if [ "${PREFLIGHT_SKIP:-0}" = 1 ]; then echo "AVISO: PREFLIGHT_SKIP=1, no se comprobaron límites ni instancias." >&2; else preflight; fi
    LOAD_EVENT_ID="${LOAD_EVENT_ID:-$(log_line LOAD_SEED | sed -n 's/.*"event_id": *\([0-9]*\).*/\1/p')}"
    [ -n "$LOAD_EVENT_ID" ] || { echo "Define LOAD_EVENT_ID (de la línea LOAD_SEED de los logs; corre «seed» primero)." >&2; exit 1; }
    if [ "$MODE" = rush ]; then     # 40.000 escaneos de cédula lo más rápido posible: RUSH_STATIONS estaciones sin pausa, repartidas en TASKS_RUSH tareas (ver CedulaRush en tests/load/locustfile.py)
      ONLY=rush; TR="${TASKS_RUSH:-4}"; RU="${RUSH_STATIONS:-400}"; RR=40; RD="${RUSH_MAX_SECONDS:-1500}"; TF=0; TC=0; TX=0
    elif [ "$MODE" = small ]; then     # ~5 % de la escala: 1 tarea por escenario, 500 aperturas (~250 envíos), 10 estaciones de cédula 2 min, 3 usuarios faciales 1 min
      TF=1; TC=1; TX=1; FU=500; FR=9; FD=180; CU=10; CR=5; CD=120; XU=3; XR=3; XD=60
    else
      TF="${TASKS_FORMS:-6}"; TC="${TASKS_CEDULA:-4}"; TX="${TASKS_FACE:-4}"; FU=10000; FR=170; FD=360; CU=200; CR=20; CD=$(( CEDULA_MIN * 60 )); XU=60; XR=10; XD=300
    fi
    echo "Modo: $MODE · envían el $("${PYTHON3:-python3}" -c "print(round(100 * $SUBMIT_RATIO))") % de quienes abren · destino: $WEB_URL · evento $LOAD_EVENT_ID · región $REGION · tareas forms/cédula/facial: $TF/$TC/$TX"
    mk() {  # nombre escenario usuarios tasa duración tareas
      # Variables en un ARCHIVO (--env-vars-file), no en --set-env-vars: LOAD_ALLOWED_HOSTS lleva comas y gcloud las tomaría como separador de variables.
      local envfile; envfile="$(mktemp)"
      "${PYTHON3:-python3}" "$(dirname "$0")/job_env.py" "$envfile" "LOAD_SCENARIO=$2" "LOAD_TARGET=$TARGET" "LOAD_HOST=$WEB_URL" "LOAD_ALLOWED_HOSTS=$(allowed_hosts)" "LOAD_USERS=$3" "LOAD_RATE=$4" \
        "LOAD_DURATION=$5" "LOAD_EVENT_ID=$LOAD_EVENT_ID" "LOAD_FORM_SLUG=carga" "LOAD_PEOPLE=${LOAD_PEOPLE:-5000}" "LOAD_SCANS=${LOAD_SCANS:-40000}" "LOAD_THINK_MAX=${LOAD_THINK_MAX:-30}" "LOAD_SUBMIT_RATIO=$SUBMIT_RATIO" "LOAD_QUOTES=$QUOTES" \
        || { rm -f "$envfile"; return 1; }
      local sa=(); [ "$TARGET" != production ] || sa=(--service-account "$SA_APP@$PROJECT.iam.gserviceaccount.com")   # en producción la cuenta por defecto no lee el secreto del token: se usa la de la app (la misma de los servicios)
      gcloud run jobs deploy "$JOB-$1" --project "$PROJECT" --region "$REGION" --image "$IMAGE" --tasks "$6" --parallelism "$6" --max-retries 0 "${sa[@]}" \
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
    if has rush;   then mk rush   rush   "$RU" "$RR" "$RD" "$TR" || { echo "FALLÓ el despliegue del Job rush: no se lanzó nada." >&2; exit 1; }; fi
    say "Lanzando ($ONLY) a la vez, sin --wait; sigue con «report» cuando terminen"
    for s in forms cedula face rush; do
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
  report-rush)
    [ "$#" -eq 2 ] || { echo "Uso: report-rush <exec_rush>"; exit 1; }
    gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB-rush\" AND labels.\"run.googleapis.com/execution_name\"=\"$2\" AND textPayload:\"LOADGEN_RESULT\"" \
      --project "$PROJECT" --format=json --limit 1000 > /tmp/loadgen_rush.json
    python3 scripts/loadgen_report.py /tmp/loadgen_rush.json ;;
  verify)
    ops_job "--verify"; line="$(log_line LOAD_VERIFY)" || exit 1; echo "LOAD_VERIFY: $line"
    echo "Esperado tras la corrida completa: oversold=0, duplicate_persons=0, duplicate_sids=0, confirmed_submissions=capacity (4000: hubo ~5.000 intentos), access_logs_in_event ≥ las respuestas 200 de «POST checkin-cedula» del informe." ;;
  limits-up|limits-down)   # los generadores están en Google Cloud y la app ya no cree su X-Forwarded-For: sube el límite por IP de los formularios SOLO durante la prueba y devuélvelo
    if [ "$TARGET" = production ]; then
      # PRODUCCIÓN: solo el servicio WEB (rush no usa el público). Apaga durante la prueba los dos controles que, con la cuenta de carga (digitador), dejan sin sesión a los generadores:
      # la aprobación de ingreso del coordinador (DIGITADOR_LOGIN_CONTROL=0) y la sesión única (SINGLE_SESSION=0). limits-down los QUITA (vuelve a lo normal; un despliegue también los borra).
      # Si alguna de las dos ya está puesta en el servicio, se niega: limits-down la borraría y cambiaría lo que alguien fijó a propósito.
      if [ "$1" = limits-up ]; then
        gcloud run services describe "$SVC_WEB" --project "$PROJECT" --region "$REGION" --format=json | python3 -c '
import json, sys
svc = json.load(sys.stdin)
cs = ((svc.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers") or (svc.get("template") or {}).get("containers") or [{}]
have = {e.get("name") for e in (cs[0].get("env") or [])} & {"DIGITADOR_LOGIN_CONTROL", "SINGLE_SESSION"}
if have:
    sys.exit("limits-up SE NIEGA en producción: el servicio web ya tiene " + ", ".join(sorted(have)) + " puesta(s); limits-down la borraría. Revísalo antes (no se cambió nada).")
' || exit 1
        gcloud run services update "$SVC_WEB" --project "$PROJECT" --region "$REGION" --update-env-vars DIGITADOR_LOGIN_CONTROL=0,SINGLE_SESSION=0 --quiet
        echo "PRODUCCIÓN: ingreso controlado y sesión única APAGADOS en $SVC_WEB. Al terminar: limits-down (obligatorio)."
      else
        gcloud run services update "$SVC_WEB" --project "$PROJECT" --region "$REGION" --remove-env-vars DIGITADOR_LOGIN_CONTROL,SINGLE_SESSION --quiet
        echo "PRODUCCIÓN: controles de ingreso DEVUELTOS en $SVC_WEB."
      fi
    elif [ "$1" = limits-up ]; then
      gcloud run services update "$SVC_PUBLICO" --project "$PROJECT" --region "$REGION" --update-env-vars PUBLIC_LIMIT_FACTOR=$LIMITS_FACTOR --quiet
      # La cuenta de carga es «digitador»: con el evento en proceso, el ingreso queda esperando que un coordinador lo apruebe (app/login_control.py) y nunca hay sesión (401 «No autenticado»).
      # También SINGLE_SESSION=0: las 4 tareas del generador entran con la misma cuenta y cada login expulsaría al anterior (401 «session_replaced»).
      # Se apaga SOLO en el servicio web de staging mientras dura la prueba (limits-down lo devuelve; un despliegue también lo borra).
      gcloud run services update "$SVC_WEB" --project "$PROJECT" --region "$REGION" --update-env-vars DIGITADOR_LOGIN_CONTROL=0,SINGLE_SESSION=0 --quiet
    else
      gcloud run services update "$SVC_PUBLICO" --project "$PROJECT" --region "$REGION" --remove-env-vars PUBLIC_LIMIT_FACTOR --quiet   # vuelve al valor de common.yaml (1)
      gcloud run services update "$SVC_WEB" --project "$PROJECT" --region "$REGION" --remove-env-vars DIGITADOR_LOGIN_CONTROL,SINGLE_SESSION --quiet   # vuelve al ingreso controlado
    fi ;;
  scale-up)
    [ ! -e "$SCALE_FILE" ] || { echo "scale-up SE NIEGA: ya hay valores ORIGINALES guardados en $SCALE_FILE. Si se repitiera, reescribiría los originales con los valores YA subidos y scale-down restauraría lo equivocado. Corre primero: bash deploy/loadtest/run_phase4.sh scale-down (si ya restauraste a mano, borra ese archivo)." >&2; exit 1; }
    pairs="$(scale_pairs)" || exit 1
    while read -r pair; do
      svc="${pair%%:*}"; read -r want_min want_max <<<"${pair#*:}"
      read -r cur_min cur_max <<<"$(get_scale "$svc")"
      echo "$svc $cur_min $cur_max" >> "$SCALE_FILE"                   # ORIGINALES (mínimo de servicio, máximo de plantilla)
      echo "  $svc: min $cur_min → $want_min, max $cur_max → $want_max"
      set_min "$svc" "$want_min"; set_max "$svc" "$want_max"
    done <<<"$pairs"
    echo "Originales guardados en $SCALE_FILE. Al terminar: bash deploy/loadtest/run_phase4.sh scale-down" ;;
  scale-down)
    [ -e "$SCALE_FILE" ] || { echo "No hay $SCALE_FILE: nada que restaurar (¿ya hiciste scale-down?)." >&2; exit 1; }
    while read -r svc orig_min orig_max; do
      echo "  $svc: restaurando min $orig_min, max $orig_max"
      set_max "$svc" "$orig_max"; set_min "$svc" "$orig_min"
    done < "$SCALE_FILE"
    rm -f "$SCALE_FILE"; echo "Restaurado." ;;
  cleanup)
    for s in forms cedula face rush; do gcloud run jobs delete "$JOB-$s" --project "$PROJECT" --region "$REGION" --quiet || true; done
    echo "Borrados los Jobs del generador en $REGION. NO se tocó: los datos LOAD-STG (purge-data), la imagen loadgen en Artifact Registry, los logs, ni los límites/instancias (limits-down, scale-down)." ;;
  *) sed -n 2,26p "$0"; exit 1 ;;
esac
