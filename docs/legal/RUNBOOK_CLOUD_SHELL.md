# Runbook de Cloud Shell para el piloto (staging primero; producción igual con el sufijo vacío)

> Claude no ejecuta `gcloud`. Todo esto lo corre Juan David. Variables que se repiten: `REGION=us-east4` (la región decidida) y, en staging, el sufijo `-staging` en los nombres.

## 1. Actualizar los datos de la empresa y el correo de privacidad (staging)

El despliegue normal (`deploy.sh`) ya los toma de `deploy/gcp/env/common.yaml`. Para que rijan YA, sin esperar un despliegue:

```bash
REGION=us-east4
VARS='PRIVACY_EMAIL=soporteit@goldenlogisticas.com,LEGAL_PRIVACY_EMAIL=soporteit@goldenlogisticas.com,COMPANY_NAME=Golden Eventos y Logística S.A.S.,COMPANY_NIT=901542833-2,DOMAIN=golden-eventos.com'
for S in golden-web-staging golden-publico-staging golden-biometria-staging; do
  gcloud run services update "$S" --region "$REGION" --update-env-vars "$VARS"
done
for J in golden-ops-staging golden-bulk-staging; do
  gcloud run jobs update "$J" --region "$REGION" --update-env-vars "$VARS"
done
```

`LEGAL_PRIVACY_EMAIL` queda como alias obsoleto (el código lee primero `PRIVACY_EMAIL`).

## 2. Cola de los cálculos faciales (vector tras la aceptación)

El vector se calcula en el servicio de biometría (2 CPU, 2 Gi), con una cola propia de **2 despachos simultáneos** y espera creciente (10 s a 300 s), con el mismo token OIDC y la misma cuenta. Así el cálculo no le quita CPU a la puerta.

```bash
bash deploy/gcp/faces_queue.sh staging        # crea o corrige la cola golden-faces-staging y deja el permiso de encolar
# luego, un despliegue normal: deploy.sh detecta la cola y agrega CLOUD_TASKS_FACES_QUEUE y CLOUD_TASKS_FACES_URL
```

Sin la cola, todo sigue funcionando por la cola general (la general ejecuta también los cálculos faciales). Para comprobar: en `/sistema`, la cola sin atrasos; y en Cloud Tasks, la cola `golden-faces-staging` con «max concurrent dispatches = 2».

## 3. Medir cuánto tarda el vector (`bench-vector`) con 10 y 25 jitters

Usa una imagen sintética (sin datos personales) y mide solo el cálculo. El job de operaciones tiene 1 CPU y 1 Gi; para igualar al servicio de biometría se sube TEMPORALMENTE a 2 CPU y 2 Gi y se restaura al final.

```bash
REGION=us-east4; JOB=golden-ops-staging
gcloud run jobs update "$JOB" --region "$REGION" --cpu 2 --memory 2Gi
gcloud run jobs execute "$JOB" --region "$REGION" --args=-m,app.ops_runner,bench-vector --update-env-vars BENCH_REPS=5 --wait
gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB\" AND textPayload:\"jitters_10_ms\"" --limit 1 --format='value(textPayload)'
gcloud run jobs update "$JOB" --region "$REGION" --cpu 1 --memory 1Gi          # RESTAURAR (los valores de deploy.sh)
gcloud run jobs update "$JOB" --region "$REGION" --remove-env-vars BENCH_REPS
```

Lo que imprime: `jitters_10_ms` y `jitters_25_ms` con mínimo, mediana y máximo en milisegundos, y los CPU visibles. Si la mediana con 25 jitters pasa de unos 12 s con 2 CPU, o si la puerta se siente lenta mientras corre, se separa el cálculo después del piloto.

## 4. Plan de despliegue de las migraciones 0051 a 0059 (corto)

**Qué hay:** 0052 y 0053 (estados de evento, filas por página), 0054 (`audit_consent_logs`), 0055 a 0059 (configuración de autorización, pre-cálculo, menores, supresión, `/aceptar`). Todas son **aditivas** (columnas con valor por defecto, tablas nuevas): el código viejo las ignora.

**Orden:**
1. `bash deploy/gcp/faces_queue.sh staging` (una vez).
2. Despliegue normal (`deploy.sh staging <imagen>` o el workflow). Dentro de él, **primero** corre el Job `golden-migrate-staging` (`alembic upgrade head` con la conexión directa del dueño) y solo si termina bien se actualizan los servicios.
3. Comprobar: `/ready` en verde, `/sistema` sin alertas rojas y una prueba rápida de la pantalla de autorización con un evento de prueba.

**Qué corre al arrancar:** ninguna migración. Solo la verificación de la clave facial (en producción, sin `FACE_ENCRYPTION_KEY` el servicio no arranca) y el precalentamiento del motor facial.

**Cómo se revierte:** se vuelve a la revisión anterior de los servicios (Cloud Run guarda las revisiones; ver `docs/15`). **No se hace `alembic downgrade` en producción**: las columnas nuevas no estorban al código viejo, y bajar la 0054 borraría `audit_consent_logs`, que es prueba legal de 3 años (en una copia de pruebas sí funciona la bajada completa).

**Comprobado (2026-10-06, base local con datos de muestra: cliente, eventos, personas con vector, ingresos):** subir 0051 a head conserva todas las filas; los eventos quedan con `controller_mode='golden'`, `consent_prompt_mode='once'` y las opciones de rostro apagadas; subir dos veces es inofensivo; bajar a 0051 y volver a subir funciona. No pude probarlo sobre la copia real de staging (no tengo acceso a Neon): para repetirlo allí, crear una rama de Neon desde staging y correr `alembic upgrade head` contra ella con `DIRECT_DATABASE_URL`.
