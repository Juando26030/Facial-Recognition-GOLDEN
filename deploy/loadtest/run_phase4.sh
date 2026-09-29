#!/usr/bin/env bash
# Fase 4 (docs/15 «Prueba de carga distribuida»): lanza los generadores de carga como Cloud Run Jobs CONTRA STAGING. Lo corre Juan David en Cloud Shell (Claude Code no
# crea ni ejecuta recursos de nube). Todo con tope: tareas y tiempo máximos por Job, sin reintentos, y el Job se borra al final.
#
#   bash deploy/loadtest/run_phase4.sh build            # 1) construye y sube la imagen del generador (Artifact Registry de staging)
#   bash deploy/loadtest/run_phase4.sh seed             # 2) siembra el evento/formulario sintéticos (5.000 personas, cupo 4.000)
#   bash deploy/loadtest/run_phase4.sh run              # 3) los tres escenarios AL MISMO TIEMPO (formularios 10.000/5.000, cédula 200×30 min, facial)
#   bash deploy/loadtest/run_phase4.sh report <EJECUCION_forms> <EJECUCION_cedula> <EJECUCION_face>   # 4) une los logs y compara con los criterios
#   bash deploy/loadtest/run_phase4.sh verify           # 5) cupo y duplicados en la base (solo cifras)
#   bash deploy/loadtest/run_phase4.sh cleanup          # 6) borra los Jobs del generador
#
# Variables opcionales: PROJECT (goldenweb-staging), REGION (us-east1), WEB_URL (https://golden-staging-<número>.web.app: la URL PÚBLICA de Firebase de staging;
# debe contener «staging»), TASKS (20), CEDULA_MIN (30). Tope de costo aproximado por corrida completa: ver docs/15 (≈ US$1-3; 1 vCPU × 20 tareas × ≤ 40 min).
set -euo pipefail
PROJECT="${PROJECT:-goldenweb-staging}"; REGION="${REGION:-us-east1}"; TASKS="${TASKS:-20}"; CEDULA_MIN="${CEDULA_MIN:-30}"
AR="$REGION-docker.pkg.dev/$PROJECT/golden-staging"; IMAGE="$AR/loadgen:latest"; APP_IMAGE_JOB="golden-ops-staging"
JOB="golden-loadgen-staging"
say() { echo -e "\n== $*"; }
case "${1:-}" in
  build)
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
    docker build -f deploy/loadtest/Dockerfile -t "$IMAGE" . && docker push "$IMAGE" ;;
  seed)
    say "Sembrando (Job existente $APP_IMAGE_JOB, con DEPLOY_ENV=staging)"
    gcloud run jobs execute "$APP_IMAGE_JOB" --project "$PROJECT" --region "$REGION" --args="-m,scripts.seed_load_staging,--people,5000,--capacity,4000" --wait
    echo "Lee la línea LOAD_SEED de los logs (event_id y form_slug):"
    echo "  gcloud logging read 'resource.type=\"cloud_run_job\" AND textPayload:\"LOAD_SEED\"' --project $PROJECT --limit 1 --format='value(textPayload)'" ;;
  run)
    : "${WEB_URL:?Define WEB_URL con la URL pública de staging (https://golden-staging-<número>.web.app)}"; : "${LOAD_EVENT_ID:?Define LOAD_EVENT_ID (de LOAD_SEED)}"
    case "$WEB_URL" in *staging*) ;; *) echo "WEB_URL debe ser de staging"; exit 1;; esac
    mk() {  # nombre escenario usuarios tasa duración
      gcloud run jobs deploy "$JOB-$1" --project "$PROJECT" --region "$REGION" --image "$IMAGE" --tasks "$TASKS" --parallelism "$TASKS" --max-retries 0 \
        --task-timeout "$(( $5 + 240 ))s" --cpu 1 --memory 1Gi \
        --set-secrets "OPS_TOKEN=golden-ops-token-staging:latest" \
        --set-env-vars "LOAD_SCENARIO=$2,LOAD_HOST=$WEB_URL,LOAD_USERS=$3,LOAD_RATE=$4,LOAD_DURATION=$5,LOAD_EVENT_ID=$LOAD_EVENT_ID,LOAD_FORM_SLUG=carga,LOAD_PEOPLE=5000" --quiet
    }
    mk forms  forms  10000 170 180
    mk cedula cedula 200   20  "$(( CEDULA_MIN * 60 ))"
    mk face   face   60    10  300
    say "Lanzando los tres a la vez (sin --wait; sigue con «report» cuando terminen)"
    for s in forms cedula face; do gcloud run jobs execute "$JOB-$s" --project "$PROJECT" --region "$REGION" --async --format='value(metadata.name)'; done
    echo "Nombres de ejecución arriba (formularios, cédula, facial). Simulacros: pega WEB/Neon según docs/15 mientras corre la cédula (30 min)." ;;
  report)
    shift; [ "$#" -eq 3 ] || { echo "Uso: report <exec_forms> <exec_cedula> <exec_face>"; exit 1; }
    i=0; for s in forms cedula face; do
      i=$((i+1)); exec_name="${!i}"
      gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB-$s\" AND labels.\"run.googleapis.com/execution_name\"=\"$exec_name\" AND textPayload:\"LOADGEN_RESULT\"" \
        --project "$PROJECT" --format=json --limit 1000 > "/tmp/loadgen_$s.json"
    done
    python3 scripts/loadgen_report.py /tmp/loadgen_forms.json /tmp/loadgen_cedula.json /tmp/loadgen_face.json ;;
  verify)
    gcloud run jobs execute "$APP_IMAGE_JOB" --project "$PROJECT" --region "$REGION" --args="-m,scripts.seed_load_staging,--verify" --wait
    gcloud logging read 'resource.type="cloud_run_job" AND textPayload:"LOAD_VERIFY"' --project "$PROJECT" --limit 1 --format='value(textPayload)' ;;
  cleanup)
    for s in forms cedula face; do gcloud run jobs delete "$JOB-$s" --project "$PROJECT" --region "$REGION" --quiet || true; done ;;
  *) sed -n 2,14p "$0"; exit 1 ;;
esac
