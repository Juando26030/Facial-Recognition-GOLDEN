#!/usr/bin/env bash
# Parche urgente SOLO del servicio público (formularios), 10-nov-2026: construye la imagen, la sube y actualiza golden-publico con ella.
# No toca la base de datos (sin migraciones), los otros servicios, los Jobs ni Firebase Hosting. Se corre desde Cloud Shell con la cuenta que tenga
# Cloud Run Admin + Artifact Registry Writer + Usuario de cuenta de servicio:
#   git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN && cd Facial-Recognition-GOLDEN && git checkout fix/precarga-variantes
#   nohup bash deploy/gcp/hotfix_publico.sh goldenweb-prod > ~/hotfix.log 2>&1 &      # luego: tail -f ~/hotfix.log
# Volver atrás: el script imprime la revisión anterior; gcloud run services update-traffic golden-publico --to-revisions <anterior>=100 --region us-east4
set -uo pipefail
cd "$(dirname "$0")/../.."
PROJECT_ID="${1:?Uso: $0 <ID-del-proyecto>}"
REGION="${REGION:-us-east4}"
SERVICE="${SERVICE:-golden-publico}"
SHA="${COMMIT:-$(git rev-parse HEAD 2>/dev/null)}"          # sin .git (código bajado como ZIP): COMMIT=6f16314... bash deploy/gcp/hotfix_publico.sh <proyecto>
[ -n "$SHA" ] || { echo "ERROR: sin .git hace falta COMMIT=<hash del commit>" >&2; exit 1; }
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/golden/app:${SHA}"
if [ -d .git ] && [ -n "$(git status --porcelain)" ]; then echo "ERROR: hay cambios sin guardar; se despliega solo lo que está en un commit." >&2; exit 1; fi
echo "== 1. Revisión actual de $SERVICE (para volver atrás)"
gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.latestReadyRevisionName)' || exit 1
echo "== 2. Imagen $IMAGE (la primera vez tarda 20-60 min por dlib; si se corta, repetir el mismo comando)"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" -q
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker build --build-arg APP_COMMIT="$SHA" -t "$IMAGE" . || { echo "ERROR: falló la construcción" >&2; exit 1; }
OK=0
for i in 1 2 3 4 5 6; do echo "subida, intento $i"; docker push "$IMAGE" && { OK=1; break; }; sleep 15; done
[ "$OK" = 1 ] || { echo "ERROR: no se pudo subir la imagen (repetir el mismo comando)" >&2; exit 1; }
echo "== 3. Actualizar $SERVICE (conserva variables, secretos y cuentas de servicio)"
gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" || exit 1
echo "== LISTO (commit ${SHA:0:7})"
gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.latestReadyRevisionName)'
