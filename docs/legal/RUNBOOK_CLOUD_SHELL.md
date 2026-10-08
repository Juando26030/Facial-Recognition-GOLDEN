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

## 8. Arreglar YA la cola facial en staging (variables ausentes tras el despliegue de a5446ab)

**Qué pasó:** `deploy.sh` agrega `CLOUD_TASKS_FACES_QUEUE` y `CLOUD_TASKS_FACES_URL` solo si puede ver la cola. La cuenta de despliegue de GitHub (`golden-deployer-staging`) no tenía ningún permiso sobre Cloud Tasks, la consulta falló con «permiso denegado» y el script tragaba ese error: siguió como si la cola no existiera. (Corregido: ahora un error detiene el despliegue con el motivo a la vista, y `faces_queue.sh` concede el permiso.)

**Paso 1: conceder los permisos que faltan** (idempotente; es el mismo script de siempre, ahora completo):
```bash
bash deploy/gcp/faces_queue.sh staging
```
Deja: `roles/cloudtasks.viewer` sobre la cola para `golden-deployer-staging` (leer que existe) y, para `golden-ops-staging`, `roles/cloudtasks.enqueuer` sobre la cola y `roles/iam.serviceAccountUser` sobre `golden-invoker-staging` (para que el barrido horario despierte a la cola).

**Paso 2: fijar las dos variables YA** en los tres servicios y en el Job de operaciones (seguro de repetir: `--update-env-vars` solo pone o reemplaza esas dos):
```bash
REGION=us-east4
PROJECT_ID=$(gcloud config get-value project)
BIO_URL=$(gcloud run services describe golden-biometria-staging --region "$REGION" --format='value(status.url)')
FACES_Q="projects/${PROJECT_ID}/locations/${REGION}/queues/golden-faces-staging"
VARS="CLOUD_TASKS_FACES_QUEUE=${FACES_Q},CLOUD_TASKS_FACES_URL=${BIO_URL}/internal/faces/run"
echo "$VARS"      # comprueba que ambos valores se vean completos antes de seguir
for S in golden-web-staging golden-publico-staging golden-biometria-staging; do
  gcloud run services update "$S" --region "$REGION" --update-env-vars "$VARS"
done
gcloud run jobs update golden-ops-staging --region "$REGION" --update-env-vars "$VARS"
```
El valor de `CLOUD_TASKS_FACES_URL` es la dirección del servicio de biometría más `/internal/faces/run` (por ejemplo `https://golden-biometria-staging-<número>.us-east4.run.app/internal/faces/run`). Es también la «audiencia» del token: el servicio la compara con esa misma variable.

**Paso 3: comprobar:**
```bash
for S in golden-web-staging golden-publico-staging golden-biometria-staging; do echo -n "$S: "; gcloud run services describe "$S" --region us-east4 --format=json | grep -o 'CLOUD_TASKS_FACES_[A-Z]*' | sort -u | tr '\n' ' '; echo; done
```
Cada servicio debe mostrar `CLOUD_TASKS_FACES_QUEUE CLOUD_TASKS_FACES_URL`. Luego la prueba de aceptación de la sección 5, paso 4.

**El próximo despliegue** (con el arreglo) pone esas variables solo; si la cuenta de despliegue no puede leer la cola, el despliegue se detiene con el mensaje «roles/cloudtasks.viewer sobre esa cola» en vez de omitirlas en silencio.

## 9. CORS del bucket (subida directa de archivos grandes desde el navegador)

**Qué es:** «Adjuntar Base de Datos» y los archivos de los formularios suben DIRECTO al bucket con una URL firmada (PUT). El navegador pregunta antes al bucket si ese origen puede hacerlo (CORS); si el origen no está en la lista, la subida falla con «No 'Access-Control-Allow-Origin' header».

**Por qué falló en staging (8-oct-2026):** Cloud Run da a cada servicio DOS direcciones válidas: la determinista (`golden-web-staging-<número de proyecto>.us-east4.run.app`) y la corta con hash (`golden-web-staging-<hash>-uk.a.run.app`). El script solo conocía la primera; el navegador entró por la segunda. La segunda no se puede calcular, solo leer del servicio, y al correr el bootstrap el servicio aún no existía.

