# Migración a Cloud Run + Neon (Fases 1-2)

Rama `migra/fase1-2`. Plan y decisiones de fondo: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` (§4-8, §11, §14-16).
Este archivo se completa en la sesión 3 (runbook del día del cambio + costos); por ahora lleva la lista de progreso.

**Estado al 2026-09-28:** sesiones 1 y 2 y la revisión R1-R4 terminadas y empujadas; nada creado en la nube; siguiente paso: Juan David
corre `bootstrap.sh staging`. Resumen para retomar: [`docs/HANDOFF.md`](HANDOFF.md).

## Progreso (se actualiza en cada commit)

### Sesión 1 — la app queda lista para Cloud Run + Neon
- [x] 1. Cupo atómico: `form_reserve_slot()` (migración 0049) + wrapper en `formsvc` + `_submit` + pruebas de concurrencia
- [x] 2. `GcsStorage` en `app/storage.py`
- [x] 3. Backend Cloud Tasks en `app/jobs.py` (Postgres sigue como alternativa)
- [x] 4. Directorio paginado e incremental en `static/js/directory.js`
- [x] 5. Dockerfile multi-etapa + 3 puntos de entrada — imagen construida (Python 3.14, dlib compilado en la etapa de ruedas), los tres servicios arriba con `deploy/docker-compose.yml` contra Neon staging (`/readyz` 200 en los tres; `publico`/`web` sin dlib, ~275 MiB cada uno; `biometria` con el modelo, ~300 MiB) y prueba del emulador de Cloud Storage (`fsouza/fake-gcs-server`) en verde. Arreglado de paso: `STORAGE_BACKEND=` vacío (como lo deja la plantilla) tumbaba `/readyz`; ahora vacío = local
- [x] 6. `.env.staging` lleno por Juan David (incluida una `FACE_ENCRYPTION_KEY` propia de staging, válida y distinta de la local). Migraciones corridas en la rama staging de Neon (vacía, Postgres 18, `us-east-1`) por la conexión directa: queda en `0049_form_atomic_reserve (head)`. Contenedor probado contra ella: login, Directorio con 3.000 personas sintéticas (`scripts/seed_staging_demo.py`: 3 páginas de 1.000 y el incremental cada 15 s actualiza los contadores sin recargar) y subida directa de un documento de 20 MB. **Latencia de referencia desde el PC de desarrollo (Bogotá) a Neon us-east-1:** `SELECT 1` mediana 81 ms (p95 85, mínimo 79), igual por el pooler que directa; abrir conexión ~500 ms (TLS + channel binding), por eso el pool reutiliza conexiones; `/readyz` del servicio web ~0,33 s en caliente (primera ~1,4 s). Esta medición NO sirve para elegir región (sale desde Colombia): la región se decide en la sesión 3 con la medición desde Cloud Run; el bootstrap queda con `us-east1` por defecto y `us-east4` como alternativa. Nota: las cadenas de `.env.staging` usan el rol dueño (`golden_db_owner`); para mínimo privilegio, crear un rol de app para la app y dejar el dueño solo a las migraciones (hecho en la sesión 2, pieza 5)

### Sesión 2 — terminada (2026-09-28)
- [x] 0. Preparación: `FACE_ENCRYPTION_KEY` NUEVA en `.env.staging` (aleatoria, nunca la de producción); región sin decidir
  (`us-east1` por defecto, `us-east4` alternativa, se mide desde Cloud Run en la sesión 3); pool de conexiones confirmado
  (uno persistente por proceso, `pool_pre_ping`, LIFO, reintentos; prueba `tests/test_db_pool.py`: 30 peticiones, 0 conexiones
  nuevas); `scripts/seed_staging_demo.py` va en la imagen y ahora exige `DEPLOY_ENV=staging` además de un host de Neon
  (producción también vivirá en Neon)
- [x] 1. Carga masiva con fotos como **Cloud Run Job** (`BULK_BACKEND=cloudrun`, `BULK_JOB_NAME`). El servicio web solo revisa
  permisos y la autorización de las fotos, guarda en la tarea (`bulk_jobs.spec_json`, migración 0050) los TOKENS de los archivos
  ya subidos al bucket —nunca su contenido: un ZIP de 2 GB no cabe en el servicio web— y lanza una ejecución del Job por la API de
  Cloud Run (`run.jobs.runWithOverrides`, args `-m app.bulk_runner <id>`). El Job (misma imagen, comando `python`, hasta 24 h, CPU
  siempre asignada, 0 reintentos) descarga, valida y procesa con el MISMO código y escribe el avance en la misma fila: la barra no
  cambia. Si el Job no se puede lanzar, la tarea queda en error (503) y el evento no queda bloqueado. Se descartó la cola procesada
  dentro de la petición: tope de 45-60 s por petición contra cargas de horas. `thread` sigue siendo el modo por defecto (VM y local).
  Pruebas: `tests/test_bulk_cloudrun.py` (4) + las 9 de siempre
- [x] 2. `deploy/gcp/bootstrap.sh <staging|production>` (NO se ha corrido: lo revisa y lo corre Juan David en Cloud Shell). Idempotente,
  con qué crea y cuánto cuesta al inicio. Lee el ID del proyecto de `gcloud config`; `REGION` por defecto `us-east1` (`REGION=us-east4`
  como alternativa). Crea: APIs; Artifact Registry con limpieza (10 últimas / 30 días); cuentas de servicio por entorno (`golden-app`,
  `golden-ops`, `golden-invoker`, `golden-deployer`) con permisos mínimos —incluido `iam.serviceAccountTokenCreator` de la cuenta de la app
  sobre sí misma (firmar URLs)—; Workload Identity Federation para GitHub (staging: cualquier rama del repositorio; producción: solo
  `main`) [corregido en R1: staging solo desde `migra/fase1-2`, permisos a nivel de recurso]; Secret Manager pidiendo cada valor por teclado a ciegas (genera los que se pueden generar; en producción pide la
  `SECRET_KEY` y la `FACE_ENCRYPTION_KEY` ACTUALES de la VM, sin las cuales no se leen los rostros migrados) y crea `golden_app` con
  `scripts/neon_app_role.py` guardando su cadena directo en el secreto; buckets (producción reutiliza los dos existentes —archivos bajo
  `app/`, separados de las copias de la VM en `data/` y `config/`— e imprime su región; staging crea uno propio para que su cuenta no
  toque producción) con CORS (origen = dominio del entorno + dominios de Firebase), ciclo de vida y versiones; cola de Cloud Tasks con
  tope; los 3 servicios y 3 Jobs con imagen de relleno (`deploy.sh --placeholder`); la tarea de Cloud Scheduler (solo producción);
  canal de correo, chequeo de disponibilidad a `/health` cada minuto y alertas de caída, Jobs fallidos y 5xx (con los nombres exactos
  del entorno, para que staging no dispare las de producción); presupuesto al 50/90/100 % en la moneda de la cuenta (se pide el
  monto) [corregido en R3: no crea otro si ya hay uno]; y el sitio de Firebase Hosting. Al final imprime las variables a configurar en GitHub. Revisado con shellcheck.
  `deploy/gcp/config.sh` concentra nombres y parámetros; `deploy/gcp/env/common.yaml` las variables no secretas
- [x] 3. Staging en Cloud Run + GitHub Actions: `.github/workflows/cloudrun.yml` despliega staging en cada push a `migra/fase1-2`
  (primero las pruebas de `ci.yml`); producción está en el mismo archivo con `if: false` (preparada, DESACTIVADA; la VM sigue con
  `deploy.yml`, que no se tocó). Los pasos viven en `cloudrun-deploy.yml`: imagen con caché (dlib se compila una vez), `deploy/gcp/deploy.sh`
  (Job de migraciones con el dueño ANTES de tocar los servicios —si falla, todo sigue en la versión anterior—, los 3 servicios con
  `APP_MODULE` distinto, sonda de arranque a `/ready` y de vida a `/health`, Jobs de carga y de operaciones, permisos entre piezas) y
  Firebase Hosting (`deploy/firebase/make_config.py`: las rutas salen de `app/appmode.py`, prueba `tests/test_firebase_config.py`). En
  producción `deploy.sh` consulta `/api/ops/deploy-allowed` con el token de operaciones y se niega a desplegar si hay un evento en curso o
  una apertura cercana (`FORCE=1` / «force» lo salta). Sin las variables del Environment el despliegue se salta sin fallar. Revisado
  con actionlint. Un despliegue NO devuelve a 0 las instancias mínimas que haya puesto el precalentamiento
- **Firebase Hosting frente a Cloud Run — límites verificados en la documentación oficial:** (1) 60 s por petición (504 aunque Cloud Run
  permita más): nada pesado pasa por una petición (cargas y respaldos son Jobs; la cola se despierta por Cloud Tasks directo a Cloud
  Run, sin Firebase); (2) **solo pasa la cookie `__session`** a Cloud Run: la app ahora la nombra con `SESSION_COOKIE=__session` (en la
  VM sigue `session`); sin esto nadie podría iniciar sesión; (3) respuestas dinámicas `private` salvo que la app diga `public` (el
  cascarón del formulario público ya manda `s-maxage=60`), con `Cookie` en `Vary`; (4) regiones: `us-east1` y `us-east4` están
  soportadas; (5) tamaño: el tope efectivo es el de Cloud Run (32 MiB), resuelto con la subida directa. Con esto Firebase alcanza y **no
  hace falta el Cloudflare Worker** (~US$5/mes); quedaría como plan B si Firebase fallara en la prueba de carga. Además, detrás de
  Firebase (Cloudflare solo DNS) `CF-Connecting-IP` se podría inventar: `TRUST_CF_CONNECTING_IP=0` y la IP real sale de
  `X-Forwarded-For` en la posición `XFF_CLIENT_INDEX` (verificar la posición exacta con tráfico real en staging, sesión 3)
- [ ] 3. Staging en Cloud Run (`*-staging`) + workflow de GitHub Actions; producción preparada pero desactivada
- [x] 4. Jobs programados: **UNA tarea de Cloud Scheduler** (cabe en las 3 gratuitas) corre cada hora al minuto 05 (hora de Bogotá) el
  Cloud Run Job `golden-ops` (`python -m app.ops_runner hourly`, misma imagen), que reemplaza los 4 cron de la VM. Pasos aislados (si
  uno falla los demás corren y el Job termina en 1 → alerta de Monitoring + correo a `ALERT_EMAIL`, máximo cada 6 h por problema):
  respaldo de la base cada hora; a las 3 también el diario («completo»: la base; los archivos viven en el bucket con versiones de
  objeto, lo borrado/sobrescrito se conserva 30 días; los secretos, versionados en Secret Manager); a las 4 la purga biométrica
  (obligatoria); revisión de respaldos (hora < 2 h, diario < 26 h, tamaño); cola de trabajos pendiente (barrido de seguridad de Cloud
  Tasks); y precalentamiento. Respaldos: `pg_dump` 18 (añadido a la imagen desde el repositorio oficial de PostgreSQL) con el dueño,
  `--no-owner --no-privileges`, gzip verificado, MD5 al subir, `gs://<BACKUP_BUCKET>/db/hourly|daily/…` (retención: 3 y 60 días,
  `deploy/gcs-lifecycle.json`). «Último respaldo» en `/sistema` lee el más reciente DIRECTO del bucket (`BACKUP_BUCKET`).
  **Precalentamiento sin tocar la base a cada rato** (regla de costo: Neon no se apagaría nunca, ~US$19/mes): se calcula dentro de la
  corrida horaria (que ya despierta a Neon para el respaldo) mirando 75 min hacia adelante, y además al instante cuando un evento entra
  o sale de «en proceso» o un formulario se abre (a mano, con constancia `form_opened`, o por calendario): `app/warmup.py` fija
  instancias mínimas a nivel de servicio (web 2 con eventos en curso, biometría 1 si usan rostro, público 2 alrededor de una apertura;
  sin revisión nueva) y, en Neon, «nunca apagarse» + mínimo 0,5 CU durante esas ventanas (vuelve a 5 min / 0,25 CU después). El
  congelamiento de despliegues va en el workflow (pieza 3). **Probado de punta a punta desde el contenedor** contra Neon staging y el
  emulador de Cloud Storage: respaldo horario y diario (17 KB), revisión en verde, y ese mismo respaldo restaurado en staging con
  `migrate_db_to_neon.py` → 389 filas idénticas (restauración probada). Pruebas: `tests/test_ops_runner.py` (10)
