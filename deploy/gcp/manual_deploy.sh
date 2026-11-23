#!/usr/bin/env bash
# Despliegue MANUAL (sin GitHub Actions), para cuando Actions no está disponible (p. ej. bloqueo de facturación de GitHub, 5-nov-2026).
# Se corre desde Cloud Shell del proyecto del entorno, con la cuenta dueña. Hace lo mismo que .github/workflows/cloudrun-deploy.yml:
# construye la imagen → la sube → deploy/gcp/deploy.sh (migraciones, 3 servicios, Jobs) → Firebase Hosting (si el entorno lo usa).
#
#   git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN && cd Facial-Recognition-GOLDEN && git checkout <rama o commit>
#   nohup bash deploy/gcp/manual_deploy.sh staging    <ID-del-proyecto> > ~/deploy.log 2>&1 &     # luego: tail -f ~/deploy.log
#   nohup bash deploy/gcp/manual_deploy.sh production <ID-del-proyecto> > ~/deploy.log 2>&1 &     # respeta el congelamiento; FORCE=1 lo salta
#   CRM: staging lo enciende solo (CRM_ENABLED=1 por defecto); producción queda apagado (0) salvo `CRM_ENABLED=1 nohup bash …` con autorización de Juan David. Ver deploy/gcp/config.sh.
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
# Valores NO secretos que cada despliegue debe llevar (ONEDRIVE_DRIVE_ID, OFFSITE_FOLDER_URL…): se guardan una vez en ~/.golden-<entorno>.env (líneas CLAVE=valor) y se cargan aquí,
# para que no dependan de que alguien los escriba delante del comando (si faltan, el Job pierde la copia semanal). Ver deploy/gcp/README.md.
if [ -f "$HOME/.golden-${ENV_NAME}.env" ]; then set -a; . "$HOME/.golden-${ENV_NAME}.env"; set +a; echo "Cargado ~/.golden-${ENV_NAME}.env"; fi
PROJECT_NUMBER_="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')" || exit 1
if [ "$ENV_NAME" = production ]; then
  HOSTING_SITE="${FIREBASE_SITE:-golden-app-${PROJECT_NUMBER_}}"; export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://app.golden-eventos.com}"
else
  HOSTING_SITE="${FIREBASE_SITE:-golden-staging-${PROJECT_NUMBER_}}"; export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://${HOSTING_SITE}.web.app}"
fi
export FIREBASE_SITE="$HOSTING_SITE"
source deploy/gcp/config.sh "$ENV_NAME"
SHA="$(git rev-parse HEAD)"
# CRM: el valor sale de config.sh (staging 1, producción 0 salvo CRM_ENABLED=1 en este comando) y deploy.sh lo escribe en el servicio `web`. Se muestra aquí para verlo ANTES de desplegar.
echo "CRM_ENABLED=$CRM_ENABLED (entorno $ENV_NAME)"
echo "ALMACEN_ENABLED=$ALMACEN_ENABLED (entorno $ENV_NAME)"
if [ "$ENV_NAME" = production ] && [ "$CRM_ENABLED" = 1 ]; then echo "AVISO: vas a ENCENDER el CRM en PRODUCCIÓN. Solo con autorización explícita de Juan David y con el contador fijado (scripts/crm_set_counter.py)." >&2; fi
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
PKG_OK=1
if [ "$ENV_NAME" = production ]; then
  say "5. PAQUETE DE ACTUALIZACIÓN DE LOS SERVIDORES LOCALES (mismo commit que acaba de salir)"
  PKG_OK=0
  VER="$(date -u +%Y.%m.%d.%H%M%S)"; PKG_DIR="$(mktemp -d)"
  if git archive HEAD | tar -x -C "$PKG_DIR" \
     && docker run --rm -v "$PKG_DIR:/repo" -w /repo -e UPDATE_ONLY=1 -e PYTHONDONTWRITEBYTECODE=1 python:3.13-slim python deploy/windows/build_cross.py "$VER" "$SHA" \
     && DEST="gs://${APP_BUCKET}/${APP_PREFIX:+$APP_PREFIX/}system/local-update/" \
     && gsutil -q cp "$PKG_DIR/build/windows/out/golden-local-update-$VER.zip" "$PKG_DIR/build/windows/out/golden-local-update-$VER.sha256" "$PKG_DIR/build/windows/out/golden-local-update-$VER.commit" "$DEST"; then
    for i in 1 2 3 4 5 6; do   # el manifiesto debe anunciar ESTE paquete y ESTE commit
      M="$(curl -s "$PUBLIC_BASE_URL/api/ops/update-manifest")"
      if echo "$M" | grep -q "golden-local-update-$VER.zip" && echo "$M" | grep -q "\"commit\":\"${SHA:0:12}"; then PKG_OK=1; break; fi
      sleep 10
    done
    echo "$M"
  fi
  docker run --rm -v "$PKG_DIR:/repo" python:3.13-slim rm -rf /repo/build /repo/deploy >/dev/null 2>&1; rm -rf "$PKG_DIR" 2>/dev/null || true
  if [ "$PKG_OK" = 1 ]; then echo "Paquete $VER publicado: los servidores locales ya pueden actualizarse."; else echo "ATENCIÓN: el despliegue salió pero el paquete de los servidores locales NO quedó publicado (los locales no verán la versión nueva hasta repetirlo)." >&2; fi
fi
say "LISTO ($ENV_NAME, commit ${SHA:0:7})"
gcloud run services list --region "$REGION" --format="table(metadata.name,status.latestReadyRevisionName)"
[ "$PKG_OK" = 1 ] || exit 2
