#!/usr/bin/env bash
# =====================================================================================================================================
#  Golden en Google Cloud — creación de TODO lo necesario para un entorno (staging o production). Idempotente: se puede volver a correr;
#  lo que ya existe no se toca (salvo lo que se indica). Lo corre Juan David en Cloud Shell, DESPUÉS de revisarlo:
#
#      gcloud config set project <ID del proyecto>      # el proyecto se llama «GoldenWeb», pero el ID es otro: el script lo lee de aquí
#      bash deploy/gcp/bootstrap.sh staging              # primero staging
#      bash deploy/gcp/bootstrap.sh production           # después producción (servicios quedan con imagen de relleno hasta el cambio)
#      REGION=us-east4 bash deploy/gcp/bootstrap.sh ...  # si la medición de la sesión 3 decide Virginia del Norte
#
#  QUÉ CREA Y CUÁNTO CUESTA (precios de lista, US$/mes; la suma de TODO el plan está en docs/15_MIGRACION.md):
#   1. APIs (Cloud Run, Artifact Registry, Secret Manager, Cloud Tasks, Cloud Scheduler, IAM, Monitoring, Firebase…) ....... 0
#   2. Artifact Registry «golden» (imágenes Docker) con limpieza automática: guarda las 10 últimas, borra lo de >30 días.
#      0,5 GB gratis; la imagen pesa ~0,7 GB y las versiones comparten capas ......................................... ~0,10-0,30
#   3. Cuentas de servicio con permisos mínimos (app, ops, invoker, deployer) por entorno ................................ 0
#   4. Workload Identity Federation para GitHub Actions (sin llaves: GitHub se identifica con su token OIDC) .............. 0
#   5. Secret Manager: pide cada valor POR TECLADO (no se ve en pantalla ni queda en el historial). US$0,06 por versión
#      activa al mes (6 gratis por cuenta de facturación); ~15-20 secretos por entorno .................................. ~1-2
#   6. Buckets: producción REUTILIZA los que ya existen (archivos bajo «app/»); staging crea uno propio. CORS para la subida
#      directa (deploy/gcs-app-cors.json), ciclo de vida (deploy/gcs-app-lifecycle.json / gcs-lifecycle.json) y versiones
#      de objeto (lo borrado o sobrescrito se conserva 30 días). US$0,02 por GB (regional) ................................ ~0,05-0,50
#   7. Cloud Tasks «golden-jobs»: despierta la cola de trabajos. 1 millón de operaciones al mes gratis ..................... 0
#   8. Cloud Run: 3 servicios (web, publico, biometria) y 3 Jobs (migraciones, carga masiva, operaciones), creados con una
#      imagen de relleno; el primer despliegue real lo hace GitHub Actions. Escalan a cero, máx. 10 instancias cada uno.
#      Cobro por uso (ver doc 13 §6) ................................................................................... ~5-19
#   9. Cloud Scheduler: UNA tarea (golden-ops-hourly, cada hora al minuto 05). 3 tareas gratis por cuenta; producción la
#      activa, staging no (se corre a mano) ............................................................................. 0
#  10. Monitoreo: canal de correo, chequeo de disponibilidad a /health cada minuto (NO toca la base: Neon puede apagarse),
#      alertas de caída, de Jobs fallidos y de errores 5xx. Chequeos: 1 millón/mes gratis; alertas sin costo hasta 2027 ... 0
#  11. Presupuesto con avisos al 50, 90 y 100 % (solo con production; en la moneda de la cuenta de facturación) ........... 0
#  12. Firebase Hosting: sitio del entorno (dominio propio frente a Cloud Run; la CDN sirve /static). 10 GB/mes gratis ..... ~0
#
#  NO crea: la cuenta ni las ramas de Neon (ya existen), el rol golden_app (lo hace scripts/neon_app_role.py, que este script
#  llama), el dominio propio en Firebase (paso manual del día del cambio, docs/15) ni nada en la VM.
# =====================================================================================================================================
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh "${1:-}"
ROTATE="${ROTATE:-}"          # p. ej. ROTATE="secret-key ops-token": vuelve a pedir esos secretos aunque existan
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
step() { echo -e "\n\033[1m== $*\033[0m"; }
ok() { echo "   ✓ $*"; }
exists() { "$@" >/dev/null 2>&1; }