- [x] 5. Rol `golden_app` en Neon (`scripts/neon_app_role.py`, idempotente). La app entra con `golden_app` por el pooler; migraciones,
  respaldos y restauraciones con el dueño (`golden_db_owner`, conexión directa). Permisos: `CONNECT`, `USAGE` del esquema, DML en
  todas las tablas, secuencias, `EXECUTE` de funciones, y privilegios por defecto del dueño para lo que creen las migraciones futuras;
  sin `CREATE`. **Cambio frente a la VM:** allá `golden_app` es DUEÑO de las 66 tablas (el volcado trae `OWNER TO golden_app`); en Neon
  el dueño es `golden_db_owner` y la migración de datos quita esos `OWNER TO`/`GRANT`. La contraseña se genera en el script (256 bits),
  va a Neon en claro por TLS (Neon rechaza un verificador SCRAM precalculado: lo sincroniza con su plano de control) y solo se escribe en
  `.env.staging` o en Secret Manager (`--app-secret`), nunca en pantalla. **Aplicado en la rama staging:** golden_app entra por el pooler,
  lee, NO puede crear tablas, y la app funcionó con él (cola: encolar/reclamar/terminar; función de cupo; `/readyz` 200). Copia del
  `.env.staging` anterior fuera del repo
- [x] 6. Scripts de migración, probados:
  - **Base VM→Neon** (`scripts/migrate_db_to_neon.py`): origen en vivo (`pg_dump 18 --no-owner --no-privileges`) o un respaldo
    `.sql[.gz]`; exige `golden_app` creado antes y destino vacío (`--wipe` con confirmación); pasa el volcado directo a `psql 18`
    (`ON_ERROR_STOP`, una sola transacción, sin archivos intermedios) quitando `OWNER TO`/`GRANT`/`REVOKE`/`ALTER DEFAULT PRIVILEGES` de la
    VM; cuenta filas por tabla en el volcado (y en el origen vivo) y en Neon, y sale con error ante cualquier diferencia; `--migrate` corre
    `alembic upgrade head` con el dueño; al final aplica los permisos de `golden_app`. Sin psql 18 local: variable `PSQL` con
    `docker run … postgres:18 psql`. **Probado con el respaldo de producción más reciente disponible (26-sep, 17:05; no hay uno más nuevo
    en este equipo) contra la rama staging:** 389 filas en 36 tablas idénticas antes/después, migraciones 0048→0050 sin cambiar conteos,
    las 37 tablas quedan del dueño y `golden_app` lee sin ser dueño de nada. Staging queda con esa copia de producción. Prueba del filtro:
    `tests/test_migrate_db_to_neon.py` (no toca datos de los COPY aunque empiecen por «GRANT»; sin saltos de línea de Windows)
  - **Archivos VM→Cloud Storage** (`scripts/migrate_files_to_gcs.py`): mismas claves que la app (`<GCS_PREFIX>/<tenant>/…`), sube solo lo
    que falta o cambió (MD5), cada subida verificada con MD5 de punta a punta, pasada final local-vs-bucket (falta/distinto → código 1),
    `--dry-run` y `--verify-only`, sin temporales (`uploads/`, `*.part`). Probado contra el emulador: repetir no resube, un objeto
    alterado se detecta y se corrige, y `GcsStorage` lee el archivo migrado con su clave (`tests/test_migrate_files.py`). La corrida real
    contra el bucket es de la sesión del cambio (Juan David, desde la VM)

