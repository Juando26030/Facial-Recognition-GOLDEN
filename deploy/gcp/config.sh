# Nombres y parámetros de Golden en Google Cloud. Lo cargan bootstrap.sh y deploy.sh (`source deploy/gcp/config.sh <entorno>`).
# Nada secreto aquí: los valores secretos viven en Secret Manager y solo se referencian por nombre.
#
#   GOLDEN_ENV     staging | production          (primer argumento)
#   REGION         us-east1 por defecto (Nivel 1, más barata); us-east4 es la alternativa si la latencia a Neon (us-east-1) no alcanza.
#                  Se decide en la sesión 3 midiendo DESDE Cloud Run; cambiarla es volver a correr bootstrap.sh + deploy.sh.
#   PROJECT_ID     se lee de `gcloud config` (el proyecto se renombró a «GoldenWeb» pero su ID no cambió: nunca se escribe a mano).

GOLDEN_ENV="${1:-${GOLDEN_ENV:-}}"
case "$GOLDEN_ENV" in
  staging) SUFFIX="-staging" ;;
  production) SUFFIX="" ;;
  *) echo "Uso: $0 staging|production" >&2; exit 2 ;;
esac

REGION="${REGION:-us-east1}"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT_ID" ]; then echo "No hay proyecto en gcloud config: gcloud config set project <ID>" >&2; exit 2; fi
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
GITHUB_REPO="${GITHUB_REPO:-Juando26030/Facial-Recognition-GOLDEN}"

# Imagen (un solo repositorio de Artifact Registry para los dos entornos)
AR_REPO="golden"
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

# Cola, programador
QUEUE="golden-jobs${SUFFIX}"
SCHEDULER_OPS="golden-ops-hourly${SUFFIX}"

# Buckets. Producción REUTILIZA los que ya existen (archivos bajo el prefijo «app/», separados de las copias de la VM que viven en
# «data/» y «config/»); staging tiene uno propio para que su cuenta de servicio no toque nada de producción.
if [ "$GOLDEN_ENV" = production ]; then
  APP_BUCKET="${APP_BUCKET:-golden-datos-analisis-de-imagen-id}"; APP_PREFIX="app"
  BACKUP_BUCKET="${BACKUP_BUCKET:-golden-backups-analisis-de-imagen-id}"
else
  APP_BUCKET="${APP_BUCKET:-${PROJECT_ID}-golden-staging}"; APP_PREFIX=""
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
