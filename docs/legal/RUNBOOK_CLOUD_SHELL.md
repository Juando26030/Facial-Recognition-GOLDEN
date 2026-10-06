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

## 5. Cola golden-faces-staging: crearla, comprobarla, ver atascos y reintentar (orden exacto)

1. **Crearla** (una sola vez; idempotente): `bash deploy/gcp/faces_queue.sh staging` (la región por defecto es `us-east4`; para otra: `REGION=<región> bash deploy/gcp/faces_queue.sh staging`). Ya creada en staging el 6 de octubre de 2026.
2. **Verificar que existe y sus límites:**
   ```bash
   gcloud tasks queues describe golden-faces-staging --location us-east4 --format="yaml(name,state,rateLimits,retryConfig)"
   ```
   Debe decir `state: RUNNING`, `maxConcurrentDispatches: 2`, `maxAttempts: 5`, `maxDoublings: 4`, `minBackoff: 10s`, `maxBackoff: 300s`.
3. **Desplegar** (el push de la rama de staging o `deploy.sh staging <imagen>`): `deploy.sh` detecta la cola y agrega `CLOUD_TASKS_FACES_QUEUE` y `CLOUD_TASKS_FACES_URL` a los servicios. Comprobarlo:
   ```bash
   gcloud run services describe golden-publico-staging --region us-east4 --format=json | grep -o 'CLOUD_TASKS_FACES_[A-Z]*'
   ```
   Deben salir las dos variables, y lo mismo en `golden-web-staging` y `golden-biometria-staging`.
4. **Comprobar que una aceptación de prueba la usa:** crear un evento de prueba con rostro, aceptar desde `/aceptar/<código>` (o en el quiosco) y subir la selfie. Luego:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="golden-biometria-staging" AND httpRequest.requestUrl:"/internal/faces/run"' --limit 5 --format='value(timestamp,httpRequest.status)'
   ```
   Debe haber una petición con estado `200` pocos segundos después de la aceptación. En el quiosco, el estado de esa persona pasa de «se está preparando» a rostro listo.
5. **Ver tareas atascadas:** `gcloud tasks list --queue golden-faces-staging --location us-east4` (lo normal es que esté vacía en segundos). Una tarea con `dispatchCount` alto y `lastAttempt` con error indica que el servicio de biometría no responde. En `/sistema` (admin), el ítem «Cola de trabajos» muestra pendientes, el más antiguo y fallidos. El barrido horario (`golden-ops`) vuelve a avisar a la cola facial si quedó trabajo pendiente.
6. **Reintentar lo que se agotó** (estado fallido tras 3 intentos): devuelve esos cálculos a la cola con los intentos en cero y despierta la cola facial.
   ```bash
   gcloud run jobs execute golden-ops-staging --region us-east4 --args=-m,app.ops_runner,retry-face-jobs --wait
   ```
7. **Pausar o vaciar en una emergencia:** `gcloud tasks queues pause golden-faces-staging --location us-east4` (y `resume`). Las personas siguen entrando por cédula o QR; los cálculos esperan en la tabla de trabajos.

## 6. Probar las migraciones en una rama de Neon creada desde staging

1. **Crear la rama:** consola de Neon → proyecto de staging → Branches → «Create branch» → desde la rama de staging, «Current data», nombre `prueba-migraciones`. Copiar su cadena de conexión **directa** (sin `-pooler`) con el rol dueño.
2. **Antes de migrar, guardar la foto del estado** (en Cloud Shell, con `export DB='<cadena directa de la rama>'`):
   ```bash
   for T in tenants events users event_attendees access_logs print_logs form_submissions form_payments; do echo -n "$T "; psql "$DB" -Atc "select count(*) from $T"; done | tee antes.txt
   psql "$DB" -Atc "select version_num from alembic_version" | tee version_antes.txt
   ```
3. **Migrar la rama** (no toca staging): en un clon de la rama `integracion/piloto-legal`:
   ```bash
   python3 -m venv v && . v/bin/activate
   grep -viE '^(face[-_]recognition|dlib)' requirements.txt > /tmp/req.txt && pip install -r /tmp/req.txt
   export DATABASE_URL="$DB"
   alembic heads            # debe decir UNA sola cabeza: 0061_privacy_requests
   alembic upgrade head     # aplica 0052 a 0061 (las que falten según la versión de staging)
   ```
4. **Después, comparar:**
   ```bash
   for T in tenants events users event_attendees access_logs print_logs form_submissions form_payments; do echo -n "$T "; psql "$DB" -Atc "select count(*) from $T"; done | tee despues.txt
   diff antes.txt despues.txt && echo "IGUALES: no se perdió ninguna fila"
   psql "$DB" -Atc "select version_num from alembic_version"          # debe ser 0061_privacy_requests
   psql "$DB" -Atc "select controller_mode, consent_prompt_mode, aceptar_enabled, precalculo_autorizado, facial_enabled from events limit 5"      # golden / once / f / f / como estaba
   psql "$DB" -Atc "select count(*) from pg_trigger where tgrelid='audit_consent_logs'::regclass and not tgisinternal"                        # debe dar 2 (solo inserción)
   psql "$DB" -Atc "select to_regclass('web_acceptances'), to_regclass('suppressed_people'), to_regclass('privacy_requests'), to_regclass('privacy_request_counters')"   # las cuatro existen
   psql "$DB" -Atc "select has_table_privilege('golden_app','audit_consent_logs','UPDATE'), has_table_privilege('golden_app','audit_consent_logs','INSERT')"      # f y t
   ```
   Los conteos antes y después deben ser iguales (las migraciones solo agregan). Si `golden_app` no existe en la rama, la última consulta falla: es normal, el permiso lo fija `scripts/neon_app_role.py`.
5. **Repetir la subida** (`alembic upgrade head`) debe terminar sin cambios.
6. **Desechar la rama:** consola de Neon → Branches → `prueba-migraciones` → menú → Delete (o `neonctl branches delete prueba-migraciones --project-id <id>`). Borrar solo esa rama: nunca la de staging ni la de producción. Antes, confirmar que ningún servicio tiene su cadena.

## 7. Qué revisar en el panel de staging después de desplegar

- `/sistema` (admin): todo en verde; «Cola de trabajos» sin atrasos; «Eventos por finalizar» sin alertas; versión nueva (commit).
- `/ready` y `/health` en 200 en los tres servicios.
- Un evento de prueba: Parámetros → «Reconocimiento facial: paso guiado» muestra el resumen sin faltantes (con COMPANY_NAME, COMPANY_NIT y PRIVACY_EMAIL definidos).
- Una aceptación de prueba (sección 5, paso 4) y el comando de `bench-vector` (sección 3), restaurando el job a 1 CPU y 1 Gi.