#### Revisión de Juan David (2026-09-28) — correcciones antes de correr nada
- [x] R1. **Aislamiento staging/producción.** `golden-deployer-<entorno>` ya NO tiene `run.admin` ni `firebasehosting.admin` en el
  proyecto: recibe `run.developer` sobre cada servicio y Job de SU entorno (a nivel de recurso, lo da bootstrap.sh después de crearlos
  con la imagen de relleno) y un rol propio de solo lectura `goldenRunOperationsViewer` (`run.operations.get/list`, para esperar sus
  despliegues). `deploy.sh` ya no crea recursos ni cambia políticas (`--allow-unauthenticated` y los permisos entre piezas pasaron a
  bootstrap, que corre el dueño). Artifact Registry: un repositorio por entorno (`golden-staging`, `golden`), así staging no puede
  sobrescribir una imagen que despliegue producción. Secretos: la cuenta de despliegue ve los metadatos de los secretos de SU entorno
  (por secreto), no la lista del proyecto. Workload Identity: staging solo desde `refs/heads/migra/fase1-2` (`STAGING_BRANCH_REF` para
  cambiarla) y producción solo desde `refs/heads/main`.
  **Firebase Hosting no tiene permisos por sitio** (sus roles se dan a nivel de proyecto; no pude confirmarlo en la lista oficial de
  permisos porque la página no cargó completa, así que el diseño asume lo seguro): con un solo proyecto, quien pueda publicar el sitio
  de staging también puede publicar o borrar el de producción. Opciones: (a) **staging en su propio proyecto de Google Cloud**
  (RECOMENDADA): aislamiento total de todo —Cloud Run, secretos, buckets, imágenes, Firebase—, sin costo extra (mismo pago de
  facturación; las capas gratuitas van por cuenta de facturación) y sin cambiar código: `gcloud config set project <proyecto-staging>`
  y `FIREBASE_DEPLOY=1 bash deploy/gcp/bootstrap.sh staging`. Firebase Hosting solo reenvía a Cloud Run del MISMO proyecto, por eso
  staging con Firebase implica mover todo staging. (b) Un solo proyecto (lo que hace el script por defecto): la cuenta de staging no
  recibe NINGÚN permiso de Firebase; staging se prueba por la URL de Cloud Run y, como sin Firebase nadie reparte las rutas entre los
  3 servicios, el servicio web de staging sirve la app completa (`app.main:app`). Pierde probar en staging lo propio de Firebase (cookie
  `__session`, 60 s, CDN), que habría que probar el día del cambio. (c) Publicar Firebase de staging a mano (sin cuenta de GitHub):
  poco práctico. **Recomiendo (a).**