echo "Proyecto: $PROJECT_ID (número $PROJECT_NUMBER) · Entorno: $GOLDEN_ENV · Región: $REGION · Repositorio: $GITHUB_REPO"
read -rp "¿Continuar? (escribe «si»): " answer; [ "$answer" = "si" ] || { echo "Cancelado."; exit 1; }

# -------------------------------------------------------------------------------------------------------------------------- 1
step "1. APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com monitoring.googleapis.com \
  logging.googleapis.com storage.googleapis.com billingbudgets.googleapis.com cloudbilling.googleapis.com \
  firebase.googleapis.com firebasehosting.googleapis.com
ok "habilitadas"

# -------------------------------------------------------------------------------------------------------------------------- 2
step "2. Artifact Registry ($AR_REPO, $REGION)"
if ! exists gcloud artifacts repositories describe "$AR_REPO" --location "$REGION"; then
  gcloud artifacts repositories create "$AR_REPO" --repository-format docker --location "$REGION" --description "Imágenes de Golden"
fi
cat > "$TMP/cleanup.json" <<'EOF'
[{"name": "guardar-10-recientes", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 10}},
 {"name": "borrar-viejas", "action": {"type": "Delete"}, "condition": {"olderThan": "2592000s"}}]
EOF
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location "$REGION" --policy "$TMP/cleanup.json" --no-dry-run --quiet >/dev/null
ok "repositorio y limpieza"

# -------------------------------------------------------------------------------------------------------------------------- 3
step "3. Cuentas de servicio"
for sa in "$SA_APP:App (servicios y carga masiva)" "$SA_OPS:Operaciones y migraciones" "$SA_INVOKER:Cloud Tasks y Scheduler" "$SA_DEPLOYER:GitHub Actions"; do
  name="${sa%%:*}"
  exists gcloud iam service-accounts describe "$(sa_email "$name")" || gcloud iam service-accounts create "$name" --display-name "Golden ${GOLDEN_ENV}: ${sa#*:}"