**Aplicarlo (idempotente: lee el bucket, compara y solo cambia si difiere):**
```bash
git pull   # rama producto/legal-piloto o integracion/piloto-legal, la que tenga deploy/gcp/cors.sh
bash deploy/gcp/cors.sh staging
```
Imprime la lista de orígenes aplicada (debe incluir las dos direcciones del servicio web). `bootstrap.sh` lo corre solo al final (después de crear los servicios).

**Producción:** lleva el dominio (`https://app.golden-eventos.com`) y los sitios de Firebase, y NO las direcciones `run.app`. Para verificar producción por la dirección de Cloud Run antes del dominio (guía de producción, paso 6): `CORS_INCLUDE_RUN_URLS=1 bash deploy/gcp/cors.sh production`, y al terminar volver a correrlo SIN la variable.

**Comprobar:**
```bash
gcloud storage buckets describe gs://$(gcloud config get-value project)-golden-staging-us-east4 --format='yaml(cors_config)'
```

## 10. Correo (enlaces de autorización, escarapela virtual, constancia): cómo envía hoy y qué falta

**Cómo envía hoy `app/mailer.py`** (tres caminos, en este orden):
1. **Microsoft Graph (el recomendado):** si existen las cuatro variables `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` y `GRAPH_SENDER` (el buzón remitente, p. ej. `soporteit@goldenlogisticas.com`). Pide un token de aplicación y envía con `POST /users/<buzón>/sendMail`.
2. **SMTP:** si no hay Graph y existe `SMTP_HOST` (y `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`).
3. **Ninguno:** el correo NO sale; se guarda como archivo `.eml` en el almacenamiento (`outbox/` del bucket). El sistema responde «Ni Microsoft Graph ni SMTP están configurados — el correo quedó guardado en …».
En staging el asunto lleva `[STAGING]` (`DEPLOY_ENV=staging`). La configuración NO está en la base de datos: son variables de entorno, que en Cloud Run vienen de **Secret Manager**.

**Qué falta:** en staging solo existen `LEGAL_EMAIL`, `LEGAL_PRIVACY_EMAIL` y `PRIVACY_EMAIL` (textos legales) y el secreto `golden-alert-email-staging` (a quién avisa el sistema). Los cuatro secretos del correo son OPCIONALES en el bootstrap y se omitieron: `golden-azure-tenant-id-staging`, `golden-azure-client-id-staging`, `golden-azure-client-secret-staging` y `golden-graph-sender-staging` (en producción, los mismos sin el sufijo `-staging`). Mientras no existan, nada sale al exterior (camino 3).

**Pasos para el administrador de Microsoft 365 (una sola vez; sirve para staging y producción):**
1. Entra a **entra.microsoft.com** → Identidad → Aplicaciones → **Registros de aplicaciones** → **Nuevo registro**. Nombre: «Golden Eventos - Envío de correo». Tipos de cuenta: «Solo este directorio organizativo». Sin URI de redirección → **Registrar**.
2. En la aplicación: **Permisos de API** → Agregar un permiso → **Microsoft Graph** → **Permisos de aplicación** (NO delegados) → marca **Mail.Send** → Agregar. Luego pulsa **«Conceder consentimiento de administrador para <la organización>»** (lo hace un administrador global o de aplicaciones). Debe quedar con la marca verde «Concedido». Sin este paso el token se emite pero Graph rechaza el envío.
3. **Certificados y secretos** → Nuevo secreto de cliente → descripción «staging» (otro llamado «producción» para el otro entorno) → vigencia de 12 o 24 meses → copia el **VALOR** en ese momento (solo se muestra una vez; no el «Id. del secreto»).
4. En **Información general** copia el **Id. de aplicación (cliente)** y el **Id. de directorio (inquilino)**.
5. **Buzón remitente:** el que firmará los correos, `soporteit@goldenlogisticas.com` (puede ser un buzón compartido). La aplicación no necesita su contraseña.
6. **Recomendado (seguridad):** restringir la aplicación a ese único buzón y a solo enviar. Las *Application Access Policies* ya las sustituye **RBAC for Applications**: los comandos exactos, la prueba y qué permisos quitar de Entra están en la **sección 11**. Sin esto la aplicación podría enviar como cualquier buzón del tenant (y, si tiene `Mail.Read*`, leerlos).
7. **Que no caiga en spam:** en el portal de seguridad (security.microsoft.com → Correo y colaboración → Directivas → Autenticación de correo electrónico → DKIM) activa DKIM para `goldenlogisticas.com`; en el DNS del dominio debe existir el SPF que incluye `spf.protection.outlook.com` y un DMARC (al menos `p=none`).
8. **Límites:** Exchange Online permite unos 30 mensajes por minuto por buzón y 10.000 destinatarios por día. El envío masivo de enlaces irá a un ritmo de 25 por minuto o menos.