- [x] R2. **`/internal/*` en un servicio público.** Antes aceptaba también el token de operaciones (`X-Ops-Token`) y, si faltaba
  `CLOUD_TASKS_URL`, la librería de Google verificaba el token SIN audiencia. Ahora TODA ruta `/internal/*` (hoy solo
  `/internal/jobs/run`) pasa por una sola dependencia (`google_invoker`, app/routers/ops.py): token OIDC de Google válido (firma, emisor
  y vigencia de Google), audiencia = `CLOUD_TASKS_URL` y emitido para `JOBS_INVOKER_SA` del entorno con correo verificado. Sin token o
  inválido → 401; válido de otra cuenta (p. ej. el invoker de producción contra staging) → 403; sin configurar → 403 (cerrado);
  no se pudo verificar por red → 503 (Cloud Tasks reintenta). Ni la sesión de admin ni `X-Ops-Token` sirven ahí (`X-Ops-Token` sigue
  solo para `/api/ops/deploy-allowed`). Una prueba recorre todas las rutas `/internal` de la app y falla si alguna no tiene la
  dependencia (`tests/test_jobs_cloudtasks.py`)

- [x] R3. **Presupuesto:** el paso 11 ya no crea uno si CUALQUIER presupuesto de la cuenta de facturación cubre el proyecto (filtrado a
  este proyecto o de toda la cuenta): solo lo informa (p. ej. «GoldenWeb mensual» 160000 COP). Si no puede leer los presupuestos (falta
  `billing.budgets.list` en la cuenta de la empresa) no crea nada y avisa. Solo sin ninguno pregunta el monto (Enter = no crear)