done
sa_bind() {   # cuenta-destino miembro rol
  gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$1")" --member "serviceAccount:$(sa_email "$2")" --role "$3" --quiet >/dev/null
}
project_bind() { gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$(sa_email "$1")" --role "$2" --condition=None --quiet >/dev/null; }
sa_bind "$SA_APP" "$SA_APP" roles/iam.serviceAccountTokenCreator   # firmar sus propias URLs de subida (signBlob): no tiene llave privada
sa_bind "$SA_INVOKER" "$SA_APP" roles/iam.serviceAccountUser       # crear tareas de Cloud Tasks con el token OIDC del invoker
sa_bind "$SA_APP" "$SA_DEPLOYER" roles/iam.serviceAccountUser      # desplegar servicios que corren como app / ops
sa_bind "$SA_OPS" "$SA_DEPLOYER" roles/iam.serviceAccountUser
# La cuenta de despliegue NO tiene roles de Cloud Run a nivel de proyecto: recibe run.developer sobre cada servicio y Job de SU entorno
# (paso 8). Lo único de proyecto: ver el estado de las operaciones que lanza (rol propio de solo lectura, nada de otro entorno).
OPS_ROLE="goldenRunOperationsViewer"
exists gcloud iam roles describe "$OPS_ROLE" --project "$PROJECT_ID" \
  || gcloud iam roles create "$OPS_ROLE" --project "$PROJECT_ID" --title "Golden: ver operaciones de Cloud Run" \
       --permissions run.operations.get,run.operations.list --stage GA >/dev/null
project_bind "$SA_DEPLOYER" "projects/${PROJECT_ID}/roles/${OPS_ROLE}"
if [ "$FIREBASE_DEPLOY" = 1 ]; then
  project_bind "$SA_DEPLOYER" roles/firebasehosting.admin           # solo a nivel de proyecto: ver docs/15 (staging en proyecto aparte)
fi
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" \
  --member "serviceAccount:$(sa_email "$SA_DEPLOYER")" --role roles/artifactregistry.writer --quiet >/dev/null
ok "app, ops, invoker, deployer"

# -------------------------------------------------------------------------------------------------------------------------- 4
step "4. Workload Identity Federation (GitHub → $SA_DEPLOYER)"
POOL=github; PROVIDER=github-oidc
exists gcloud iam workload-identity-pools describe "$POOL" --location global \
  || gcloud iam workload-identity-pools create "$POOL" --location global --display-name "GitHub Actions"
exists gcloud iam workload-identity-pools providers describe "$PROVIDER" --location global --workload-identity-pool "$POOL" \
  || gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location global --workload-identity-pool "$POOL" \
       --issuer-uri "https://token.actions.githubusercontent.com" \
       --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
       --attribute-condition "assertion.repository=='${GITHUB_REPO}'"
POOL_PATH="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
# Solo la rama del entorno (el proveedor ya exige el repositorio): staging ← migra/fase1-2, producción ← main.
MEMBER="principalSet://iam.googleapis.com/${POOL_PATH}/attribute.ref/${DEPLOY_REF}"
gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$SA_DEPLOYER")" --role roles/iam.workloadIdentityUser --member "$MEMBER" --quiet >/dev/null
ok "proveedor ${POOL_PATH}/providers/${PROVIDER}; $SA_DEPLOYER solo desde ${DEPLOY_REF}"

# -------------------------------------------------------------------------------------------------------------------------- 5
step "5. Secret Manager (${GOLDEN_ENV})"
echo "   Cada valor se escribe a ciegas (no se ve) y va directo a Secret Manager. Enter en uno opcional = no crearlo."
gen_hex() { python3 -c "import secrets; print(secrets.token_hex(32))"; }
gen_fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }
ensure_secret() { exists gcloud secrets describe "$1" || gcloud secrets create "$1" --replication-policy automatic >/dev/null; }
put_secret() {   # nombre-corto  ayuda  obligatorio(0/1)  [generador]
  local s; s="$(secret_name "$1")"
  if exists gcloud secrets versions access latest --secret "$s" && [[ " $ROTATE " != *" $1 "* ]]; then ok "$s ya tiene valor"; return; fi
  local value=""
  read -rsp "   $s — $2: " value; echo
  if [ -z "$value" ] && [ -n "${4:-}" ]; then value="$($4)"; echo "     (generado al azar)"; fi
  if [ -z "$value" ]; then
    [ "$3" = 1 ] && { echo "   $s es obligatorio." >&2; exit 1; }
    echo "     (omitido)"; return
  fi
  ensure_secret "$s"
  printf '%s' "$value" | gcloud secrets versions add "$s" --data-file=- >/dev/null
  ok "$s guardado"
}
put_secret direct-database-url "cadena DIRECTA de Neon (rama ${GOLDEN_ENV}, rol DUEÑO, host SIN -pooler)" 1
if [ "$GOLDEN_ENV" = production ]; then
  put_secret secret-key "SECRET_KEY actual de la VM (misma, para no invalidar sesiones ni enlaces ya enviados)" 1
  put_secret face-encryption-key "FACE_ENCRYPTION_KEY actual de la VM (SIN ella no se pueden leer los rostros migrados)" 1
else
  put_secret secret-key "Enter = generar una nueva" 1 gen_hex
  put_secret face-encryption-key "Enter = generar una NUEVA (nunca la de producción)" 1 gen_fernet