**Pasos en Cloud Shell (tú), con los cuatro valores en la mano:**
```bash
git fetch && git checkout integracion/piloto-legal && git pull
bash deploy/gcp/bootstrap.sh staging
```
El script es idempotente: lo que ya existe no se toca y, cuando pregunta por los opcionales (`azure-tenant-id`, `azure-client-id`, `azure-client-secret`, `graph-sender`), pegas cada valor (no se ve en pantalla). También da el permiso de lectura a las cuentas de la aplicación y de operaciones. Después hay que **redesplegar** (cualquier push a `migra/fase1-2`, o «Run workflow» del despliegue) para que los servicios monten los secretos. Producción: `bash deploy/gcp/bootstrap.sh production` cuando se prepare el corte.

**Comprobar que sale:** en el evento de pruebas con escarapela digital activa, **Parámetros → correo de la escarapela digital → «Enviar prueba»** a un buzón tuyo; debe llegar con el asunto `[STAGING] [PRUEBA] …`. Si el detalle dice «Ni Microsoft Graph ni SMTP están configurados», el servicio aún no tiene los secretos (falta redesplegar); si dice «No se pudo enviar el correo (Graph) …», el mensaje trae el motivo de Microsoft (casi siempre falta el consentimiento de administrador del paso 2 o la política del paso 6).

## 11. Correo con mínimo privilegio: solo enviar, solo como `soporteit@goldenlogisticas.com` (RBAC para aplicaciones), carga de los secretos y rotación

> Reemplaza el paso 6 de la sección 10: las *Application Access Policies* (`New-ApplicationAccessPolicy`) las sustituye «RBAC for Applications» de Exchange Online (Microsoft, doc. actualizada el 21-ago-2026). No se ejecuta nada desde el repositorio: son comandos para el administrador y para ti en Cloud Shell.

### 11.1 Qué usa el código de Graph (evidencia) y qué permiso basta
- **Solo se ENVÍA.** En todo el repositorio, Graph aparece en dos líneas de `app/mailer.py`: el token con `scope = https://graph.microsoft.com/.default` (línea 38) y `POST https://graph.microsoft.com/v1.0/users/{GRAPH_SENDER}/sendMail` (línea 69), con `saveToSentItems = false`. Los adjuntos (`attachments`) viajan DENTRO de ese `sendMail`; no se lee ningún adjunto.
- **No hay correo entrante:** no existe `imaplib`, `poplib`, `/messages`, `mailFolders` ni lectura de buzón en ningún módulo (búsqueda en `app/`, `scripts/`, `deploy/`, `static/`, `templates/`). Quien llama a `send_mail` solo envía: restablecer contraseña, informe final, alertas del Job de operaciones, invitaciones, escarapela digital, enlace personal de autorización y constancia.
- **Conclusión:** basta **`Mail.Send` de tipo Aplicación**. `Mail.Read`, `Mail.ReadBasic`, `Mail.ReadBasic.All` y `Mail.ReadWrite` NO se usan y hoy permiten leer (y con `ReadWrite`, modificar y borrar) **todos los buzones de la organización** si alguien obtiene el secreto: hay que quitarlos. `User.Read` delegado no interviene (el flujo es de aplicación, sin usuario) y también se puede quitar.

