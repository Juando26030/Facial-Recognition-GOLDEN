#!/usr/bin/env bash
# Despliega una imagen en un entorno: migraciones (Job) → 3 servicios → Jobs de carga masiva y de operaciones → permisos entre ellos.
# Lo usan el workflow de GitHub Actions (.github/workflows/cloudrun.yml) y, una sola vez con --placeholder, bootstrap.sh.
#
#   deploy/gcp/deploy.sh staging    <imagen>        # p. ej. <región>-docker.pkg.dev/<proyecto>/golden/app:<commit>
#   deploy/gcp/deploy.sh production <imagen>        # respeta el congelamiento (/api/ops/deploy-allowed); FORCE=1 lo salta
#   deploy/gcp/deploy.sh staging --placeholder      # crea todo con la imagen «hello» de Google (bootstrap, antes de la primera imagen)
#
# Qué NO toca: las instancias mínimas de cada servicio (las maneja el precalentamiento; un despliegue no las devuelve a 0), los
# secretos (solo los referencia), el programador ni NINGÚN permiso: la cuenta de GitHub Actions solo tiene run.developer sobre los
# servicios y Jobs de su entorno, así que aquí no se crea nada nuevo ni se cambian políticas (eso es de bootstrap.sh, con el dueño). Vuelta atrás: `gcloud run services update-traffic <svc> --to-revisions
# <revisión-anterior>=100` (Cloud Run guarda las revisiones) — ver docs/15_MIGRACION.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh "${1:-}"
IMAGE="${2:?Falta la imagen (o --placeholder)}"
PLACEHOLDER=0
if [ "$IMAGE" = "--placeholder" ]; then IMAGE="us-docker.pkg.dev/cloudrun/container/hello"; PLACEHOLDER=1; fi
WEB_URL="$(run_url "$SVC_WEB")"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
say() { echo -e "\n== $*"; }

# ---------------------------------------------------------------- congelamiento de despliegues (solo producción)
if [ "$PLACEHOLDER" = 0 ] && [ "$GOLDEN_ENV" = production ] && [ "${FORCE:-0}" != 1 ] \
   && gcloud run services describe "$SVC_WEB" --region "$REGION" >/dev/null 2>&1; then
  say "¿Se puede desplegar? (${WEB_URL}/api/ops/deploy-allowed)"
  TOKEN="$(gcloud secrets versions access latest --secret "$(secret_name ops-token)")"
  ANSWER="$(curl -fsS --max-time 30 -H "X-Ops-Token: ${TOKEN}" "${WEB_URL}/api/ops/deploy-allowed")"
  echo "$ANSWER"
  if ! echo "$ANSWER" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["allowed"] else 1)'; then
    echo "CONGELADO: hay un evento en curso o una apertura cercana. Despliega después, o con FORCE=1 si es una emergencia." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- todo debe existir ya (lo crea bootstrap.sh con la imagen de relleno)
if [ "$PLACEHOLDER" = 0 ]; then
  for svc in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do
    gcloud run services describe "$svc" --region "$REGION" >/dev/null 2>&1 || { echo "No existe $svc: corre deploy/gcp/bootstrap.sh $GOLDEN_ENV." >&2; exit 1; }
  done
fi

# ---------------------------------------------------------------- secretos que existen → --set-secrets (se revisa cada uno, sin listar el proyecto)
secrets_flag() {   # $1 = lista «nombre:VARIABLE[*]»; los de * son obligatorios
  local out="" pair name var required s
  for pair in $1; do
    name="${pair%%:*}"; var="${pair#*:}"; required=0
    if [ "${var%\*}" != "$var" ]; then required=1; var="${var%\*}"; fi
    s="$(secret_name "$name")"
    if gcloud secrets describe "$s" >/dev/null 2>&1; then out+="${var}=${s}:latest,"
    elif [ "$required" = 1 ] && [ "$PLACEHOLDER" = 0 ]; then echo "Falta el secreto obligatorio ${s} (corre bootstrap.sh)." >&2; exit 1
    fi
  done
  echo "${out%,}"
}
APP_SECRET_FLAGS="$(secrets_flag "$APP_SECRETS")"
OPS_SECRET_FLAGS="$(secrets_flag "$APP_SECRETS neon-project-id:NEON_PROJECT_ID neon-endpoint-id:NEON_ENDPOINT_ID $OPS_SECRETS")"
MIGRATE_SECRET_FLAGS="$(secrets_flag "direct-database-url:DIRECT_DATABASE_URL*")"
MIGRATE_SECRET_FLAGS="${MIGRATE_SECRET_FLAGS:+${MIGRATE_SECRET_FLAGS},DATABASE_URL=$(secret_name direct-database-url):latest}"