fi
put_secret ops-token "Enter = generar uno nuevo" 1 gen_hex
for opt in wompi-public-key wompi-integrity-secret wompi-events-secret wompi-private-key wompi-sandbox-public-key \
           wompi-sandbox-integrity-secret wompi-sandbox-events-secret wompi-sandbox-private-key \
           azure-tenant-id azure-client-id azure-client-secret graph-sender alert-email neon-api-key neon-project-id neon-endpoint-id; do
  put_secret "$opt" "opcional" 0
done
# La cadena de la APP (rol golden_app, por el pooler) la genera scripts/neon_app_role.py: crea el rol si falta, con contraseña al azar,
# y la guarda directo en el secreto. Nunca pasa por la pantalla.
if ! exists gcloud secrets versions access latest --secret "$(secret_name database-url)" || [[ " $ROTATE " == *" database-url "* ]]; then
  ensure_secret "$(secret_name database-url)"
  pip3 install --user --quiet psycopg2-binary >/dev/null 2>&1 || true
  # --rotate: si golden_app ya existía su contraseña no se conoce, así que se le pone una nueva para poder guardarla en el secreto.
  python3 scripts/neon_app_role.py --owner-secret "$(secret_name direct-database-url)" --app-secret "$(secret_name database-url)" --rotate
fi
secret_access() { gcloud secrets add-iam-policy-binding "$(secret_name "$1")" --member "serviceAccount:$(sa_email "$2")" \
                    --role roles/secretmanager.secretAccessor --quiet >/dev/null 2>&1 || true; }
for pair in $APP_SECRETS; do secret_access "${pair%%:*}" "$SA_APP"; secret_access "${pair%%:*}" "$SA_OPS"; done
for pair in $OPS_SECRETS neon-project-id:x neon-endpoint-id:x; do secret_access "${pair%%:*}" "$SA_OPS"; done
secret_access ops-token "$SA_DEPLOYER"     # el despliegue pregunta /api/ops/deploy-allowed (congelamiento)
# El despliegue necesita saber QUÉ secretos de SU entorno existen (para montarlos), no sus valores: metadatos por secreto, no del proyecto.
for pair in $APP_SECRETS $OPS_SECRETS neon-project-id:x neon-endpoint-id:x; do
  gcloud secrets add-iam-policy-binding "$(secret_name "${pair%%:*}")" --member "serviceAccount:$(sa_email "$SA_DEPLOYER")" \
    --role roles/secretmanager.viewer --quiet >/dev/null 2>&1 || true
done
ok "permisos de lectura: app → secretos de la app; ops → todos; deployer → ops-token y metadatos de los de su entorno"

# -------------------------------------------------------------------------------------------------------------------------- 6
step "6. Buckets"
if [ "$GOLDEN_ENV" = staging ] && ! exists gcloud storage buckets describe "gs://$APP_BUCKET"; then
  gcloud storage buckets create "gs://$APP_BUCKET" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
fi
for b in "$APP_BUCKET" "$BACKUP_BUCKET"; do
  echo "   gs://$b está en: $(gcloud storage buckets describe "gs://$b" --format='value(location)')"
  echo "   reglas de ciclo de vida ACTUALES (se reemplazan por las del repositorio):"
  gcloud storage buckets describe "gs://$b" --format='json(lifecycle_config)' | sed 's/^/     /'