- [x] R4. **Privacidad: cuánto sobrevive un dato biométrico después de purgado.** Cambios: en la nube las fotos biométricas viven bajo un
  prefijo común (`BIOMETRIC_KEY_PREFIX=biometric` → `app/biometric/<cliente>/known_people/<cédula>.jpg`; en la VM nada cambia) y
  `scripts/migrate_files_to_gcs.py --biometric-prefix biometric` las deja ahí. Así una regla de ciclo de vida
  (`deploy/gcs-app-lifecycle.json`) borra en **1 día** las versiones viejas que dejan la purga, un «eliminar» o una foto corregida (el
  resto de archivos conserva sus versiones 30 días). Los respaldos (`deploy/gcs-lifecycle.json`) también borran en 1 día cualquier versión
  vieja. bootstrap.sh desactiva el *soft delete* de GCS (retención oculta de lo borrado, 7 días por defecto) en los dos buckets: la
  protección de archivos es el versionado, y los respaldos no los puede borrar ninguna cuenta de servicio (solo el ciclo de vida).

  | Dónde | Qué queda tras la purga (`purge_biometrics`, 180 días después del fin del evento) | Máximo que sobrevive |
  |---|---|---|
  | Base de datos (Neon, en vivo) | nada: `face_encoding` queda vacío al instante | 0 |
  | Historial de Neon (restaurar a un minuto pasado) | el encoding (cifrado con la llave de la app) dentro de la ventana de restauración | la ventana configurada en Neon (plan Launch: hasta 7 días). **Recomendado: fijarla en 1 día** (consola de Neon → Settings → Storage → History retention; paso manual) |
  | Foto en el bucket | versión vieja bajo `app/biometric/…` | ≤ 2 días (regla de 1 día; GCS la aplica de forma asíncrona, hasta ~24 h después) |
  | Respaldos horarios | el encoding cifrado | 3 días (+ ≤ 1 día de retraso del ciclo de vida) |
  | Respaldos diarios | el encoding cifrado | **60 días** (+ ≤ 1 día) |
  | Logs | nada: nunca registran encodings ni fotos | 0 |

  **Número para la política de privacidad: hasta 61 días después de la purga** (la copia más vieja de los respaldos diarios, cifrada con
  la llave de la app; ~2 días si se trata solo de la foto). Con la ventana de Neon en 1 día el número no cambia (lo manda el respaldo).
  Si se quisiera acortarlo habría que acortar la retención de los respaldos diarios (hoy 60 días, `deploy/gcs-lifecycle.json`).
  **Pendiente del mundo VM (limpiar después del cambio):** las copias que hace la VM (`gs://<bucket-datos>/data/`, con versiones: incluye
  `known_people/`) y sus volcados en `gs://<bucket-respaldos>/db/` siguen su propia retención (60 días los volcados; las versiones viejas
  de `data/`, hasta 30 días con la regla general). En el runbook del cambio: apagar el cron de la VM y borrar `gs://<bucket-datos>/data/`
  y `config/.env` una vez verificada la migración

