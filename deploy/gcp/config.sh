# Nombres y parámetros de Golden en Google Cloud. Lo cargan bootstrap.sh y deploy.sh (`source deploy/gcp/config.sh <entorno>`).
# Nada secreto aquí: los valores secretos viven en Secret Manager y solo se referencian por nombre.
#
#   GOLDEN_ENV     staging | production          (primer argumento)
#   REGION         SIN valor fijo en el código: variable REGION, o la propiedad de gcloud `run/region` (`gcloud config set run/region <región>`), o error.
#                  Decisión de Golden (2026-09-29): us-east4 (Virginia del Norte), junto a Neon (AWS us-east-1); us-east1 y us-east4 son ambas Nivel 1.
#                  TODO lo regional (servicios, Jobs, Artifact Registry, Cloud Tasks, Scheduler, bucket) vive en la MISMA región para no pagar tráfico entre
#                  regiones. Mover de región = docs/15 «Mover a otra región» y deploy/gcp/move_region.sh. OLD_REGION solo lo usa ese script.
#   PROJECT_ID     se lee de `gcloud config` (el proyecto se renombró a «GoldenWeb» pero su ID no cambió: nunca se escribe a mano).

GOLDEN_ENV="${1:-${GOLDEN_ENV:-}}"
case "$GOLDEN_ENV" in
  staging) SUFFIX="-staging" ;;
  production) SUFFIX="" ;;
  *) echo "Uso: $0 staging|production" >&2; exit 2 ;;
esac

REGION="${REGION:-$(gcloud config get-value run/region 2>/dev/null)}"
if [ -z "$REGION" ]; then echo "Falta la región: REGION=<región> o gcloud config set run/region <región> (la decidida es us-east4; ver docs/15)." >&2; exit 2; fi
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT_ID" ]; then echo "No hay proyecto en gcloud config: gcloud config set project <ID>" >&2; exit 2; fi
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
GITHUB_REPO="${GITHUB_REPO:-Juando26030/Facial-Recognition-GOLDEN}"
# Rama desde la que GitHub Actions puede desplegar cada entorno (Workload Identity: cualquier otra rama no obtiene credenciales).
if [ "$GOLDEN_ENV" = production ]; then DEPLOY_REF="refs/heads/main"; else DEPLOY_REF="${STAGING_BRANCH_REF:-refs/heads/migra/fase1-2}"; fi
# Firebase Hosting solo da permisos a nivel de PROYECTO (no por sitio). Por eso la cuenta de despliegue de staging NO los recibe salvo
# que staging viva en su propio proyecto de Google Cloud (recomendado, docs/15): FIREBASE_DEPLOY=1 para dárselos igual.
if [ "$GOLDEN_ENV" = production ]; then FIREBASE_DEPLOY="${FIREBASE_DEPLOY:-1}"; else FIREBASE_DEPLOY="${FIREBASE_DEPLOY:-0}"; fi

# Imagen: un repositorio de Artifact Registry POR ENTORNO (staging no puede sobrescribir una imagen que producción vaya a desplegar)
AR_REPO="golden${SUFFIX}"
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/app"

# Cuentas de servicio (una por papel y por entorno: staging nunca puede leer secretos ni archivos de producción)
SA_APP="golden-app${SUFFIX}"          # servicios web/publico/biometria y Job de carga masiva
SA_OPS="golden-ops${SUFFIX}"          # Jobs de operaciones y de migraciones (dueño de la base)
SA_INVOKER="golden-invoker${SUFFIX}"  # identidad de Cloud Tasks y Cloud Scheduler al llamar
SA_DEPLOYER="golden-deployer${SUFFIX}" # GitHub Actions (Workload Identity Federation, sin llaves)
sa_email() { echo "$1@${PROJECT_ID}.iam.gserviceaccount.com"; }