### 11.2 Limitar la aplicación a un solo buzón (Exchange Online, RBAC for Applications)
Quién: un administrador con el rol **Organization Management** de Exchange (y el de **Exchange Administrator** en Entra). Módulo: `ExchangeOnlineManagement` (`Install-Module ExchangeOnlineManagement` si no está).
**Importante (Microsoft):** los permisos de Entra y los de RBAC *se suman*. Si `Mail.Send` sigue concedido en toda la organización en Entra, el alcance de RBAC **no limita nada**. Por eso el orden es: primero crear la asignación RBAC, comprobarla y **después** quitar los permisos de Entra.

1. **Datos de Entra** (portal entra.microsoft.com → Aplicaciones empresariales → «Mailer GoldenWeb 2.0»; NO el registro de aplicaciones, ahí el «Id. de objeto» es otro): `AppId` = `2a1f1fb1-30eb-4c23-b355-5163e269a459` y el **Id. de objeto** de la aplicación empresarial (en los comandos, `<OBJECT_ID_APP_EMPRESARIAL>`).
2. **Conectar y comprobar el buzón** (PowerShell):
```powershell
Connect-ExchangeOnline -UserPrincipalName <admin@goldenlogisticas.com>
Get-Mailbox soporteit@goldenlogisticas.com | Format-List Alias,PrimarySmtpAddress,RecipientTypeDetails
```
3. **Puntero a la aplicación en Exchange:**
```powershell
New-ServicePrincipal -AppId 2a1f1fb1-30eb-4c23-b355-5163e269a459 -ObjectId <OBJECT_ID_APP_EMPRESARIAL> -DisplayName "Mailer GoldenWeb 2.0"
```
4. **Alcance = ese único buzón** (usa el `Alias` que mostró el paso 2; aquí `soporteit`):
```powershell
New-ManagementScope -Name "Mailer GoldenWeb - solo soporteit" -RecipientRestrictionFilter "Alias -eq 'soporteit'"
```
5. **Rol de solo enviar, con ese alcance:**
```powershell
New-ManagementRoleAssignment -App <OBJECT_ID_APP_EMPRESARIAL> -Role "Application Mail.Send" -CustomResourceScope "Mailer GoldenWeb - solo soporteit"
```
6. **Prueba de la regla** (simula lo que Exchange permitirá; no incluye lo que Entra conceda aparte):
```powershell
Test-ServicePrincipalAuthorization -Identity 2a1f1fb1-30eb-4c23-b355-5163e269a459 -Resource soporteit@goldenlogisticas.com | Format-Table
Test-ServicePrincipalAuthorization -Identity 2a1f1fb1-30eb-4c23-b355-5163e269a459 -Resource <cualquier-otro-buzon>@goldenlogisticas.com | Format-Table
```
   **Debe verse:** fila `Application Mail.Send` con `InScope = True` para `soporteit` y `InScope = False` para el otro buzón. Si el primero sale `False`, el filtro del paso 4 no apunta al buzón (revisa el `Alias`).
7. **Quitar de Entra los permisos que sobran** (con Microsoft Graph PowerShell; quitar la fila en «Permisos de API» del registro NO revoca lo ya concedido a la aplicación empresarial):
```powershell
Connect-MgGraph -Scopes "AppRoleAssignment.ReadWrite.All","Application.Read.All"
$sp    = Get-MgServicePrincipal -Filter "appId eq '2a1f1fb1-30eb-4c23-b355-5163e269a459'"
$graph = Get-MgServicePrincipal -Filter "appId eq '00000003-0000-0000-c000-000000000000'"
$as    = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $sp.Id -All
$as | ForEach-Object { $r = $graph.AppRoles | Where-Object Id -eq $_.AppRoleId; [pscustomobject]@{ Permiso = $r.Value; AsignacionId = $_.Id } }
# quita TODOS los Mail.* de Entra (el envío queda cubierto por RBAC, solo para soporteit)
$as | Where-Object { ($graph.AppRoles | Where-Object Id -eq $_.AppRoleId).Value -like 'Mail.*' } | ForEach-Object { Remove-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $sp.Id -AppRoleAssignmentId $_.Id }
```
   (Si prefieres el portal: Aplicaciones empresariales → la aplicación → Permisos → revocar cada `Mail.*`.) Opcional: borrar también `User.Read` del registro.