#### Qué corre Juan David después de la sesión 2 (en este orden; nada de esto lo corrió Claude Code)
1. Revisar `deploy/gcp/bootstrap.sh`, `deploy/gcp/deploy.sh`, `deploy/gcp/config.sh` y `.github/workflows/cloudrun*.yml`.
2. Cloud Shell: `git clone` del repositorio, `git checkout migra/fase1-2`, `gcloud config set project <ID>` y
   `bash deploy/gcp/bootstrap.sh staging` — **si se sigue la recomendación de R1**, `<ID>` es un proyecto NUEVO solo para staging y
   se corre `FIREBASE_DEPLOY=1 bash deploy/gcp/bootstrap.sh staging`. En Neon (plan Launch): fijar la ventana de historia en 1 día
   (R4) y crear una llave de API para el precalentamiento (se pega en el bootstrap, nunca en el chat). Pide: la cadena DIRECTA del dueño de la rama staging de Neon (la de `DIRECT_DATABASE_URL`
   de `.env.staging`), Enter para generar `SECRET_KEY`/`FACE_ENCRYPTION_KEY`/`OPS_TOKEN` nuevas, y los opcionales (llaves SANDBOX de
   Wompi, Azure si se quiere correo real en staging, correo de alertas, llave de API de Neon + id del proyecto + id del endpoint de la
   rama staging para el precalentamiento). Ojo: le pone una contraseña NUEVA a `golden_app` en staging (la de `.env.staging` local deja de
   servir; para volver a usarla: `python scripts/neon_app_role.py --env-file .env.staging --rotate`). Si Firebase pide autenticación:
   `firebase login --no-localhost` y volver a correr el script (es idempotente).
3. GitHub → Settings → Environments: crear `staging` (y `production`) con las variables que imprime el script.
4. Volver a lanzar el workflow «Cloud Run» (o hacer un push a `migra/fase1-2`): construye la imagen (~20 min la primera vez), corre las
   migraciones, despliega staging y publica Firebase Hosting. Verificar `https://golden-staging-<número>.web.app`.
5. `bash deploy/gcp/bootstrap.sh production` puede esperar a la semana 3 (necesita la rama `production` de Neon y la `SECRET_KEY` y
   `FACE_ENCRYPTION_KEY` de la VM). Deja los servicios con imagen de relleno y la tarea horaria EN PAUSA hasta el día del cambio.

- [x] Cierre de la sesión 2: `docs/HANDOFF.md` (estado, decisiones, reglas, riesgos, siguientes pasos), `CLAUDE.md` corto y el
  historial detallado movido sin cambios a `docs/historial.md`

### Staging desplegado (2026-09-29, proyecto `goldenweb-staging`, us-east1) — problemas encontrados y corregidos
- [x] S1. **`/healthz` daba 404 de Google** en Cloud Run (la respuesta ni siquiera llega a la app: Cloud Run reserva rutas que terminan
  en «z», docs.cloud.google.com/run/docs/known-issues). Nuevas rutas equivalentes `/health` y `/ready` (las viejas siguen para la VM) en:
  sondas de Cloud Run (`deploy.sh`: arranque `/ready`, vida `/health`), comprobación tras desplegar, chequeo de disponibilidad y alerta
  del bootstrap (`golden-health-<entorno>` a `/health`), Firebase Hosting, `docs/observabilidad.md` y runbook. **Para recrear el chequeo
  de staging** basta volver a correr `bash deploy/gcp/bootstrap.sh staging` (borra `golden-healthz-staging` y su alerta «/healthz no
  responde» y crea los nuevos). A mano, en Cloud Shell:
  `gcloud monitoring uptime list-configs --filter='displayName="golden-healthz-staging"' --format='value(name)'` →
  `gcloud monitoring uptime delete <ID del final>`, y `gcloud monitoring policies list --filter='displayName="Golden staging: /healthz no responde"' --format='value(name)'`
  → `gcloud monitoring policies delete <nombre>`; después correr el bootstrap para crear los nuevos. El día del cambio: «GoldenWeb readyz»
  y UptimeRobot a `https://app.golden-eventos.com/health`

- [x] S2. **Página sin estilos en `*.web.app`.** El HTML pedía el CSS como `http://golden-web-staging-…a.run.app/static/css/style.css?v=…`:
  `url_for` armaba una URL ABSOLUTA con el host y el esquema que ve la app detrás del proxy (host interno de Cloud Run, `http`), y el
  navegador la bloqueaba por contenido mixto en la página `https`. Firebase sí servía `/static/…` (200). Arreglo: `app/staticver.py` devuelve
  solo la ruta (`/static/…?v=…`), válida en cualquier dominio (en Firebase sale de su CDN); además `FORWARDED_ALLOW_IPS="*"` en Cloud Run
  para que la app tome `X-Forwarded-Proto=https` de Google (redirecciones en https). Prueba: `test_static_urls_are_paths_not_absolute_urls`