done
python3 - "$PUBLIC_BASE_URL" "$FIREBASE_SITE" > "$TMP/cors.json" <<'EOF'
import json, sys
rules = json.load(open("deploy/gcs-app-cors.json"))
site = sys.argv[2]
rules[0]["origin"] = sorted({sys.argv[1]} | ({f"https://{site}.web.app", f"https://{site}.firebaseapp.com"} if site else set()))
print(json.dumps(rules))
EOF
gcloud storage buckets update "gs://$APP_BUCKET" --cors-file "$TMP/cors.json" --versioning --quiet >/dev/null
# Sin «soft delete» (retención de lo borrado, 7 días por defecto en GCS): la protección contra borrados es el versionado (30 días) y, para
# fotos biométricas, lo purgado debe desaparecer en ~1 día. En los respaldos tampoco: nadie puede borrarlos (ninguna cuenta de servicio
# tiene permiso; solo el ciclo de vida), así el tiempo máximo que sobrevive un dato purgado en un respaldo es un número fijo (docs/15).
gcloud storage buckets update "gs://$APP_BUCKET" --clear-soft-delete --quiet >/dev/null
gcloud storage buckets update "gs://$BACKUP_BUCKET" --clear-soft-delete --quiet >/dev/null
if [ "$APP_BUCKET" = "$BACKUP_BUCKET" ]; then        # staging: un solo bucket con las dos reglas
  python3 -c 'import json; a, b = (json.load(open(f)) for f in ("deploy/gcs-app-lifecycle.json", "deploy/gcs-lifecycle.json")); print(json.dumps({"rule": a["rule"] + b["rule"]}))' > "$TMP/lc.json"
  gcloud storage buckets update "gs://$APP_BUCKET" --lifecycle-file "$TMP/lc.json" --quiet >/dev/null
else
  gcloud storage buckets update "gs://$APP_BUCKET" --lifecycle-file deploy/gcs-app-lifecycle.json --quiet >/dev/null
  gcloud storage buckets update "gs://$BACKUP_BUCKET" --lifecycle-file deploy/gcs-lifecycle.json --quiet >/dev/null
fi
bucket_bind() { gcloud storage buckets add-iam-policy-binding "gs://$1" --member "serviceAccount:$(sa_email "$2")" --role "$3" --quiet >/dev/null; }
bucket_bind "$APP_BUCKET" "$SA_APP" roles/storage.objectAdmin
bucket_bind "$APP_BUCKET" "$SA_OPS" roles/storage.objectAdmin              # la purga biométrica borra fotos
bucket_bind "$BACKUP_BUCKET" "$SA_OPS" roles/storage.objectCreator          # respaldos: crear…
bucket_bind "$BACKUP_BUCKET" "$SA_OPS" roles/storage.objectViewer           # …y revisar (no borrar: eso lo hace el ciclo de vida)
bucket_bind "$BACKUP_BUCKET" "$SA_APP" roles/storage.objectViewer           # «Último respaldo» en /sistema
ok "CORS ($PUBLIC_BASE_URL + dominios de Firebase), versiones, ciclo de vida y permisos"

# -------------------------------------------------------------------------------------------------------------------------- 7
step "7. Cloud Tasks ($QUEUE)"
if ! exists gcloud tasks queues describe "$QUEUE" --location "$REGION"; then
  gcloud tasks queues create "$QUEUE" --location "$REGION" --max-dispatches-per-second 5 --max-concurrent-dispatches 5 \
    --max-attempts 5 --min-backoff 10s --max-backoff 300s
fi
gcloud tasks queues add-iam-policy-binding "$QUEUE" --location "$REGION" --member "serviceAccount:$(sa_email "$SA_APP")" \
  --role roles/cloudtasks.enqueuer --quiet >/dev/null
ok "cola con tope de 5 despachos simultáneos"

# -------------------------------------------------------------------------------------------------------------------------- 8
step "8. Cloud Run (servicios y Jobs)"
if exists gcloud run services describe "$SVC_WEB" --region "$REGION"; then
  ok "ya existen: los actualiza el workflow de GitHub Actions (no se tocan aquí)"
else
  bash deploy/gcp/deploy.sh "$GOLDEN_ENV" --placeholder       # crea los 3 servicios (públicos) y los 3 Jobs con la imagen «hello»
fi
# Permisos a nivel de RECURSO (idempotentes). El despliegue ya no da permisos: lo hace esto, con la cuenta de quien corre el bootstrap.
bind_job() { gcloud run jobs add-iam-policy-binding "$1" --region "$REGION" --member "serviceAccount:$(sa_email "$2")" --role "$3" --quiet >/dev/null; }
bind_svc() { gcloud run services add-iam-policy-binding "$1" --region "$REGION" --member "serviceAccount:$(sa_email "$2")" --role "$3" --quiet >/dev/null; }
for svc in "$SVC_WEB" "$SVC_PUBLICO" "$SVC_BIOMETRIA"; do
  bind_svc "$svc" "$SA_DEPLOYER" roles/run.developer               # GitHub Actions actualiza SOLO los servicios de su entorno
  bind_svc "$svc" "$SA_OPS" roles/run.developer                    # el precalentamiento cambia sus instancias mínimas