# Cloud Run
SVC_WEB="golden-web${SUFFIX}"; SVC_PUBLICO="golden-publico${SUFFIX}"; SVC_BIOMETRIA="golden-biometria${SUFFIX}"
JOB_MIGRATE="golden-migrate${SUFFIX}"; JOB_BULK="golden-bulk${SUFFIX}"; JOB_OPS="golden-ops${SUFFIX}"
run_url() { echo "https://$1-${PROJECT_NUMBER}.${REGION}.run.app"; }          # formato determinista de Cloud Run
run_path() { echo "projects/${PROJECT_ID}/locations/${REGION}/$1/$2"; }

# Dominio público y sitio de Firebase Hosting. Sin Firebase (staging en el mismo proyecto que producción, FIREBASE_DEPLOY=0) no hay quien
# reparta las rutas entre los 3 servicios: el servicio web de staging sirve TODA la app (WEB_MODULE) y su URL de Cloud Run es la pública.
WEB_MODULE="app.entrypoints.web:app"
if [ "$GOLDEN_ENV" = production ]; then
  FIREBASE_SITE="${FIREBASE_SITE:-golden-app-${PROJECT_NUMBER}}"; PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://app.golden-eventos.com}"
elif [ "$FIREBASE_DEPLOY" = 1 ]; then
  FIREBASE_SITE="${FIREBASE_SITE:-golden-staging-${PROJECT_NUMBER}}"; PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://${FIREBASE_SITE}.web.app}"
else
  FIREBASE_SITE=""; WEB_MODULE="app.main:app"; PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-$(run_url "golden-web${SUFFIX}")}"
fi

# Cola, programador
QUEUE="golden-jobs${SUFFIX}"
SCHEDULER_OPS="golden-ops-hourly${SUFFIX}"

# Buckets: NUEVOS y en la región del entorno (la ubicación de un bucket no se puede cambiar, y los que ya tenía la VM están en otra región: usarlos
# costaría tráfico entre regiones en cada foto y cada respaldo). El nombre lleva la región, así mover de región crea uno nuevo sin chocar con el viejo
# (los nombres son únicos en todo Google Cloud). Las copias que hace la VM (`data/`, `config/`, sus volcados) siguen en los buckets viejos hasta apagar la VM.
# Staging: uno solo (app y respaldos) para que su cuenta de servicio no toque nada de producción.
if [ "$GOLDEN_ENV" = production ]; then
  APP_BUCKET="${APP_BUCKET:-${PROJECT_ID}-golden-app-${REGION}}"; APP_PREFIX="app"
  BACKUP_BUCKET="${BACKUP_BUCKET:-${PROJECT_ID}-golden-backups-${REGION}}"
else
  APP_BUCKET="${APP_BUCKET:-${PROJECT_ID}-golden-staging-${REGION}}"; APP_PREFIX=""
  BACKUP_BUCKET="$APP_BUCKET"
fi

# Secretos (nombre en Secret Manager → variable de entorno). Los marcados con * son obligatorios.
secret_name() { echo "golden-$1${SUFFIX}"; }
APP_SECRETS="database-url:DATABASE_URL* secret-key:SECRET_KEY* face-encryption-key:FACE_ENCRYPTION_KEY* ops-token:OPS_TOKEN*
wompi-public-key:WOMPI_PUBLIC_KEY wompi-integrity-secret:WOMPI_INTEGRITY_SECRET wompi-events-secret:WOMPI_EVENTS_SECRET wompi-private-key:WOMPI_PRIVATE_KEY
wompi-sandbox-public-key:WOMPI_SANDBOX_PUBLIC_KEY wompi-sandbox-integrity-secret:WOMPI_SANDBOX_INTEGRITY_SECRET
wompi-sandbox-events-secret:WOMPI_SANDBOX_EVENTS_SECRET wompi-sandbox-private-key:WOMPI_SANDBOX_PRIVATE_KEY
azure-tenant-id:AZURE_TENANT_ID azure-client-id:AZURE_CLIENT_ID azure-client-secret:AZURE_CLIENT_SECRET graph-sender:GRAPH_SENDER"
# El Job de operaciones también manda correos (avisos) y lee lo de la app que necesita la purga (llave de rostros).
OPS_SECRETS="direct-database-url:DIRECT_DATABASE_URL* neon-api-key:NEON_API_KEY alert-email:ALERT_EMAIL"