- [x] S3. **«Usuario o contraseña incorrectos» con la cuenta de producción en staging: NO es un fallo del flujo.** Diagnóstico con la
  conexión directa del dueño (sin mostrar usuarios ni claves): (1) el hash es bcrypt puro (`app/auth.py`), no depende de `SECRET_KEY` ni de
  ninguna variable; (2) el único intento fallido registrado (`rate_limit_events`) muestra que la petición SÍ llegó a la app, que el usuario
  escrito EXISTE (la cuenta `super_admin`, activa, hash `$2b$` de 60 caracteres) y que la app vio la IP real del cliente (sin bloqueo por
  IP); (3) con un usuario de prueba `revisor.staging` (coordinador, contraseña aleatoria guardada fuera del repo) el inicio de sesión
  FUNCIONA por el `run.app` y por el `web.app` (302, cookie `__session` con `Secure`, `/clientes` 200 con la sesión): el cuerpo del
  formulario llega, Firebase deja pasar la cookie y el control de origen acepta `PUBLIC_BASE_URL`. Conclusión: la contraseña guardada en
  staging es la de la cuenta en el respaldo de producción del 26-sep; si se cambió después (o se escribió otra), no coincide. Arreglo:
  poner una contraseña nueva a esa cuenta SOLO en staging (comando en el mensaje de la sesión) o volver a copiar un respaldo reciente

### Sesión 3 — pendiente (empieza cuando staging esté desplegado en Cloud Run)
- [ ] 1. Script de medición de latencia app→Neon desde Cloud Run (us-east1) y decisión de región (us-east1 / us-east4)
- [ ] 2. Verificar `XFF_CLIENT_INDEX` con tráfico real detrás de Firebase y fijarlo en `deploy/gcp/env/common.yaml`
- [ ] 3. Prueba de carga distribuida contra staging (Locust en Cloud Run Jobs: 10.000 aperturas / 5.000 envíos + escaneos) y simulacros
  de falla (doc 13 §11, Fase 4)
- [ ] 4. Este documento completo: runbook del día del cambio (ventana, respaldo final, migración de base y archivos con
  `--biometric-prefix biometric`, DNS, dominio en Firebase, reanudar `golden-ops-hourly`, mover el chequeo «GoldenWeb readyz» y el monitor de UptimeRobot a
  `/health` (NO `/healthz`: en Cloud Run da 404 de Google), verificación, vuelta atrás, limpieza de lo de la VM) y tabla de costos por componente
- [ ] 5. Revisión final de pruebas y ruff

## Decisiones tomadas
- `docs/13` se actualizó con la versión completa que Juan David pegó en el chat (§14-§17); no estaba en el disco.
- Cupo atómico: la función replica `held_count` (confirmadas + pagos en espera dentro de 30 min) y `quota_counts`, igual que
  `held_count`. Códigos de descuento y la purga de inscripciones abandonadas quedan fuera de la función a propósito
  (no necesitan el bloqueo de la fila del formulario).
- Con la fila del formulario bloqueada ahora solo corren: `form_reserve_slot()` (1 ida y vuelta: reintento por `sid`, cupos
  por variable, cupo total contando pagos en espera, duplicado), el INSERT y el commit. Antes eran 5-7 consultas.
  Fuera de la función, a propósito: descartar el intento de pago anterior de la misma persona (antes del bloqueo), la purga de
  inscripciones abandonadas (solo en formularios con pago) y la verificación del código de descuento (solo si hay código).
- Reintento: si ya existe una inscripción confirmada con la misma clave de envío (`sid`) se responde `replayed` sin volver a
  comparar los datos (el `sid` es aleatorio por carga de página y tras confirmar la página muestra el agradecimiento).
- `GcsStorage` (`STORAGE_BACKEND=gcs`, `GCS_BUCKET`, `GCS_PREFIX`): los archivos se sirven transmitidos por la app, sin URLs
  firmadas (no hace falta darle a la cuenta de servicio el permiso de firmar, y fotos/firmas cifradas se sirven descifradas por la
  app de todos modos). `/readyz` hace una lectura mínima del bucket (solo arranque). Prueba contra el emulador
  `fsouza/fake-gcs-server` (se salta si no está `STORAGE_EMULATOR_HOST`); corrida en verde en la pieza 5.