done
for job in "$JOB_MIGRATE" "$JOB_BULK" "$JOB_OPS"; do bind_job "$job" "$SA_DEPLOYER" roles/run.developer; done
bind_job "$JOB_BULK" "$SA_APP" roles/run.jobsExecutorWithOverrides  # el servicio lanza la carga masiva
bind_job "$JOB_OPS" "$SA_APP" roles/run.jobsExecutorWithOverrides   # y el precalentamiento inmediato
bind_job "$JOB_OPS" "$SA_INVOKER" roles/run.invoker                  # Cloud Scheduler corre la tarea horaria
ok "$SA_DEPLOYER: run.developer sobre los 3 servicios y 3 Jobs de $GOLDEN_ENV (nada del otro entorno)"

# -------------------------------------------------------------------------------------------------------------------------- 9
step "9. Cloud Scheduler ($SCHEDULER_OPS)"
if [ "$GOLDEN_ENV" = production ] || [ "${SCHEDULE_STAGING:-0}" = 1 ]; then
  if ! exists gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION"; then
    gcloud scheduler jobs create http "$SCHEDULER_OPS" --location "$REGION" --schedule "5 * * * *" --time-zone "America/Bogota" \
      --uri "https://run.googleapis.com/v2/$(run_path jobs "$JOB_OPS"):run" --http-method POST \
      --oauth-service-account-email "$(sa_email "$SA_INVOKER")" --description "Respaldos, revisión, purga, cola y precalentamiento"
    # Se crea EN PAUSA: hasta el día del cambio el Job tiene la imagen de relleno (fallaría cada hora y llenaría el correo de alertas)
    # y no debe respaldar una base que todavía no es la real. Se reanuda en el runbook del cambio:
    #   gcloud scheduler jobs resume golden-ops-hourly --location <región>
    gcloud scheduler jobs pause "$SCHEDULER_OPS" --location "$REGION" >/dev/null
  fi
  ok "cada hora al minuto 05 (Bogotá); estado: $(gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION" --format 'value(state)')"
else
  ok "staging no se programa (SCHEDULE_STAGING=1 para hacerlo); a mano: gcloud run jobs execute $JOB_OPS --region $REGION"
fi