8. **Esperar** de 30 minutos a 2 horas: Exchange guarda en caché los permisos (el comando de prueba del paso 6 no la usa, el envío real sí).
9. **Prueba real** desde Cloud Shell (no imprime el secreto; el token se descarta al terminar):
```bash
read -rp "Tenant ID: " T; read -rp "Client ID: " C; read -rsp "Client secret (no se ve): " S; echo
TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/$T/oauth2/v2.0/token" -d "client_id=$C" --data-urlencode "client_secret=$S" -d "scope=https://graph.microsoft.com/.default" -d "grant_type=client_credentials" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"); unset S
read -rp "Tu correo, para recibir la prueba: " TO
enviar() { curl -s -o /dev/null -w "$1 -> HTTP %{http_code}\n" -X POST "https://graph.microsoft.com/v1.0/users/$1/sendMail" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"message\":{\"subject\":\"[PRUEBA RBAC] $1\",\"body\":{\"contentType\":\"Text\",\"content\":\"prueba\"},\"toRecipients\":[{\"emailAddress\":{\"address\":\"$TO\"}}]},\"saveToSentItems\":false}"; }
enviar soporteit@goldenlogisticas.com
enviar <otro-buzon>@goldenlogisticas.com
unset TOKEN
```
   **Debe verse:** `soporteit@… -> HTTP 202` (y llega el correo `[PRUEBA RBAC]`) y `<otro-buzon>@… -> HTTP 403` (`ErrorAccessDenied`). Mientras no hayas quitado los `Mail.*` de Entra (paso 7) o no haya pasado la caché, el segundo puede dar 202: es la señal de que todavía falta uno de los dos.

### 11.3 Cargar los cuatro secretos de correo de STAGING (lectura silenciosa)
**De qué rama:** `migra/fase1-2` (staging despliega desde ahí). Hoy está en el commit `0c2baaa` y `deploy/gcp/bootstrap.sh` no cambia en las ramas siguientes (hasta `f48431c` es idéntico), así que sirve cualquier commit de esa rama.
```bash
cd ~ && { [ -d Facial-Recognition ] || git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN.git Facial-Recognition; } && cd Facial-Recognition
git fetch origin && git checkout migra/fase1-2 && git pull --ff-only && git log --oneline -1
gcloud config set run/region us-east4
```
**Opción recomendada: solo los cuatro secretos** (hace lo mismo que `put_secret` del bootstrap: crea, guarda la versión y da los permisos de lectura; nada se imprime):
```bash
SUF=-staging; PROJECT=$(gcloud config get-value project)
cargar() {  # nombre-corto
  local s="golden-$1${SUF}" v
  if gcloud secrets versions access latest --secret "$s" >/dev/null 2>&1; then echo "$s ya tiene valor (no se toca)"; return; fi
  if [ "$1" = graph-sender ]; then read -rp "$s (el buzón remitente): " v; else read -rsp "$s: " v; echo; fi
  [ -n "$v" ] || { echo "vacío: omitido"; return; }
  gcloud secrets describe "$s" >/dev/null 2>&1 || gcloud secrets create "$s" --replication-policy automatic >/dev/null
  printf '%s' "$v" | gcloud secrets versions add "$s" --data-file=- >/dev/null; unset v
  for sa in golden-app$SUF golden-ops$SUF; do gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:$sa@$PROJECT.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --quiet >/dev/null; done
  gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:golden-deployer$SUF@$PROJECT.iam.gserviceaccount.com" --role roles/secretmanager.viewer --quiet >/dev/null
  echo "$s guardado"
}
for n in azure-tenant-id azure-client-id azure-client-secret graph-sender; do cargar "$n"; done
```
Escribe/pega el **tenant id**, el **client id**, el **secreto** (el VALOR, se ve vacío al teclear) y el remitente `soporteit@goldenlogisticas.com`. Comprobar sin ver valores:
```bash
for n in azure-tenant-id azure-client-id azure-client-secret graph-sender; do echo -n "golden-$n-staging: "; gcloud secrets versions list "golden-$n-staging" --format='value(name,state)' | head -1; done
```
*Alternativa:* `bash deploy/gcp/bootstrap.sh staging` hace lo mismo (pregunta cada opcional con lectura silenciosa y no toca lo que ya tiene valor), pero además repasa todos los pasos y vuelve a preguntar por los demás opcionales (Enter los omite).

