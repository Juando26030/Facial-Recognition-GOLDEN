#!/usr/bin/env bash
# Despliegue MANUAL (sin GitHub Actions), para cuando Actions no está disponible (p. ej. bloqueo de facturación de GitHub, 5-nov-2026).
# Se corre desde Cloud Shell del proyecto del entorno, con la cuenta dueña. Hace lo mismo que .github/workflows/cloudrun-deploy.yml:
# construye la imagen → la sube → deploy/gcp/deploy.sh (migraciones, 3 servicios, Jobs) → Firebase Hosting (si el entorno lo usa).
#
#   git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN && cd Facial-Recognition-GOLDEN && git checkout <rama o commit>
#   nohup bash deploy/gcp/manual_deploy.sh staging    <ID-del-proyecto> > ~/deploy.log 2>&1 &     # luego: tail -f ~/deploy.log
#   nohup bash deploy/gcp/manual_deploy.sh production <ID-del-proyecto> > ~/deploy.log 2>&1 &     # respeta el congelamiento; FORCE=1 lo salta
#
# Lecciones de la primera vez (producción, 5-nov-2026): el build de dlib tarda 20-60 min (por eso nohup y no cerrar la pestaña); el push desde
# Cloud Shell falló con «connection refused» con varias capas en paralelo → aquí se sube de a una capa y con reintentos; si se corta, volver a correr
# el mismo comando (las capas ya construidas y subidas se reutilizan). Nunca crea recursos ni permisos de nube (eso es de bootstrap.sh).
set -uo pipefail
cd "$(dirname "$0")/../.."
ENV_NAME="${1:?Uso: $0 staging|production <ID-del-proyecto>}"
export PROJECT_ID="${2:?Falta el ID del proyecto de Google Cloud}"
# Sitio de Firebase Hosting y dirección pública, igual que las variables FIREBASE_SITE y PUBLIC_BASE_URL del Environment de GitHub (no son secretos).
# OJO: config.sh deja FIREBASE_SITE vacío en staging (FIREBASE_DEPLOY=0), pero el workflow SÍ publica Hosting y fija PUBLIC_BASE_URL; por eso aquí se guarda el sitio
# en HOSTING_SITE antes de cargar config.sh y PUBLIC_BASE_URL se exporta antes. (Primera vez en staging, 5-nov-2026: sin esto los servicios quedaron con la URL run.app
# como dirección pública y Hosting sin publicar.)
PROJECT_NUMBER_="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')" || exit 1
if [ "$ENV_NAME" = production ]; then
  HOSTING_SITE="${FIREBASE_SITE:-golden-app-${PROJECT_NUMBER_}}"; export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://app.golden-eventos.com}"
else
  HOSTING_SITE="${FIREBASE_SITE:-golden-staging-${PROJECT_NUMBER_}}"; export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://${HOSTING_SITE}.web.app}"
fi
export FIREBASE_SITE="$HOSTING_SITE"
source deploy/gcp/config.sh "$ENV_NAME"
SHA="$(git rev-parse HEAD)"
IMAGE="${IMAGE_BASE}:${SHA}"
say() { echo -e "\n== $*"; }
if [ -n "$(git status --porcelain)" ]; then echo "ERROR: hay cambios sin guardar en la copia del código; se despliega solo lo que está en un commit." >&2; exit 1; fi

say "1. REVISIONES ACTUALES (para volver atrás: gcloud run services update-traffic <servicio> --to-revisions <revisión>=100 --region $REGION)"
gcloud run services list --region "$REGION" --format="table(metadata.name,status.latestReadyRevisionName)"

say "2. IMAGEN $IMAGE"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" -q
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build --build-arg APP_COMMIT="$SHA" -t "$IMAGE" . || { echo "ERROR: falló la construcción" >&2; exit 1; }
fi
printf '{"max-concurrent-uploads":1}\n' | sudo tee /etc/docker/daemon.json >/dev/null 2>&1 && { sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null || true; sleep 5; }
OK=0
for i in 1 2 3 4 5 6; do
  echo "subida, intento $i"; docker push "$IMAGE" && { OK=1; break; }; sleep 15
done
[ "$OK" = 1 ] || { echo "ERROR: no se pudo subir la imagen (volver a correr el mismo comando)" >&2; exit 1; }

say "3. DESPLEGAR"
bash deploy/gcp/deploy.sh "$ENV_NAME" "$IMAGE" || { echo "ERROR en deploy.sh (no se publica Hosting)" >&2; exit 1; }

if [ -n "$HOSTING_SITE" ]; then   # igual que el workflow: se publica Hosting siempre que el entorno tenga sitio
  say "4. FIREBASE HOSTING (/static sale de la CDN: sin esto los archivos nuevos no llegan)"
  python3 deploy/firebase/make_config.py "$GOLDEN_ENV" "$PROJECT_ID" "$REGION" "$HOSTING_SITE" || exit 1
  npx -y firebase-tools@13 deploy --only hosting --project "$PROJECT_ID" --config build/firebase/firebase.json --non-interactive || { echo "ERROR en Hosting" >&2; exit 1; }
fi
if [ -n "${FORMS_SITE:-}" ]; then   # D2.5k (docs/20): segundo sitio de Hosting del host de inscripciones (todo → servicio publico); solo si se definió FORMS_SITE
  say "4b. FIREBASE HOSTING · sitio de inscripciones ($FORMS_SITE)"
  python3 deploy/firebase/make_config.py "$GOLDEN_ENV" "$PROJECT_ID" "$REGION" "$FORMS_SITE" --inscripciones || exit 1
  npx -y firebase-tools@13 deploy --only hosting --project "$PROJECT_ID" --config build/firebase-inscripciones/firebase.json --non-interactive || { echo "ERROR en Hosting (inscripciones)" >&2; exit 1; }
fi
say "LISTO ($ENV_NAME, commit ${SHA:0:7})"
gcloud run services list --region "$REGION" --format="table(metadata.name,status.latestReadyRevisionName)"