# -------------------------------------------------------------------------------------------------------------------------- 10
step "10. Monitoreo y alertas"
EMAIL="$(gcloud secrets versions access latest --secret "$(secret_name alert-email)" 2>/dev/null || true)"
[ -n "$EMAIL" ] || read -rp "   Correo para las alertas (Enter = omitir alertas): " EMAIL
if [ -n "$EMAIL" ]; then
  CHANNEL="$(gcloud beta monitoring channels list --filter "displayName=\"Golden alertas\"" --format 'value(name)' | head -n1)"
  [ -n "$CHANNEL" ] || CHANNEL="$(gcloud beta monitoring channels create --display-name "Golden alertas" --type email \
                                   --channel-labels "email_address=$EMAIL" --format 'value(name)')"
  # Versión anterior: chequeo «golden-healthz» a /healthz y su alerta. En Cloud Run /healthz da 404 del propio Google (reserva las rutas que
  # terminan en «z»), así que fallaban siempre: se borran y se crean «golden-health» a /health y su alerta nueva.
  OLD_ID="$(gcloud monitoring uptime list-configs --filter "displayName=\"golden-healthz${SUFFIX}\"" --format 'value(name)' | head -n1)"
  OLD_POLICY="$(gcloud monitoring policies list --filter "displayName=\"Golden ${GOLDEN_ENV}: /healthz no responde\"" --format 'value(name)' | head -n1)"
  [ -z "$OLD_POLICY" ] || gcloud monitoring policies delete "$OLD_POLICY" --quiet >/dev/null
  [ -z "$OLD_ID" ] || gcloud monitoring uptime delete "${OLD_ID##*/}" --quiet >/dev/null
  UPTIME="golden-health${SUFFIX}"
  WEB_HOST="$(run_url "$SVC_WEB" | sed 's#https://##')"
  CHECK_ID="$(gcloud monitoring uptime list-configs --filter "displayName=\"$UPTIME\"" --format 'value(name)' | head -n1 | sed 's#.*/##')"
  [ -n "$CHECK_ID" ] || CHECK_ID="$(gcloud monitoring uptime create "$UPTIME" --resource-type uptime-url \
      --resource-labels "host=$WEB_HOST,project_id=$PROJECT_ID" --path /health --protocol https --period 1 --timeout 10 \
      --format 'value(name)' | sed 's#.*/##')"
  policy() {   # nombre  archivo-json
    if [ -z "$(gcloud monitoring policies list --filter "displayName=\"$1\"" --format 'value(name)')" ]; then
      gcloud monitoring policies create --policy-from-file "$2" --notification-channels "$CHANNEL" >/dev/null
    fi
  }
  cat > "$TMP/p1.json" <<EOF
{"displayName": "Golden ${GOLDEN_ENV}: /health no responde", "combiner": "OR",
 "conditions": [{"displayName": "chequeo de disponibilidad fallando", "conditionThreshold": {
   "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"${CHECK_ID}\" AND resource.type=\"uptime_url\"",
   "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "120s", "trigger": {"count": 1},
   "aggregations": [{"alignmentPeriod": "1200s", "perSeriesAligner": "ALIGN_NEXT_OLDER", "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}]}}]}
EOF
  cat > "$TMP/p2.json" <<EOF
{"displayName": "Golden ${GOLDEN_ENV}: un Job falló (respaldos, migraciones o carga)", "combiner": "OR",
 "conditions": [{"displayName": "ejecución fallida", "conditionThreshold": {
   "filter": "metric.type=\"run.googleapis.com/job/completed_execution_count\" AND resource.type=\"cloud_run_job\" AND metric.label.result=\"failed\" AND resource.label.job_name=one_of(\"${JOB_OPS}\",\"${JOB_BULK}\",\"${JOB_MIGRATE}\")",
   "comparison": "COMPARISON_GT", "thresholdValue": 0, "duration": "0s", "trigger": {"count": 1},
   "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM"}]}}]}
EOF
  cat > "$TMP/p3.json" <<EOF
{"displayName": "Golden ${GOLDEN_ENV}: errores 5xx", "combiner": "OR",
 "conditions": [{"displayName": "más de 20 respuestas 5xx en 5 minutos", "conditionThreshold": {
   "filter": "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND metric.label.response_code_class=\"5xx\" AND resource.label.service_name=one_of(\"${SVC_WEB}\",\"${SVC_PUBLICO}\",\"${SVC_BIOMETRIA}\")",
   "comparison": "COMPARISON_GT", "thresholdValue": 20, "duration": "0s", "trigger": {"count": 1},
   "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM", "crossSeriesReducer": "REDUCE_SUM"}]}}]}
EOF
  policy "Golden ${GOLDEN_ENV}: /health no responde" "$TMP/p1.json"
  policy "Golden ${GOLDEN_ENV}: un Job falló (respaldos, migraciones o carga)" "$TMP/p2.json"
  policy "Golden ${GOLDEN_ENV}: errores 5xx" "$TMP/p3.json"
  ok "canal de correo, chequeo /health cada minuto (sin tocar la base) y 3 alertas"
else
  ok "alertas omitidas"
fi

# -------------------------------------------------------------------------------------------------------------------------- 11
step "11. Presupuesto"
# Solo se crea uno si NINGÚN presupuesto de la cuenta de facturación cubre este proyecto (uno filtrado a este proyecto, o uno de toda la
# cuenta). Si ya hay (p. ej. «GoldenWeb mensual», COP 160.000), solo se informa. Si no se pueden leer los presupuestos, NO se crea nada.
BILLING="$(gcloud billing projects describe "$PROJECT_ID" --format 'value(billingAccountName)' | sed 's#billingAccounts/##')"
if ! BUDGETS="$(gcloud billing budgets list --billing-account "$BILLING" --format json 2>/dev/null)"; then
  echo "   ⚠ No se pudieron leer los presupuestos de la cuenta $BILLING (permiso billing.budgets.list): no se crea ninguno. Revísalo en la consola."
else
  COVERING="$(BUDGETS_JSON="$BUDGETS" python3 - "$PROJECT_NUMBER" "$PROJECT_ID" <<'EOF'
import json, os, sys
number, pid = sys.argv[1], sys.argv[2]
for b in json.loads(os.environ["BUDGETS_JSON"] or "[]"):
    projects = (b.get("budgetFilter") or {}).get("projects") or []
    if not projects or f"projects/{number}" in projects or f"projects/{pid}" in projects:
        amount = (b.get("amount") or {}).get("specifiedAmount") or {}
        print(f"«{b.get('displayName', b['name'])}» {amount.get('units', '?')} {amount.get('currencyCode', '')}".strip())
EOF
)"
  if [ -n "$COVERING" ]; then
    ok "ya hay presupuesto para este proyecto, no se crea otro: $(echo "$COVERING" | paste -sd ';' -)"
  else
    read -rp "   No hay presupuesto para este proyecto. Monto mensual EN LA MONEDA de la cuenta (p. ej. 160000COP; Enter = no crear): " AMOUNT
    if [ -n "$AMOUNT" ]; then
      gcloud billing budgets create --billing-account "$BILLING" --display-name "Golden nube" --budget-amount "$AMOUNT"         --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0 --filter-projects "projects/$PROJECT_ID"
      ok "creado, con avisos al 50, 90 y 100 % (avisan, no apagan nada)"
    fi
  fi
fi

# -------------------------------------------------------------------------------------------------------------------------- 12
step "12. Firebase Hosting (sitio ${FIREBASE_SITE:-ninguno})"
if [ -z "$FIREBASE_SITE" ]; then
  ok "sin Firebase en este entorno (staging en el mismo proyecto): se prueba por la URL de Cloud Run, que sirve toda la app"
elif command -v firebase >/dev/null; then
  firebase projects:addfirebase "$PROJECT_ID" >/dev/null 2>&1 || true                   # si ya es proyecto de Firebase, no pasa nada
  firebase hosting:sites:create "$FIREBASE_SITE" --project "$PROJECT_ID" >/dev/null 2>&1 || true
  if firebase hosting:sites:get "$FIREBASE_SITE" --project "$PROJECT_ID" >/dev/null 2>&1; then ok "sitio listo; el contenido lo publica el workflow"
  else echo "   ⚠ No se pudo crear el sitio (¿falta «firebase login --no-localhost»?). Vuelve a correr el script después."; fi
else
  echo "   ⚠ Sin CLI de Firebase: npm install -g firebase-tools, y vuelve a correr el script."
fi

# -------------------------------------------------------------------------------------------------------------------------- resumen
cat <<EOF

LISTO ($GOLDEN_ENV). Configura en GitHub → Settings → Environments → «$GOLDEN_ENV» → Variables (no son secretos):
  GCP_PROJECT_ID      = $PROJECT_ID
  GCP_REGION          = $REGION
  GCP_WIF_PROVIDER    = ${POOL_PATH}/providers/${PROVIDER}
  GCP_DEPLOYER        = $(sa_email "$SA_DEPLOYER")
  FIREBASE_SITE       = ${FIREBASE_SITE:-(dejar VACÍA: este entorno no usa Firebase Hosting)}
Web (Cloud Run): $(run_url "$SVC_WEB")   ·   Dirección pública: $PUBLIC_BASE_URL
EOF