# ---------------------------------------------------------------- variables (comunes + calculadas + por servicio) → un YAML por componente
env_file() {   # $1 = archivo de salida; el resto «CLAVE=valor» propios del componente
  local out="$1"; shift
  cp deploy/gcp/env/common.yaml "$out"
  {
    echo "DEPLOY_ENV: \"$GOLDEN_ENV\""
    echo "PUBLIC_BASE_URL: \"$PUBLIC_BASE_URL\""
    echo "STORAGE_BACKEND: \"gcs\""
    echo "GCS_BUCKET: \"$APP_BUCKET\""
    echo "GCS_PREFIX: \"$APP_PREFIX\""
    echo "BACKUP_BUCKET: \"$BACKUP_BUCKET\""
    echo "JOBS_BACKEND: \"cloudtasks\""
    echo "JOBS_WORKER: \"off\""
    echo "CLOUD_TASKS_QUEUE: \"$(run_path queues "$QUEUE")\""
    echo "CLOUD_TASKS_URL: \"${WEB_URL}/internal/jobs/run\""
    echo "JOBS_INVOKER_SA: \"$(sa_email "$SA_INVOKER")\""
    echo "BULK_BACKEND: \"cloudrun\""
    echo "BULK_JOB_NAME: \"$(run_path jobs "$JOB_BULK")\""
    echo "OPS_JOB_NAME: \"$(run_path jobs "$JOB_OPS")\""
    echo "WARM_SERVICE_WEB: \"$(run_path services "$SVC_WEB")\""
    echo "WARM_SERVICE_PUBLICO: \"$(run_path services "$SVC_PUBLICO")\""
    echo "WARM_SERVICE_BIOMETRIA: \"$(run_path services "$SVC_BIOMETRIA")\""
    echo "APP_COMMIT: \"${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo desconocido)}\""
    echo "APP_BUILD_DATE: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
    for kv in "$@"; do echo "${kv%%=*}: \"${kv#*=}\""; done
  } >> "$out"
}

# ---------------------------------------------------------------- 1) migraciones ANTES de cambiar los servicios
say "Job de migraciones ($JOB_MIGRATE)"
env_file "$TMP/migrate.yaml"
gcloud run jobs deploy "$JOB_MIGRATE" --image "$IMAGE" --region "$REGION" --service-account "$(sa_email "$SA_OPS")" \
  --command alembic --args upgrade,head --tasks 1 --max-retries 0 --task-timeout 900 --cpu 1 --memory 512Mi \
  --env-vars-file "$TMP/migrate.yaml" ${MIGRATE_SECRET_FLAGS:+--set-secrets "$MIGRATE_SECRET_FLAGS"} --quiet
if [ "$PLACEHOLDER" = 0 ]; then
  gcloud run jobs execute "$JOB_MIGRATE" --region "$REGION" --wait   # si falla, se detiene aquí: los servicios siguen con la versión anterior
fi