- **Archivos grandes: subida directa a Cloud Storage con URLs firmadas** (corrección pedida tras la sesión 1). Pasar los archivos
  por la app no alcanza: **Cloud Run rechaza peticiones de más de 32 MiB** (HTTP/1; documentado en las cuotas de Cloud Run) y la
  carga masiva manda lotes de hasta 60 MB. **Firebase Hosting no publica un límite de tamaño propio**, pero reenvía a Cloud Run por
  HTTP/1 (así que el tope efectivo sigue siendo el de 32 MiB) y además corta toda petición a los **60 s** (documentado: 504 aunque
  el servicio tenga un timeout mayor). **El menor de los dos es el de Cloud Run: 32 MiB**, y el de 60 s de Firebase es el que
  manda en tiempo. Implementación (`app/uploads.py`, `app/routers/uploads.py`, `static/js/direct-upload.js`): el navegador pide
  una URL (`POST /api/uploads` para el personal, `POST /f/<evento>/<slug>/upload` para formularios públicos), sube con PUT
  directo al bucket (URL v4 de 15 min, con el tipo y el tamaño máximo firmados en `x-goog-content-length-range`) y la petición
  normal lleva solo un token firmado (propósito + evento/formulario/campo + clave del objeto generada en el servidor). El endpoint
  lee el objeto, lo valida igual que antes (firma de bytes, imagen, etc.) y borra el temporal. Cubre: carga masiva (Excel/CSV y
  ZIP de fotos, el ZIP hasta 2 GB por lote), documentos y evidencias de gastos del evento (25 MB) y archivos de formularios (varios
  campos de hasta 20 MB sí superaban los 32 MiB juntos). Los archivos chicos (logos, imágenes del editor, fotos del kiosco, informe
  final de 15 MB, firmas) siguen pasando por la app, igual que las descargas (salen transmitidas por partes, sin tope). Con
  almacenamiento local la "URL firmada" es `PUT /api/uploads/local/<token>` en la misma app (desarrollo y la VM actual), así que el
  código es el mismo en los dos mundos. **En GCP hace falta:** (1) CORS del bucket para PUT desde el dominio (`deploy/gcs-app-cors.json`,
  `gcloud storage buckets update gs://<bucket> --cors-file=deploy/gcs-app-cors.json`); (2) regla de ciclo de vida que borra
  `uploads/` a 1 día (`deploy/gcs-app-lifecycle.json`; con `GCS_PREFIX` la ruta es `<prefijo>/uploads/`); (3) como la cuenta de
  servicio de Cloud Run no tiene llave privada, la URL se firma con la API IAM (signBlob): la cuenta necesita
  `roles/iam.serviceAccountTokenCreator` sobre sí misma. (Esto corrige lo dicho arriba: las DESCARGAS siguen sin URLs firmadas;
  las SUBIDAS grandes sí las usan.) Pendiente para la sesión 2: la carga masiva con fotos sigue procesándose en un hilo después de
  responder (`app/bulk_jobs.py`); en Cloud Run con facturación por petición tiene que pasar a un Cloud Run Job o a la cola.
- Cola con Cloud Tasks (`JOBS_BACKEND=cloudtasks`): la tabla `jobs` sigue siendo la fuente de verdad; Cloud Tasks solo despierta a
  `POST /internal/jobs/run` (token OIDC de `JOBS_INVOKER_SA`, audiencia `CLOUD_TASKS_URL`, o `X-Ops-Token`). Una tarea por
  segundo como máximo (`kick-<segundo>`) y cada reintento programa la suya. **Confirmado (corrección tras la sesión 1):** el endpoint
  procesa DENTRO de la petición (`jobs.drain` en el mismo hilo que la atiende, sin hilos de fondo), porque en Cloud Run con
  facturación por petición la CPU se reduce apenas se responde. Se agregó el tope de tiempo: vacía la cola o para a los
  `JOBS_RUN_BUDGET_SECONDS` (45, bajo el timeout de 60 s de Gunicorn), con lotes chicos para no dejar trabajos reclamados sin
  ejecutar, y si queda trabajo programa otra tarea. Pruebas en `tests/test_jobs_cloudtasks.py`. Sin Cloud Scheduler para la cola: el barrido de
  seguridad (lo que quede por un fallo al crear la tarea) se engancha en la sesión 2 al trabajo programado de precalentamiento.
- Directorio: la lista llega en páginas de 1.000 (la primera se ve enseguida) y cada 15 s, con la pestaña visible, se piden solo los
  cambios (`/api/users/changes`). Bajas y estados revertidos no salen en el incremental: el total no cuadra y se recarga todo; las
  acciones locales (editar, eliminar, cambiar estado) siguen recargando completo. Prueba: `node tests/js/directory_paging_check.js`.
  No se pudo mirar en el navegador (el inicio de sesión automático en la app local quedó bloqueado por permisos): revisarlo a mano.
- Imagen: UNA para todo (`Dockerfile`, Python 3.14 como la VM). Etapa 1 compila las ruedas (dlib incluido); la final no tiene
  compiladores, corre como usuario `golden` (uid 10001) y trae `tesseract-ocr` (cédula por foto). `APP_MODULE` elige el servicio
  (`app.entrypoints.publico|web|biometria:app`); un Job cambia el comando (`alembic upgrade head`). Sin cliente de Postgres
  (`pg_dump`): los respaldos van en la sesión 2 (imagen o paso aparte con Postgres 18). `deploy/docker-compose.yml` levanta los
  tres servicios en local con límites parecidos a Cloud Run (publico/web 1 vCPU 1 GB, biometria 2 vCPU 2 GB).
