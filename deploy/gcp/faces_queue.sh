#!/usr/bin/env bash
# Cola de Cloud Tasks de los CÁLCULOS FACIALES (`golden-faces[-staging]`): el vector se calcula después de que la persona acepta y NUNCA debe quitarle CPU a la puerta.
# La corre Juan David en Cloud Shell (Claude no ejecuta gcloud). Idempotente: crea la cola si falta o la corrige si algo difiere.
#
#   bash deploy/gcp/faces_queue.sh <staging|production>
#
# Qué deja: una cola con MÁXIMO 2 despachos simultáneos (2 por segundo), 5 intentos y espera creciente (10 s → 300 s), con permiso para que la cuenta de la app encole.
# Después: redesplegar (deploy.sh agrega CLOUD_TASKS_FACES_QUEUE y CLOUD_TASKS_FACES_URL = <servicio de biometría>/internal/faces/run). Sin esas variables todo sigue funcionando por la cola general.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh "${1:-}"
exists() { "$@" >/dev/null 2>&1; }
ARGS=(--max-dispatches-per-second 2 --max-concurrent-dispatches 2 --max-attempts 5 --min-backoff 10s --max-backoff 300s --max-doublings 4)
if exists gcloud tasks queues describe "$QUEUE_FACES" --location "$REGION"; then
  gcloud tasks queues update "$QUEUE_FACES" --location "$REGION" "${ARGS[@]}" --quiet
else
  gcloud tasks queues create "$QUEUE_FACES" --location "$REGION" "${ARGS[@]}"
fi
gcloud tasks queues add-iam-policy-binding "$QUEUE_FACES" --location "$REGION" --member "serviceAccount:$(sa_email "$SA_APP")" --role roles/cloudtasks.enqueuer --quiet >/dev/null
echo "Cola $QUEUE_FACES lista (2 despachos simultáneos). Falta: redesplegar para que los servicios la usen."