**Redesplegar** para que los servicios y los Jobs monten los secretos: GitHub → Actions → «Cloud Run (staging; producción preparada y DESACTIVADA)» → **Run workflow** → rama `migra/fase1-2` (sin marcar «force»). Cualquier push a esa rama hace lo mismo. Comprobar que quedaron montados (solo muestra nombres):
```bash
gcloud run services describe golden-web-staging --region us-east4 --format=json | grep -o '"name": "\(AZURE_[A-Z_]*\|GRAPH_SENDER\)"' | sort -u
```
**Probar con «Enviar prueba»:** en un evento de staging, tarjeta **«Parámetros del Evento» → Escarapela digital** (si está apagada, actívala), escribe en el campo de prueba un buzón tuyo y pulsa **«Enviar prueba»**. Debe llegar un correo con el asunto `[STAGING] …` desde `soporteit@goldenlogisticas.com`. Si dice «Ni Microsoft Graph ni SMTP están configurados», aún no se redesplegó; si dice «No se pudo enviar el correo (Graph) …», el mensaje trae el motivo de Microsoft (consentimiento, secreto vencido o regla RBAC).

### 11.4 Producción: ¿un secreto propio por entorno? Sí
- **Secretos de Secret Manager separados** (ya es el diseño: `golden-azure-client-secret-staging` y `golden-azure-client-secret`), para que staging nunca lea los de producción.
- **Un secreto de cliente de Entra distinto por entorno.** Mínimo: en la misma aplicación, dos secretos con descripciones «staging» y «producción» (cada uno se rota y se revoca sin tocar el otro). Más fuerte: dos aplicaciones («Mailer GoldenWeb 2.0 staging» y «… producción»), cada una con su asignación RBAC; útil si algún día staging debe enviar desde otro buzón. Para el piloto basta lo mínimo.
- **No reutilices el secreto de la máquina vieja (VM)** en Cloud Run: crea secretos nuevos para los dos entornos.
- **Procedimiento en el corte:** (1) crear en Entra el secreto «producción»; (2) cargarlo con la misma función `cargar` pero con `SUF=` (vacío) y `golden-app`, `golden-ops`, `golden-deployer` sin sufijo — o con `bash deploy/gcp/bootstrap.sh production`, que lo pide en silencio; (3) desplegar producción (con tu autorización) y probar «Enviar prueba» y una constancia real; (4) cuando la VM esté apagada y producción lleve 7 días estable, **borrar en Entra el secreto que usa la VM** (Certificados y secretos → eliminar) y quitar la línea `AZURE_CLIENT_SECRET` de su `.env`.
- **Rotación:** cada 12 meses o 30 días antes de vencer (el actual vence el 20/09/2028: pon un recordatorio para agosto de 2028). Orden: crear el secreto nuevo en Entra → `printf '%s' "$VALOR" | gcloud secrets versions add golden-azure-client-secret[-staging] --data-file=-` → redesplegar (los servicios leen `:latest` al arrancar una instancia) → «Enviar prueba» → borrar el secreto viejo en Entra y deshabilitar la versión vieja (`gcloud secrets versions disable <n> --secret …`).
- **Si el secreto se filtra:** borrarlo en Entra de inmediato (el envío se interrumpe hasta cargar uno nuevo), crear otro y seguir la rotación.
