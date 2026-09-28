#!/usr/bin/env bash
# Despliega una imagen en un entorno: migraciones (Job) → 3 servicios → Jobs de carga masiva y de operaciones → permisos entre ellos.
# Lo usan el workflow de GitHub Actions (.github/workflows/cloudrun.yml) y, una sola vez con --placeholder, bootstrap.sh.
#
#   deploy/gcp/deploy.sh staging    <imagen>        # p. ej. us-east1-docker.pkg.dev/<proyecto>/golden/app:<commit>
#   deploy/gcp/deploy.sh production <imagen>        # respeta el congelamiento (/api/ops/deploy-allowed); FORCE=1 lo salta
#   deploy/gcp/deploy.sh staging --placeholder      # crea todo con la imagen «hello» de Google (bootstrap, antes de la primera imagen)
#
# Qué NO toca: las instancias mínimas de cada servicio (las maneja el precalentamiento; un despliegue no las devuelve a 0), los
# secretos (solo los referencia) ni el programador (bootstrap.sh). Vuelta atrás: `gcloud run services update-traffic <svc> --to-revisions
# <revisión-anterior>=100` (Cloud Run guarda las revisiones) — ver docs/15_MIGRACION.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh "${1:-}"
IMAGE="${2:?Falta la imagen (o --placeholder)}"
PLACEHOLDER=0
if [ "$IMAGE" = "--placeholder" ]; then IMAGE="us-docker.pkg.dev/cloudrun/container/hello"; PLACEHOLDER=1; fi
WEB_URL="$(run_url "$SVC_WEB")"
if [ "$GOLDEN_ENV" = production ]; then
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://app.golden-eventos.com}"; FIREBASE_SITE="${FIREBASE_SITE:-golden-app-${PROJECT_NUMBER}}"
else
  FIREBASE_SITE="${FIREBASE_SITE:-golden-staging-${PROJECT_NUMBER}}"; PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://${FIREBASE_SITE}.web.app}"
fi
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

# ---------------------------------------------------------------- secretos que existen → --set-secrets
EXISTING="$(gcloud secrets list --format='value(name)' | sed 's#.*/##')"
secrets_flag() {   # $1 = lista «nombre:VARIABLE[*]»; los de * son obligatorios
  local out="" pair name var required s
  for pair in $1; do
    name="${pair%%:*}"; var="${pair#*:}"; required=0
    if [ "${var%\*}" != "$var" ]; then required=1; var="${var%\*}"; fi
    s="$(secret_name "$name")"
    if grep -qx "$s" <<<"$EXISTING"; then out+="${var}=${s}:latest,"
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
    # /readyz (toca la base) SOLO al arrancar; el chequeo periódico de vida va a /healthz, que no toca nada (Neon puede apagarse).
    probes=(--startup-probe "httpGet.path=/readyz,initialDelaySeconds=0,timeoutSeconds=5,periodSeconds=5,failureThreshold=36"
            --liveness-probe "httpGet.path=/healthz,timeoutSeconds=3,periodSeconds=30,failureThreshold=3")
  fi
  gcloud run deploy "$svc" --image "$IMAGE" --region "$REGION" --service-account "$(sa_email "$SA_APP")" --allow-unauthenticated \
    --cpu "$cpu" --memory "$mem" --concurrency "$conc" --max-instances "$max" --timeout 60 --cpu-boost --execution-environment gen2 \
    --env-vars-file "$TMP/$svc.yaml" ${APP_SECRET_FLAGS:+--set-secrets "$APP_SECRET_FLAGS"} "${probes[@]}" --quiet
}
deploy_service "$SVC_WEB"       app.entrypoints.web:app       1 1Gi 40 10 2
deploy_service "$SVC_PUBLICO"   app.entrypoints.publico:app   1 1Gi 40 10 2
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

# ---------------------------------------------------------------- 4) permisos entre piezas (a nivel de recurso, idempotentes)
say "Permisos entre servicios y Jobs"
bind_job() { gcloud run jobs add-iam-policy-binding "$1" --region "$REGION" --member "serviceAccount:$(sa_email "$2")" --role "$3" --quiet >/dev/null; }
bind_job "$JOB_BULK" "$SA_APP" roles/run.jobsExecutorWithOverrides       # el servicio lanza la carga masiva
bind_job "$JOB_OPS" "$SA_APP" roles/run.jobsExecutorWithOverrides        # y el precalentamiento inmediato
bind_job "$JOB_OPS" "$SA_INVOKER" roles/run.invoker                       # Cloud Scheduler corre la tarea horaria
for svc in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do                  # el precalentamiento cambia sus instancias mínimas
  gcloud run services add-iam-policy-binding "$svc" --region "$REGION" --member "serviceAccount:$(sa_email "$SA_OPS")" \
    --role roles/run.developer --quiet >/dev/null
done

if [ "$PLACEHOLDER" = 0 ]; then
  say "Comprobación"
  curl -fsS --max-time 60 "${WEB_URL}/healthz" && echo
  curl -fsS --max-time 60 "${WEB_URL}/readyz" | head -c 300 && echo
fi
echo -e "\nListo: $GOLDEN_ENV con $IMAGE\n  web: $WEB_URL\n  público (Firebase Hosting): $PUBLIC_BASE_URL"