# ---------------------------------------------------------------- 2) servicios (misma imagen, APP_MODULE distinto)
deploy_service() {   # nombre, módulo, cpu, memoria, concurrencia, máx. instancias, procesos, [extra KEY=val...]
  local svc="$1" module="$2" cpu="$3" mem="$4" conc="$5" max="$6" workers="$7"; shift 7
  say "Servicio $svc"
  env_file "$TMP/$svc.yaml" "APP_MODULE=$module" "WEB_CONCURRENCY=$workers" "$@"
  local probes=()
  if [ "$PLACEHOLDER" = 0 ]; then
    # /ready (toca la base) SOLO al arrancar; el chequeo periódico de vida va a /health, que no toca nada (Neon puede apagarse).
    # Nunca rutas que terminen en «z»: Cloud Run las reserva (/healthz da 404 del propio Google).
    probes=(--startup-probe "httpGet.path=/ready,initialDelaySeconds=0,timeoutSeconds=5,periodSeconds=5,failureThreshold=36"
            --liveness-probe "httpGet.path=/health,timeoutSeconds=3,periodSeconds=30,failureThreshold=3")
  fi
  local public=()
  [ "$PLACEHOLDER" = 1 ] && public=(--allow-unauthenticated)     # solo al crearlo (bootstrap); después la política no se toca
  gcloud run deploy "$svc" --image "$IMAGE" --region "$REGION" --service-account "$(sa_email "$SA_APP")" "${public[@]}" \
    --cpu "$cpu" --memory "$mem" --concurrency "$conc" --max-instances "$max" --timeout 60 --cpu-boost --execution-environment gen2 \
    --env-vars-file "$TMP/$svc.yaml" ${APP_SECRET_FLAGS:+--set-secrets "$APP_SECRET_FLAGS"} "${probes[@]}" --quiet
}
# `web` (estaciones de cédula): límite alto con jitter grande para que los reciclajes de los procesos no coincidan bajo carga uniforme. Biometría: sin tocar (se mide en una prueba larga).
deploy_service "$SVC_WEB"       "$WEB_MODULE"                 1 1Gi 40 10 2 GUNICORN_MAX_REQUESTS=20000 GUNICORN_MAX_REQUESTS_JITTER=10000
# GUNICORN_MAX_REQUESTS=0 SOLO aquí (corrida 9: con el límite por defecto los 20 procesos de las 10 instancias se reciclaron casi a la vez en pleno pico y cortaron conexiones). El público no lleva
# dlib; `web` y `biometria` conservan el reciclaje. Por ir aquí (y no en common.yaml, que es de los tres servicios) sobrevive a cada despliegue de CI. Vigilar la memoria: docs/15.
deploy_service "$SVC_PUBLICO"   app.entrypoints.publico:app   1 1Gi 40 10 2 GUNICORN_MAX_REQUESTS=0
deploy_service "$SVC_BIOMETRIA" app.entrypoints.biometria:app 2 2Gi 2  10 1 FACE_PROCESSES=2

# ---------------------------------------------------------------- 3) Jobs de carga masiva y de operaciones
say "Job de carga masiva ($JOB_BULK)"
env_file "$TMP/bulk.yaml" FACE_PROCESSES=2
gcloud run jobs deploy "$JOB_BULK" --image "$IMAGE" --region "$REGION" --service-account "$(sa_email "$SA_APP")" \
  --command python --args=-m,app.bulk_runner --tasks 1 --max-retries 0 --task-timeout 86400 --cpu 2 --memory 4Gi \
  --env-vars-file "$TMP/bulk.yaml" ${APP_SECRET_FLAGS:+--set-secrets "$APP_SECRET_FLAGS"} --quiet
say "Job de operaciones ($JOB_OPS)"
env_file "$TMP/ops.yaml" FACE_PROCESSES=0
gcloud run jobs deploy "$JOB_OPS" --image "$IMAGE" --region "$REGION" --service-account "$(sa_email "$SA_OPS")" \
  --command python --args=-m,app.ops_runner,hourly --tasks 1 --max-retries 0 --task-timeout 1800 --cpu 1 --memory 1Gi \
  --env-vars-file "$TMP/ops.yaml" ${OPS_SECRET_FLAGS:+--set-secrets "$OPS_SECRET_FLAGS"} --quiet

if [ "$PLACEHOLDER" = 0 ]; then
  say "Comprobación"
  curl -fsS --max-time 60 "${WEB_URL}/health" && echo
  curl -fsS --max-time 60 "${WEB_URL}/ready" | head -c 300 && echo
fi
echo -e "\nListo: $GOLDEN_ENV con $IMAGE\n  web: $WEB_URL\n  público (Firebase Hosting): $PUBLIC_BASE_URL"
