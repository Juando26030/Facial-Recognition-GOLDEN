# Migración a Cloud Run + Neon (Fases 1-2)

Rama `migra/fase1-2`. Plan y decisiones de fondo: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` (§4-8, §11, §14-16).
Este archivo se completa en la sesión 3 (runbook del día del cambio + costos); por ahora lleva la lista de progreso.

**Estado al 2026-09-29:** staging (`goldenweb-staging`, us-east1) desplegado y en verde; la sesión 4 (D.1, B, A, C y los scripts de D.2) está en la rama y lo que
falta lo corre Juan David: lista exacta al final de este archivo y en [`docs/HANDOFF.md`](HANDOFF.md).

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

### Sesión 4 (2026-09-29, rama `migra/fase1-2`) — D.1: arreglos tras el primer despliegue de staging
- [x] D1.1 **Job de ops: el motivo del fallo va en `message`.** Cada paso fallido (y cada tarea suelta) registra
  `paso <nombre> falló: <Tipo>: <motivo>` (400 caracteres como máximo, sin datos personales ni secretos), además del `stack_trace`. Se lee con
  `gcloud logging read 'resource.type="cloud_run_job" AND severity>=ERROR' --format='value(jsonPayload.message)' --limit 5`.
- [x] D1.2 **`check-backups` en un entorno recién creado.** Que falte el PRIMER respaldo diario es un AVISO (el paso pasa y lo dice) mientras el
  respaldo más viejo del bucket tenga menos de `BACKUP_DAILY_MAX_AGE_H` (26) horas. Sin respaldos horarios, o con el diario ausente pasado
  ese plazo, sigue fallando (la alarma real no se debilita). Pruebas en `tests/test_ops_runner.py`.
- [x] D1.3 **Pasos sueltos del Job de operaciones** (`backup | backup-daily | purge | check-backups | sweep | warmup`; el Job se llama
  `golden-ops` en producción y `golden-ops-staging` en staging):
  ```bash
  gcloud run jobs execute golden-ops-staging --region us-east1 --args="-m,app.ops_runner,<paso>" --wait
  ```
  **Entorno nuevo:** tras el primer despliegue real (con la imagen de relleno el Job no sirve) correr una vez `backup-daily`; `bootstrap.sh`
  lo imprime al final y el runbook del cambio lo incluye.
- [x] D1.4 `datetime.utcnow()` → `app.timeutil.utcnow()` (mismo valor: `datetime` naive en UTC; sin `DeprecationWarning` en Python 3.14).
- [x] D1.5 **`ENVIRONMENT=production` junto a `DEPLOY_ENV=staging` es INTENCIONAL.** `ENVIRONMENT` decide el comportamiento de seguridad
  (`IS_PRODUCTION` en `app/main.py`: cookie de sesión `Secure`, `SECRET_KEY` obligatoria, sin `/docs` ni `/openapi.json`); staging debe
  probar exactamente eso. `DEPLOY_ENV` solo identifica el entorno. Para que nada de staging pase por producción: distintivo rojo
  «STAGING · pruebas, no es producción» en todas las pantallas del personal y en el ingreso (`templates/_env_badge.html`), prefijo `[STAGING]`
  en el asunto de TODO correo (`app/mailer.py`, incluidas las alertas del Job de ops) y las alertas/chequeos de Monitoring ya llevan el
  nombre del entorno (bootstrap). Prueba: `tests/test_staging_badge.py`.
- [x] D1.6 **Bootstrap, paso 12 (Firebase Hosting):** no interactivo (`--non-interactive`, sin stdin), cada llamada con `timeout`
  (`FIREBASE_TIMEOUT`, 90 s), salta si el sitio ya existe y, si falla, imprime el comando manual en vez de esperar.
- [x] D1.7 **GitHub Actions** (avisos por Node 20): checkout v7, setup-python v7, setup-node v7 (Node 22 para firebase-tools),
  google-github-actions/auth v3 y setup-gcloud v3, docker/setup-buildx v4 y build-push v7 (todas `node24`).

### Sesión 4 — A: reconocimiento facial, verificación del operador (docs/14 §6.3)
- [x] A1. **Resultado del escaneo** (`static/js/app.js`, `templates/kiosk_registro.html`, `app/routers/api.py`, `app/faces.py`). Al reconocer, el kiosco muestra la captura en vivo junto a la
  **foto de registro** de la persona encontrada, con nombre, cédula, categoría, estado de registro y un indicador de confianza en palabras (`Muy parecido` < 0,40 · `Parecido` 0,40-0,50 ·
  `Revisar con cuidado` 0,50-0,55 · `Fuera de la tolerancia` ≥ 0,55; la distancia va entre paréntesis). **«Ver 5 más cercanos»** despliega los candidatos 2-6 con foto, nombre, cédula parcial (últimas 4
  cifras), confianza y, los que superan 0,55, marcados «Fuera de la tolerancia». Todo sale del MISMO cálculo: `/api/recognize` deja en el token firmado (`match_token`, ahora 300 s) la persona
  principal y los 6 más cercanos (`_Index.top`: una sola operación numpy, sin trabajo extra de base por escaneo); `/api/recognize/candidates`, `/photo` y `/person` solo leen ese token (no recalculan el rostro
  ni reciben la foto). **Las fotos de los candidatos se piden solo al pulsar el botón** (una petición `POST` por foto; la de la persona principal, al mostrarla). Clic en la principal o en un candidato →
  se abre el modal **Editar** existente (`GoldenDirectory.openEdit`); guardar ahí marca el ingreso de ESA persona (`PATCH …/status` con `method: biometrico`, así en los reportes sigue contando como
  biométrico), no el del mejor match. Tras guardar aparece el botón **Imprimir** en el mismo panel (el modal ya dispara la auto-impresión si el evento la tiene; también tras un alta nueva con foto).
  Se quitó la tarjeta anterior «Actualización de Asistente» (`liveEditForm`), que solo servía para confirmar al mejor match.
- **Regla de caso dudoso:** `MATCH_MARGIN` (variable de entorno, default 0,06; recomendado 0,10, ver docs/14 §6.3): si el mejor y el segundo candidato distan menos, el resultado es `DUDOSO`: nunca se
  registra solo (ni con autoregistro, ni con `confirm`/`force`, ni con el token) y se muestran directamente los candidatos, sin «principal». Se evalúa antes que `DUPLICADO`. El Control de Áreas
  (`faces.identify`) NO usa esta regla todavía (queda como pendiente: mismo cambio en `kiosk_areas`).
- **Seguridad:** las fotos/registros de candidatos solo salen por `POST /api/recognize/{photo,person,candidates}`: `digitador+` autorizado en el evento (`get_event_for_staff`), evento en proceso, token
  del MISMO operador y evento (no sirve para pedir la foto de cualquiera: solo las posiciones que trae el token), `Cache-Control: private, no-store`, sin cédulas ni tokens en URL ni logs (van en el cuerpo).
  En Firebase estas rutas las sirve el servicio `web` (no cargan dlib; el token y la llave de cifrado son los mismos secretos).
- **Advertencia del autoregistro** (`kiosk_registro.html`): con `facial_enabled`, al activar el registro automático sale un aviso propio (modal) que lo desaconseja en eventos grandes, y mientras esté
  activo queda un aviso permanente bajo el interruptor.
- [x] A2. Pruebas: `tests/test_recognize_verification.py` (12: candidatos del mismo cálculo y sin reconocer de nuevo, cédula parcial, fuera de tolerancia, DUDOSO con y sin autoregistro/confirm/token, margen
  configurable, permisos y token de otro evento/operador/cliente, foto solo POST y `no-store`, token vencido, «confirmar a otra persona» y método biométrico, pantalla y aviso).
- [x] A3. Calibración de `MATCH_MARGIN` con las 39 personas: docs/14 §6.3 (`scripts/calibrate_match_margin.py`, resultados anónimos). **Juan David: ya puedes borrar `C:\JDRJ\Golden\fotos_prueba`** (solo se leyó, montada en
  solo lectura; no se copió nada al repo ni a la nube; los resultados agregados quedaron en `C:\JDRJ\Golden\perf_results\calibrate_match_margin.json`).

### Sesión 4 — B: retención biométrica de 7 días después de finalizado (reemplaza a los 180 días de R4)
- [x] B1. **Regla** (`app/privacy.py`, migración `0051_biometric_retention`): foto y vector del rostro se borran cuando TODOS los eventos de la
  persona llevan al menos `BIOMETRIC_RETENTION_DAYS_AFTER_EVENT` (7) días finalizados. Si sigue en un evento abierto, o finalizado hace menos de
  7 días, se conserva y la regla corre cuando cierre ese otro evento. **Tope:** `BIOMETRIC_MAX_DAYS` (180) días desde la captura aunque el evento
  siga abierto (eventos que nunca se finalizan; una persona sin ningún evento solo se borra por el tope). Reabrir un evento finalizado reinicia
  su reloj; si las fotos ya se borraron, el cliente las vuelve a entregar en cada evento con reconocimiento facial. Todo lo demás se conserva
  (nombre, cédula, ingresos, formularios…). Se quitó `BIOMETRIC_RETENTION_DAYS` (180) de `.env.example`, `common.yaml`, scripts y textos.
- [x] B2. **Implementación.** Dos relojes nuevos, estampados por listeners de SQLAlchemy (así valen para cualquier ruta del código, scripts y pruebas):
  `events.finalized_at` (al pasar a «finalizado»; se limpia al reabrir; reenviar el mismo estado NO lo reinicia) y `users.face_captured_at` (al
  guardar un `face_encoding` distinto). **Relleno de la migración (decisión):** eventos ya finalizados → `finalized_at` = momento de la migración
  (el reloj de 7 días arranca ahí: nada se borra por sorpresa en la primera corrida); rostros existentes → `face_captured_at` = su constancia de
  autorización o, si no la tienen, el momento de la migración (el tope de 180 días cuenta desde ahí). Paso `purge` del Job de ops (cada hora, sin
  la restricción de la hora 4): consulta por claves en lotes de 200, idempotente, sin bloqueos sobre `events`; por persona borra PRIMERO el objeto
  de Storage y solo si eso salió bien deja en nulo el encoding y la constancia (si falla: cuenta el error, no toca el encoding y reintenta la hora
  siguiente; el paso termina en error y avisa). No hay miniaturas ni copias derivadas de la foto (una sola llave por persona). La caché de rostros
  en memoria se invalida sola (el listener de `faces_version` sube la versión de los eventos del cliente cuando cambia un `face_encoding`). Solo se
  registran conteos: `{"people", "objects", "errors", "by_cap"}`. Candidatos: quien tiene `face_encoding` o constancia de autorización (una foto sin
  ninguno de los dos —caso anterior al 25-sep sin encoding— no se ve desde la base; ceiling conocido). `--dry-run` en `scripts/purge_biometrics.py`.
- [x] B3. **Botón «Borrar fotos del evento»** en Estadísticas (admin+; también sustituye al botón de Parámetros): modal propio (`static/js/biometric-purge.js`,
  `showPrompt`) que explica qué se borra (fotos y vectores del rostro) y qué no (todo lo demás) y exige escribir el nombre del evento; el servidor
  también lo exige (`confirm_name`, sin distinguir mayúsculas). **Regla de omisión (decisión):** se conserva a quien está en OTRO evento ABIERTO
  (no finalizado) CON reconocimiento facial activo —el principio es no romper un evento en curso que usa rostros—; la respuesta trae cuántas se omitieron y
  el motivo con los nombres de esos eventos (nunca de personas). Quien solo está en otros eventos sin rostro, o ya finalizados, sí se borra (aunque
  la regla automática lo esperaría 7 días: el admin lo pidió). Auditoría en `system_events` (`kind=biometrics_purge`, `ref=event:<id>`, «por
  <usuario> (id N); X borradas, Y omitidas»): quién, cuándo, evento y cuántas, sin datos de personas.
- [x] B4. **Respaldos: 60 → 30 días** para `db/` (`deploy/gcs-lifecycle.json`; los horarios siguen en 3 días). Lo biométrico borrado puede seguir hasta **30 días
  (+ ≤ 1 día de retraso del ciclo de vida)** dentro de los respaldos diarios (cifrado con la llave de la app) y durante la ventana de historial de Neon
  (**se fija en 1 día**, paso manual en la consola de Neon → Settings → Storage → History retention). La foto en el bucket: ≤ 2 días (versiones viejas, regla de 1 día).
  En producción la regla también acorta los volcados de la VM en `db/` (compatible con su retención de 30 días). **Comando para Juan David (staging;
  aplica también las reglas de la app, como hace el bootstrap):**
  ```bash
  python3 -c 'import json; a, b = (json.load(open(f)) for f in ("deploy/gcs-app-lifecycle.json", "deploy/gcs-lifecycle.json")); print(json.dumps({"rule": a["rule"] + b["rule"]}))' > /tmp/lc.json
  gcloud storage buckets update gs://goldenweb-staging-golden-staging --lifecycle-file /tmp/lc.json --quiet
  ```
  Tras la migración `0051` en staging (la corre el Job `golden-migrate-staging` en el próximo despliegue) el primer `purge` no borra nada por sorpresa (ver B2).
- [x] B5. Pruebas: `tests/test_biometric_retention.py` (una persona/un evento, dos eventos con uno abierto, reapertura, reenviar el mismo estado, tope de 180,
  huérfanas, idempotencia y lotes, fallo de Storage, dry-run, paso del Job solo con conteos, permisos y nombre del botón, omisión del borrado manual,
  ciclo de vida de respaldos) y ajustes en `tests/test_privacy.py`.
- Sustituye a R4 (tabla de arriba): la persistencia máxima tras la purga pasa a **30 días** (respaldos diarios) y la retención automática a 7 días tras finalizar.

### Sesión 4 — D.2: latencia y región, IP real, carga distribuida y cambio (lo que corre Juan David; Claude Code dejó scripts y pasos)

**D2.1 Latencia app → Neon y región (medido; la decisión y la tabla completa están en docs/13 §15).**
- Medido desde Cloud Run con conexiones calientes: una consulta cuesta **15,1 ms en us-east1 y 4,9 ms en us-east4**; conexión nueva 107 ms frente a 49 ms; transacción de 3 sentencias 75,5 ms frente a 23,8 ms.
- `/ready` no mide UNA consulta: `ops._db_probe` cronometra `db.execute("SELECT 1")` **incluyendo el préstamo de la conexión del pool**, y el pool tiene `pool_pre_ping=True`, que antes de entregar la conexión hace
  OTRO `SELECT 1`: son 2 idas y vueltas (2 × 15,1 ≈ 30 ms de los 43-46 vistos en staging; el resto no se descompuso). No es conexión nueva, ni «Neon despertando», ni varias consultas.
- **Por qué importa para los formularios:** con la fila bloqueada corren `form_reserve_slot()` + `INSERT` + `COMMIT` ≈ 3 RTT: ≈ 45 ms en us-east1 (~22 envíos/s por formulario) y ≈ 15 ms en us-east4 (~68/s), frente a la meta de la
  Fase 4 de ~42/s. **Decisión (Juan David, 2026-09-29): `us-east4`; procedimiento exacto en «Mover a otra región» (arriba).**
- **Medir con conexiones calientes desde Cloud Run** (`scripts/measure_db_latency.py`: conexión nueva, `SELECT 1` = 1 RTT, dos seguidos = ping + consulta, préstamo del pool = lo de `/ready`,
  y una transacción de 3 sentencias). En us-east1 se usa el Job que ya existe (imagen y secretos de staging):
  ```bash
  gcloud run jobs execute golden-ops-staging --region us-east1 --args="-m,scripts.measure_db_latency,--n,300" --wait
  gcloud logging read 'resource.type="cloud_run_job" AND textPayload:"LATENCY_RESULT"' --project goldenweb-staging --limit 1 --format='value(textPayload)'
  ```
  Para `us-east4` hace falta un Job temporal ALLÍ (mismos secretos; sin reintentos, 5 min máximo; se borra al terminar). Imagen: la que usa staging hoy
  (`gcloud run jobs describe golden-ops-staging --region us-east1 --format='value(spec.template.spec.template.spec.containers[0].image)'`):
  ```bash
  IMG=<la imagen de arriba>          # el Artifact Registry es regional pero se puede leer entre regiones del mismo proyecto
  gcloud run jobs create golden-latency-probe --region us-east4 --image "$IMG" --service-account golden-ops-staging@goldenweb-staging.iam.gserviceaccount.com \
    --command python --args="-m,scripts.measure_db_latency,--n,300" --tasks 1 --max-retries 0 --task-timeout 300 --cpu 1 --memory 512Mi \
    --set-secrets DATABASE_URL=golden-database-url-staging:latest,DIRECT_DATABASE_URL=golden-direct-database-url-staging:latest
  gcloud run jobs execute golden-latency-probe --region us-east4 --wait
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="golden-latency-probe" AND textPayload:"LATENCY_RESULT"' --project goldenweb-staging --limit 1 --format='value(textPayload)'
  gcloud run jobs delete golden-latency-probe --region us-east4 --quiet
  ```
  (Los nombres de secreto salen de `deploy/gcp/config.sh`: `golden-<nombre>-staging`; si el de la conexión directa se llama distinto, `gcloud secrets list`.) Pegar el resultado en esta sección.
  Regla: si `select1_warm_1rtt` en `us-east1` da ≥ 12 ms y en `us-east4` ≤ 4 ms → `us-east4`.

**D2.2 IP real del cliente detrás de Firebase Hosting** *(procedimiento de MEDICIÓN original; el hallazgo y la corrección que lo reemplazan van justo debajo, «D2.2 · Hallazgo en staging y corrección»)*. Antes: `TRUST_CF_CONNECTING_IP=0` (Cloudflare solo es DNS: esa cabecera se puede inventar) y `XFF_CLIENT_INDEX=0` (la PRIMERA entrada de
`X-Forwarded-For`). El riesgo: si Firebase/Cloud Run AGREGAN al final de una cadena que trae el cliente, la primera entrada es lo que el cliente escribió (se puede inventar y esquivar los límites
por IP); si en cambio quedara la IP de Google, todos compartirían un mismo límite. Nuevo diagnóstico `GET /api/ops/client-ip` (admin+ u `X-Ops-Token`): devuelve la cadena tal como llega, cuántas entradas
y cuál toma `client_ip()`. Procedimiento (desde tu casa o desde el móvil con datos, para conocer tu IP pública real: <https://ifconfig.me>):
  ```bash
  OPS_TOKEN=$(gcloud secrets versions access latest --secret golden-ops-token-staging --project goldenweb-staging)     # no lo pegues en el chat
  curl -s -H "X-Ops-Token: $OPS_TOKEN" https://golden-staging-<número>.web.app/api/ops/client-ip
  curl -s -H "X-Ops-Token: $OPS_TOKEN" -H "X-Forwarded-For: 6.6.6.6" https://golden-staging-<número>.web.app/api/ops/client-ip     # con una entrada inventada
  ```
  Lectura: en la 1.ª respuesta busca tu IP en `x_forwarded_for` y anota su posición contando desde el FINAL (p. ej. penúltima = −2). En la 2.ª, `6.6.6.6` debe aparecer al principio y la
  tuya seguir en la misma posición contada desde el final: entonces el índice correcto es el NEGATIVO (`−2`, no `0`) y `XFF_CLIENT_INDEX: "-2"` en `deploy/gcp/env/common.yaml` (más un
  redespliegue). Si tu IP es la ÚNICA entrada (Firebase la reescribe), `0` es correcto y no se puede inventar. Con `TRUST_CF_CONNECTING_IP=0` no hay que cambiar nada más. **No cambié el valor
  hoy** porque sin este tráfico real un índice equivocado es peor que `0`. **Ojo con la carga:** la prueba de carga fija su propia `X-Forwarded-For` por usuario virtual; si el índice
  pasa a `−2` los 20 generadores compartirán IP (20 IPs) y toparán el límite por IP de los formularios: correr la Fase 4 ANTES del cambio de índice, o con `PUBLIC_LIMIT_FACTOR` alto temporal.

**D2.2 · Hallazgo en staging y corrección (opción D, implementada 2026-09-29).** Medido desde Cloud Shell (IP real 34.139.233.0): por Firebase (`web.app`) la cadena es `[IP real, IP de Google]` (la de Google cambia entre llamadas: 66.102.8.224,
74.125.210.70) y una `X-Forwarded-For` falsa se descarta; por `run.app` directo la cadena es `[lo que escribió el cliente, IP real]`, así que con `XFF_CLIENT_INDEX=0` un atacante fijaba su «IP» y esquivaba los límites. Ningún índice fijo sirve para los dos
caminos (ambas cadenas tienen 2 entradas), así que la app **quita del FINAL de la cadena las IPs de infraestructura de Google y toma la última que queda** (`security.client_ip`, `XFF_STRIP_GOOGLE=1` en `common.yaml`): por Firebase queda la IP real,
por run.app también (la última la agrega Google; el atacante solo controla lo de la izquierda). Los rangos son `goog.json` MENOS `cloud.json` (`app/google_infra_cidrs.txt`, 402 rangos): 66.102.x y 74.125.x entran, y Cloud Shell/VM de clientes (34.x…) NO,
así que cuentan como visitantes. Tests con las cadenas reales medidas en `tests/test_client_ip_strip.py`. Supuestos (marcados): (a) Firebase Hosting y el frontend de Cloud Run siguen agregando UNA IP de Google al final y esa IP sigue dentro de `goog.json`;
(b) las llamadas internas (Cloud Tasks a `/internal/jobs/run`, Scheduler, Jobs) no dependen de la IP (las protege el token OIDC; el Scheduler y los Jobs ni pasan por HTTP), así que no cambian.
- **Lista vieja (dos protecciones).** (1) Si TODA la cadena es de Google (llamada interna que llega a un límite, o la IP de un visitante que cae en un rango de Google), `limit_ip()` devuelve `None`: se SALTA el límite por IP (siguen los de por usuario/cédula) en vez de juntar a todos
  en un solo cubo y bloquearlos a la vez; queda contado. (2) «Estado del sistema» tiene el chequeo **IP del visitante**: ROJO si hubo visitas con cadena toda de Google en los últimos 10 min; AMARILLO si una IP concentra ≥ 60 % de las peticiones (≥ 100 en 5 min) con ≥ 20 navegadores distintos
  (puede ser el wifi de un evento —sube `PUBLIC_LIMIT_FACTOR`— o un proxy nuevo de Google que la lista no conoce) o si la lista tiene más de 45 días. No se desactiva el límite automáticamente por concentración: los navegadores «distintos» los declara el cliente y un atacante podría fingirlos para apagar su propio límite.
- **Refrescar la lista (cada mes y antes de un evento grande):** `python scripts/refresh_google_cidrs.py` (descarga goog.json y cloud.json, reescribe `app/google_infra_cidrs.txt`), commit y despliegue. Para probar sin desplegar código: `python scripts/refresh_google_cidrs.py --print` y ponerlo en la variable
  `XFF_STRIP_CIDRS` del servicio (coma-separado; «auto» o vacío = el archivo). **Ojo con las comas en gcloud:** una lista con comas NO puede ir en `--update-env-vars` a secas (gcloud la parte en variables falsas); usa un delimitador alterno:
  `gcloud run services update golden-web-staging --region "$REGION" --update-env-vars "^@^XFF_STRIP_CIDRS=$(python scripts/refresh_google_cidrs.py --print)"` (o un `--env-vars-file`). Regla del repo: ningún script pasa valores con comas en `--set/--update-env-vars` (`tests/test_gcloud_env_vars.py`). Fecha de la lista actual: `python scripts/refresh_google_cidrs.py --age`.
- **Prueba de carga:** los generadores están en Google Cloud (clientes: NO se quitan), pero la app ya no cree la `X-Forwarded-For` que ponen (todos los usuarios virtuales de una tarea comparten IP real): sube el límite SOLO mientras dura la prueba y devuélvelo:
  `gcloud run services update golden-publico-staging --region "$REGION" --update-env-vars PUBLIC_LIMIT_FACTOR=200` (y lo mismo con `golden-web-staging` para los límites de login) antes de `run_phase4.sh run`; al terminar:
  `gcloud run services update golden-publico-staging --region "$REGION" --remove-env-vars PUBLIC_LIMIT_FACTOR` (vuelve a 1). Atajo: `bash deploy/loadtest/run_phase4.sh limits-up` antes de `run` y `limits-down` al terminar. Un redespliegue del workflow también lo devuelve (las variables vienen de `common.yaml`). Los límites de login por IP (20 fallos) no dependen de esa variable: la carga solo inicia sesión bien.

**D2.3 Prueba de carga distribuida contra staging** (`deploy/loadtest/`, `scripts/seed_load_staging.py`, `scripts/loadgen_report.py`; generadores = Cloud Run Jobs con Locust; solo staging: el
generador se niega a apuntar a un host sin «staging» y al dominio de producción). Criterios (docs/13 §11): formularios 10.000 aperturas en 60 s + 5.000 envíos en 120 s con 0 errores 5xx, p95 del
envío < 2 s, cero sobrecupos y cero duplicados; cédula 200 estaciones × 30 min (~57/s) p95 < 500 ms; facial referencia 30/s con p95 < 2 s; aislamiento: la latencia de la cédula durante el pico
de formularios sube ≤ 20 %.
  - Datos: 5.000 personas sintéticas y encodings aleatorios en el evento `LOAD-STG` (tenant `carga-staging`), un formulario con **cupo 4.000 < 5.000 envíos** a propósito (el 409 «cupo
    completo» es correcto y se cuenta; sobrecupo = más de 4.000 confirmadas). La clave de `carga_dig` se deriva de `OPS_TOKEN` (nunca se imprime). Sin fotos reales en la nube: el escenario facial usa la
    foto de dominio público (astronauta) o, sin rostro, mide solo la detección.
  - *(Sustituido por «D2.3 · Corrida completa», más abajo; se deja como referencia.)* Pasos (en Cloud Shell, desde el clon de `migra/fase1-2`): `bash deploy/loadtest/run_phase4.sh build` → `seed` → (leer `LOAD_SEED`: `event_id`) → `WEB_URL=https://golden-staging-<número>.web.app LOAD_EVENT_ID=<id> run` →
    cuando terminen los Jobs, `report <exec_forms> <exec_cedula> <exec_face>` → `verify` → `cleanup`. El script imprime los comandos exactos. Tope de costo: 20 tareas × 1 vCPU × ≤ 34 min (cédula) +
    3 min (formularios) + 9 min (facial) ≈ 8-9 vCPU-horas ≈ **US$1-3**, sin reintentos y con `task-timeout`; los Jobs se borran en `cleanup`. Neon: el pico sube el cómputo (autoescala): fijar
    el máximo en 2-4 CU para tener tope (`Settings → Compute` en la consola) y comprobarlo antes.
  - Para que el facial no se cuelgue por instancias: el precalentamiento sube `biometria` a mínimo 1 solo si hay un evento en proceso con rostro (sí, `LOAD-STG`); para 30/s hacen falta ~6 instancias
    (≈ 5 escaneos/s por proceso con 2 jitters): subir `--max-instances` y `--min-instances` temporalmente y bajarlos después.
  - Criterios que salen de la base: `verify` imprime `oversold`, `duplicate_persons`, `duplicate_sids` y `access_logs_in_event` (deben ser 0, 0, 0 y ≥ los 200 de «POST checkin-cedula»).
**D2.3 · Corrida completa: orden único, con el valor esperado de cada verificación.** (Reemplaza a los «Pasos» de arriba. Todo en Cloud Shell, desde el clon de `migra/fase1-2`; `REGION` = la de los servicios de staging, us-east4;
los comandos vienen de `deploy/loadtest/run_phase4.sh`, que lee proyecto, región y nombres de `deploy/gcp/config.sh staging`.)

*Antes de empezar*
1. `git pull && export REGION=us-east4 && gcloud config set project goldenweb-staging` (o `gcloud config set run/region us-east4`).
2. `bash deploy/loadtest/run_phase4.sh quota` (opcional): confirma la cuota de CPU y memoria de la región (200 vCPU / ~400 GiB; la prueba pide hasta 55 vCPU y ~54 GiB en el peor caso: cabe con margen, sección «CPU simultánea» abajo).
3. Neon (consola → Settings → Compute): máximo 2-4 CU, para tener tope de costo durante el pico.
4. `bash deploy/loadtest/run_phase4.sh build` (imagen del generador en el repositorio de staging).
5. `bash deploy/loadtest/run_phase4.sh seed` → imprime `LOAD_SEED {"event_id": N, "form_slug": "carga", "people": 5000, "capacity": 4000}`. Esperado: `people` 5000, `capacity` 4000. **Los logs de Cloud Logging tardan en aparecer:** el script reintenta la lectura cada 10 s hasta 2 minutos (`LOG_WAIT_SECONDS` la cambia) y, si no sale, falla diciendo que el seed SÍ terminó y cómo leerla a mano: `gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="golden-ops-staging" AND textPayload:"LOAD_SEED"' --project goldenweb-staging --limit 1 --freshness 3d --format='value(textPayload)'` (o Logging → Explorador de registros, texto «LOAD_SEED»); `verify` también imprime `event_id`. Con el id: `LOAD_EVENT_ID=<id> bash deploy/loadtest/run_phase4.sh run …`. **`seed` es idempotente:** repetirlo no duplica ni el evento, ni el formulario, ni las personas, ni la cuenta `carga_dig` (busca por código de evento, formulario y cliente; solo agrega las personas que faltan y actualiza el cupo); pedir menos personas no borra. Para empezar desde cero: `purge-data` y luego `seed`. **`build`**: usa `deploy/loadtest/Dockerfile.dockerignore` (lista blanca de 3 archivos) en lugar del `.dockerignore` de la app, que no se ensanchó; la imagen se comprobó con un build real (3 archivos, Locust 2.46). **Los pasos van encadenados con `&&`** (`build && seed`…): `build` aborta con código 1 si falla el build o el push.
6. `bash deploy/loadtest/run_phase4.sh limits-up` (sube `PUBLIC_LIMIT_FACTOR`; los generadores comparten IP real).
7. `bash deploy/loadtest/run_phase4.sh scale-up` (sube min/max de web, publico y biometria y GUARDA los originales en `~/.golden_phase4_scale_<proyecto>.txt`).

*Modo pequeño (~5 %, ~3 min): valida la cadena entera antes de gastar la corrida completa*
8. `bash deploy/loadtest/run_phase4.sh run small` (1 tarea por escenario: 500 aperturas y ~250 envíos, 10 estaciones de cédula 2 min, 3 usuarios faciales 1 min). Anota los 3 nombres de ejecución.
9. Cuando terminen (~3 min): `bash deploy/loadtest/run_phase4.sh report <exec_forms> <exec_cedula> <exec_face>`. Esperado: los tres «CUMPLE», 0 fallos y 0 5xx. Si algo falla aquí, arréglalo antes de seguir (el destino, el token, la cuota o la siembra).
10. `bash deploy/loadtest/run_phase4.sh verify`. Esperado: `oversold` **0**, `duplicate_persons` **0**, `duplicate_sids` **0**, `confirmed_submissions` = respuestas 200 de «POST envio» del informe (~250; ≤ 4000), `access_logs_in_event` ≥ respuestas 200 de «POST checkin-cedula» (igual, sin caídas).
11. `bash deploy/loadtest/run_phase4.sh reset-data`: deja en cero inscripciones e ingresos (evento, formulario y personas se quedan). Esperado: `LOAD_RESET` con `form_submissions` y `access_logs` iguales a lo verificado en el paso 10; un `verify` posterior da 0 y 0.

*Aislamiento (criterio «la cédula no sube más de 20 % durante el pico de formularios»)*
12. Línea base: `ONLY=cedula CEDULA_MIN=5 bash deploy/loadtest/run_phase4.sh run` → `report - <exec_cedula> -`. Anota el p95 de «POST checkin-cedula».
13. `reset-data`. Con pico: `ONLY=forms,cedula CEDULA_MIN=5 bash deploy/loadtest/run_phase4.sh run` → `report <exec_forms> <exec_cedula> -`. Esperado: el p95 de la cédula ≤ 1,2 × el de la línea base (y < 500 ms); formularios p95 < 2 s, 0 5xx.

*Corrida completa con el simulacro 1 (matar una instancia)*
14. `reset-data`, y `gcloud run services update golden-web-staging --region "$REGION" --update-env-vars CHAOS_ENABLED=1`.
15. `bash deploy/loadtest/run_phase4.sh run` (formularios 10.000/5.000, cédula 200 estaciones × 30 min, facial 60 usuarios). Anota los 3 nombres de ejecución.
16. Minuto ~10 (cédula en marcha): `curl -s -X POST -H "X-Ops-Token: $OPS_TOKEN" https://golden-web-staging-<número>.$REGION.run.app/api/ops/simulate-crash` (2-3 veces, con unos segundos entre una y otra). Esperado: `{"crashing": true}` y la instancia se reemplaza sola; puede haber unos 5xx en ese instante.
17. Al terminar (~35 min): `report <exec_forms> <exec_cedula> <exec_face>`. Esperado: forms p95 «POST envio» < 2 s y 0 5xx en la ventana de formularios; cédula p95 < 500 ms (los fallos se limitan a los segundos del simulacro); facial p95 < 2 s (los 503 «reintenta» son contención esperada; revisa cuántos).
18. `verify`. Esperado: `oversold` **0**; `duplicate_persons` **0**; `duplicate_sids` **0**; `confirmed_submissions` = **4000** (hubo ~5.000 intentos y el cupo es 4000; si los 200 de «POST envio» fueron menos de 4000, = ese número); `access_logs_in_event` **≥** las respuestas 200 de «POST checkin-cedula» (ningún ingreso confirmado se perdió; puede ser mayor por peticiones cuya respuesta se perdió al caer la instancia). Después: `gcloud run services update golden-web-staging --region "$REGION" --remove-env-vars CHAOS_ENABLED`.

*Simulacro 2 (reiniciar el cómputo de Neon)*
19. `reset-data`; `ONLY=forms,cedula CEDULA_MIN=10 LOAD_THINK_MAX=120 bash deploy/loadtest/run_phase4.sh run` (el pico de formularios dura ~4 min).
20. Minuto ~2 (pico de formularios): `curl -s -X POST "https://console.neon.tech/api/v2/projects/$NEON_PROJECT_ID/endpoints/$NEON_ENDPOINT_ID/restart" -H "Authorization: Bearer $NEON_API_KEY"` (o «Restart compute» en la consola). La llave va en una variable de entorno, nunca en el chat.
21. `report <exec_forms> <exec_cedula> -` y `verify`. Esperado: `oversold` **0**, `duplicate_persons` **0**, `duplicate_sids` **0**, `confirmed_submissions` = respuestas 200 de «POST envio» (primer envío); puede ser mayor solo por envíos cuya respuesta se perdió durante el reinicio (nunca por duplicados: el reintento con la misma `sid` da «replayed»); `access_logs_in_event` ≥ respuestas 200 de «POST checkin-cedula».

*Cierre (siempre, aunque algo haya fallado)*
22. Devolver lo tocado: `bash deploy/loadtest/run_phase4.sh scale-down` (restaura min/max ORIGINALES desde el archivo), `bash deploy/loadtest/run_phase4.sh limits-down`, quitar `CHAOS_ENABLED` si quedó (`--remove-env-vars CHAOS_ENABLED`) y devolver el máximo de Neon a su valor.
23. `bash deploy/loadtest/run_phase4.sh cleanup` (borra SOLO los 3 Jobs del generador). Los datos sintéticos se quedan hasta que corras `bash deploy/loadtest/run_phase4.sh purge-data` (escribir `LOAD-STG`; borra el evento LOAD-STG, el formulario, las 5.000 personas, las inscripciones e ingresos, la cuenta `carga_dig` y el cliente `carga-staging`, y nada más). Opcional: borrar la imagen `loadgen` de Artifact Registry.
24. Al día siguiente: Facturación → Informes (por SKU): sin consumo sostenido de Cloud Run/Neon fuera de lo esperado.

**D2.3 · CPU simultánea máxima (¿alcanza la cuota de Cloud Run de la región?).** Por instancia: web 1 vCPU / 1 GiB, publico 1 vCPU / 1 GiB, biometria 2 vCPU / 2 GiB (`deploy/gcp/deploy.sh`, máximo 10 instancias cada uno); generadores 1 vCPU / 1 GiB por tarea; Job de operaciones 1 vCPU (seed/verify, momentáneo).
| Componente | vCPU máx. con los topes de `deploy.sh` (10 instancias) | vCPU máx. con `scale-up` (topes 6) | Esperado bajo carga |
|---|---:|---:|---:|
| web (cédula ~57/s + logins) | 10 | 6 | ~3 |
| publico (10.000 aperturas + 5.000 envíos) | 10 | 6 | ~3 |
| biometria (60 usuarios ≈ 17 escaneos/s; ~9/s por instancia con 2 jitters) | 20 | 12 | ~6 |
| generadores: forms 6 + cédula 4 + facial 4 tareas | 14 | 14 | 14 |
| Job de ops (seed/verify) | 1 | 1 | ~1 |
| **Total** | **55** | **39** | **~27** |
Memoria simultánea análoga: ~54 GiB con los topes por defecto (web 10 + publico 10 + biometria 20 + generadores 14), ~38 GiB con topes 6, ~25 GiB esperado.
**Cuota de la región (dato de Juan David, 2026-09-29):** en us-east4 la cuota de Cloud Run es **200 vCPU y ~400 GiB de memoria**; uso actual **3,75 vCPU y 4 GB**.
| | Necesita la prueba | Uso actual | Suma | Cuota | Ocupación |
|---|---:|---:|---:|---:|---:|
| CPU, peor caso (topes de `deploy.sh`: 10 instancias por servicio) | 55 vCPU | 3,75 | 58,75 | 200 | **29 %** |
| CPU, con `scale-up` (topes 6) | 39 vCPU | 3,75 | 42,75 | 200 | 21 % |
| CPU, esperado | ~27 vCPU | 3,75 | ~31 | 200 | ~15 % |
| Memoria, peor caso | ~54 GiB | 4 | ~58 | ~400 | **~15 %** |
| Memoria, esperado | ~25 GiB | 4 | ~29 | ~400 | ~7 % |
**Cabe con margen** (el peor caso usa menos de un tercio de la CPU y ~15 % de la memoria), así que **no hace falta correr los generadores en otra región**: todo va en la región de los servicios, como en producción. Los topes de `scale-up` (6 por servicio) no son por la cuota sino para acotar costo
y que la prueba no escale sin límite; si quieres que el facial llegue a la referencia de 30/s, sube el de biometria (`SCALE_BIO="4 8"`): 8 instancias = 16 vCPU, siguen cabiendo de sobra.

**D2.3 · Instancias: comandos exactos para subir y bajar** (lo hace `run_phase4.sh scale-up` / `scale-down`; aquí van a mano por si prefieres). El mínimo es a nivel de SERVICIO (API v2, el mismo mecanismo de `app/warmup.py`, no crea revisión); el máximo va en la plantilla (`gcloud`, crea una revisión):
```bash
PROJECT=goldenweb-staging; REGION=us-east4            # o el que uses
TOKEN=$(gcloud auth print-access-token)
for S in golden-web-staging golden-publico-staging golden-biometria-staging; do        # 1) ANOTA los ORIGINALES (min max)
  echo -n "$S: "; curl -fsS -H "Authorization: Bearer $TOKEN" "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/services/$S" \\
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("scaling") or {}).get("minInstanceCount", 0), (d.get("template", {}).get("scaling") or {}).get("maxInstanceCount", 10))'
done
# 2) SUBIR (ejemplo: web 2/6, biometria 3/6)
curl -fsS -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"scaling":{"minInstanceCount":3}}' \\
  "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/services/golden-biometria-staging?updateMask=scaling.minInstanceCount"
gcloud run services update golden-biometria-staging --project "$PROJECT" --region "$REGION" --max-instances 6
curl -fsS -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"scaling":{"minInstanceCount":2}}' \\
  "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/services/golden-web-staging?updateMask=scaling.minInstanceCount"
gcloud run services update golden-web-staging --project "$PROJECT" --region "$REGION" --max-instances 6
# 3) RESTAURAR con los valores anotados en el paso 1 (repite los dos comandos por servicio con esos números)
```
**Valores originales esperados** (los que deja `deploy.sh`/el precalentamiento; confírmalos con el paso 1, porque el precalentamiento puede haberlos movido): máximo **10** en los tres servicios; mínimo **0** si no hay eventos en proceso (staging no tiene el Scheduler; con el evento LOAD-STG en proceso, un paso `warmup` del Job de ops puede dejar web en 2 y biometria en 1, y publico en 2 alrededor de la apertura de un formulario). `scale-down` restaura exactamente lo que `scale-up` leyó y guardó. No cambies estados de eventos ni abras formularios durante la prueba (`warmup.kick()` movería los mínimos).

**D2.3 · Los generadores no pueden apuntar a producción** (aunque `WEB_URL` esté mal escrita). Cuatro candados: (1) `run_phase4.sh run` aborta si el host de `WEB_URL` no es EXACTAMENTE uno de los de staging que calcula `config.sh staging` (el sitio de Firebase `golden-staging-<n>.web.app` o los `run.app` de web/publico/biometria de staging); un nombre de producción, un typo o cualquier otro se rechaza antes de crear nada. (2) Cada tarea recibe `LOAD_ALLOWED_HOSTS` con esa lista y vuelve a comprobarla (`scripts/load_cfg.check_host`: https, contiene «staging», no es `golden-eventos…`, y coincide con uno de los permitidos); sin la lista no genera carga. (3) La cuenta de carga es `carga_dig` con clave derivada del `OPS_TOKEN` de STAGING y un evento que solo existe en la base de staging: contra producción el inicio de sesión fallaría. (4) `seed_load_staging.py` se niega a correr sin `DEPLOY_ENV=staging` y host de Neon. Pruebas en `tests/test_load_tools.py`.

**D2.3 · Resultado de la 1.ª prueba de formularios (10.000 usuarios, 6 tareas) y cambios en el camino del formulario público (2026-09-29).** Medido: `POST envio` p50 26 s / p95 56 s, `GET state` p50 10 s, 1.516 fallos en `state` (429 «Rate exceeded.» de Cloud Run y 500) y 400 × 429, 316 × 500, 188 × 502 en el envío; integridad intacta (oversold 0, sin duplicados, 4000 confirmadas). Causas (por lectura del código): (1) el bloqueo de la fila del formulario duraba ~5 idas y vueltas (`reserve`, `INSERT`, `SELECT Event`, `INSERT FormEvent`, `COMMIT`) → ~33 envíos/s por formulario frente a ~85/s ofrecidos: cola de decenas de segundos; (2) cada envío en cola retenía un hilo (24 por proceso) y una conexión (20 por proceso); (3) `GET state` es un endpoint `def` y esperaba un hilo libre aunque fuera un acierto de caché (p50 ≈ 10 s); (4) al pasar de 400 peticiones en vuelo (10 instancias × concurrencia 40) Cloud Run responde 429 «Rate exceeded.» (texto que NO es de la app; inferencia). Cambios (todos sin migraciones y sin tocar la integridad): `state` y la página sirven el ACIERTO de caché en el bucle de eventos (sin hilos ni base), con UNA sola recarga a la vez por clave y un solo conteo de cupo por fallo (`held_count` ahora es una sola consulta); el envío libera la conexión antes de validar (DNS del correo, archivos) y usa una vía rápida para el «cupo lleno» (caché de ~2 s, sin bloqueo, que se invalida al liberarse un cupo y nunca deja pasar de más: `form_reserve_slot` revalida bajo bloqueo; un reintento con la misma `sid` sigue respondiendo «replayed»); dentro del bloqueo solo quedan `reserve`, `INSERT` y `COMMIT` (el `SELECT Event` solo con archivos y el `INSERT` de la analítica va DESPUÉS del commit); y contrapresión: `lock_timeout` de 3 s (`FORM_LOCK_TIMEOUT_MS`) → 503 + `Retry-After: 2`, que el navegador reintenta con la misma `sid`. La consulta MX del correo ya tenía caché de 1 h (corrección a mi análisis anterior): ahora también se recuerdan 60 s los fallos del DNS y el tiempo máximo baja de 4 a 2 s. `run_phase4.sh run` hace una comprobación previa (PUBLIC_LIMIT_FACTOR 200 y máximos de instancias esperados) porque un despliegue de CI los borra (`--env-vars-file` reemplaza todas las variables).
**D2.3 · 2.ª ronda (f52b2fd → siguiente commit): la caché ya no bloquea, el envío espera un solo hilo, diagnóstico de esperas y caché pública opcional.** Resultado de f52b2fd: fallos 904 → 5, pero `POST envio` p50 8,3 s / p95 31 s y `GET state` p50 9,8 s / p95 30 s (la página, 120 ms). Lectura: el pool de hilos (24 por proceso, cola FIFO) se saturaba con peticiones de `state` que esperaban DENTRO de un candado la recarga de la caché, y cada envío pedía dos turnos (uno para `Depends(get_db)`, otro para el envío). Cambios (sin migraciones; NO se tocan `THREADPOOL_SIZE`, `DB_POOL_SIZE` ni la concurrencia de Cloud Run: una variable por corrida):
- **A · stale-while-revalidate.** Un valor vigente se sirve al instante; uno VENCIDO (hasta `FORM_PUBLIC_STALE_SECONDS`, 5 s por defecto, después de su TTL) también, y un hilo propio (no del pool) lo refresca, uno solo por clave; solo si no hay nada utilizable se espera, con `await` a una tarea única (no ocupa hilos). `state` y la página ahora son `async` (`_cached_async`, `TTLCache.peek`). Si la recarga falla se sigue sirviendo el valor viejo hasta que pase el margen.
- **B ·** `submit` ya no usa `Depends(get_db)`: abre la sesión dentro de su único salto al hilo (`_submit_sync`).
- **C · diagnóstico, apagado por defecto** (`app/timing.py`). `SERVER_TIMING=1` + `OPS_TOKEN` en el servicio: la respuesta lleva `Server-Timing: app;dur, thread;dur (espera de hilo), pool;dur (espera de conexión), db;dur, queries, threads;desc="borrowed=X/Y waiting=Z"` SOLO si la petición trae `X-Timing-Token` (derivado del `OPS_TOKEN`: `scripts/load_cfg.timing_token()`; Locust lo manda solo). `LOG_SLOW_WAITS_MS=N`: línea `golden.timing` «espera lenta …» cuando una petición esperó ≥ N ms por hilo o conexión (ruta enmascarada, solo milisegundos y contadores; nada de personas). Locust registra además una petición «[fuera de la app] <nombre>» = latencia medida por el cliente − `app;dur`: lo que queda en Cloud Run (cola de concurrencia), red, Firebase y el propio generador. Para encenderlo en staging: `gcloud run services update golden-publico-staging --region "$REGION" --update-env-vars ^@^SERVER_TIMING=1@LOG_SLOW_WAITS_MS=500` (delimitador alterno `^@^`, como pide el resto de la documentación) (el `--env-vars-file` del CI las borra en el siguiente despliegue).
- **D · `s-maxage` público SOLO para el estado anónimo, apagado por defecto.** `FORM_STATE_CDN_SECONDS=N` (1-10; recomendado 4): `GET /f/<ev>/<slug>/state` responde `Cache-Control: public, max-age=0, s-maxage=N` únicamente sin parámetros, sin `Cookie` y sin `Authorization`; con `?k=`, `?i=`, `?t=` o cualquier otro parámetro, con cookie o con sesión NO se cachea (pruebas en `tests/test_state_cache_and_timing.py`). El cuerpo anónimo no tiene nada por usuario: diseño y tema, etapa, cupo restante global y textos del formulario, sin `Set-Cookie`. Efecto: con N=4, Firebase absorbe la mayoría de las aperturas y Cloud Run recibe ~1 petición de estado por cada 4 s por punto de presencia (no un cupo exacto: el cupo mostrado puede llevar hasta N + 2 s de retraso; el envío revalida el cupo bajo bloqueo, así que no hay sobreventa).
  **Activarlo y comprobar en staging** (Juan David; el navegador y la URL de Firebase son las de `config.sh staging`):
  ```bash
  gcloud run services update golden-publico-staging --region "$REGION" --update-env-vars FORM_STATE_CDN_SECONDS=4
  URL=https://golden-staging-<número>.web.app/f/<evento>/<slug>/state
  curl -sI "$URL" | grep -iE '^(cache-control|age|x-cache|x-served-by|cf-cache-status|via)'    # 1.ª: cache-control: public, max-age=0, s-maxage=4
  curl -sI "$URL" | grep -iE '^(cache-control|age|x-cache|x-served-by|cf-cache-status|via)'    # 2.ª (en <4 s): debe traer `age: 1..4` y/o `x-cache: HIT`
  curl -sI "$URL?k=x" | grep -i '^cache-control'                                                  # con parámetro: SIN s-maxage
  ```
  Las cabeceras `Age`/`X-Cache` de Firebase Hosting son una suposición que hay que confirmar en la primera prueba; la confirmación definitiva es contar las peticiones de `/state` en los registros de Cloud Run (`gcloud run services logs read golden-publico-staging --region "$REGION" --limit 200 | grep -c '/state'`) durante una ráfaga de `curl` repetidos: con caché activa deben ser muy pocas. Para apagarlo: `--remove-env-vars FORM_STATE_CDN_SECONDS`. Para que sobreviva a los despliegues (que reemplazan todas las variables) hay que ponerlo en `deploy/gcp/env/common.yaml`.
- **`run_phase4.sh scale-up` sin recorte a 6.** Los topes salen de `SCALE_WEB`, `SCALE_PUBLICO` (alias `SCALE_PUB`) y `SCALE_BIO`, en formato «min max»; por defecto `2 10`, `2 10` y `3 10`. **El máximo debe ser 10 para parecerse a producción** (10 instancias × 40 de concurrencia = 400 peticiones en vuelo; con 6 el límite de 240 hacía que Cloud Run respondiera 429 «Rate exceeded.» antes que la app). La comprobación previa de `run` usa los mismos valores. Cuota: la tabla de vCPU de más arriba (D2.3, cálculo de cuota) se calculó con máximos de 6; con 10 en cada servicio hay que recalcularla con los vCPU por instancia de `deploy.sh` (cabe con holgura en los 200 de us-east4, pero confírmalo antes de la corrida).

**D2.3 · Corridas 5 y 6 (instancias calientes) y contrapresión del envío.** Corrida 5 (publico min=max=10, Firebase): página p50 140 ms (la sirve la CDN, `s-maxage=60`: no mide las instancias), `state` p50 6 s / p95 25 s, envío p50 9,5 s / p95 28 s, 1.660 × 503 «busy»; corrida 6 (20 instancias): `state` p50 1,5 s, envío p50 7,4 s, ~80 % de 503 (antes ~15 %), 429 «Rate exceeded.». Lectura (logs de espera lenta: `db` ≈ 3 s también en los 409, hilos `waiting=0`, pool < 1 s): el cuello es la cola del `FOR UPDATE` del formulario (se sirve a ~35-50 reservas/s por formulario) y cada envío en cola retiene un turno de Cloud Run (concurrencia 40 × instancias) hasta el `lock_timeout` de 3 s; con ~90 envíos/s × ~4 s se acaban los turnos y `state`, que sale de caché en microsegundos, espera en la cola de Cloud Run («Pendiente»). Más instancias = más gente en la cola del bloqueo = más 503. Cambios (sin migraciones, la reserva bajo bloqueo sigue siendo la autoridad):
- **Precomprobación sin bloqueo** (`formsvc.precheck`, una lectura): reintento (misma `sid` → 200 «replayed»), cupo lleno (caché de ~2 s) y duplicado de cédula (409), en el mismo orden que `form_reserve_slot`, ANTES del `FOR UPDATE`. `form_reserve_slot` repite todas las comprobaciones (pruebas en `tests/test_form_backpressure.py`).
- **Analítica y aviso al worker después de responder** (`_respond`: `BackgroundTask`). `_record_submit_event` (INSERT con FK a `web_forms` → `FOR KEY SHARE`, que hacía fila detrás de los `FOR UPDATE` sin límite) ahora tiene `lock_timeout` propio (`FORM_EVENT_LOCK_TIMEOUT_MS`, 2000; si vence solo se pierde la marca). `jobs.kick()` solo si de verdad se encoló un trabajo (antes, con Cloud Tasks, era una llamada gRPC por CADA envío). `SUBMIT_AFTER_RESPONSE=0` lo devuelve a antes de responder. Fuera de una petición Cloud Run puede reducir la CPU; con tráfico hay CPU, y el trabajo encolado está en la tabla (lo recoge el siguiente aviso o el barrido).
- **Rechazo temprano:** contador por proceso de envíos en la zona del bloqueo; por encima de `FORM_MAX_LOCK_WAITERS` (3 por defecto, 0 = sin límite) responde 503 `busy` + `Retry-After` 1-3 s (variable) sin esperar el bloqueo ni tocar la base en ese momento (las lecturas de la precomprobación ya se hicieron; así los «replayed», duplicados y «cupo lleno» se contestan aunque haya cola). Se libera en `finally`; la vía del «cupo lleno» no lo cuenta. Cuenta: ~35-50 reservas/s por formulario y N×tope envíos esperando → cada uno espera ~N×tope/45 s; con 20 procesos (10 instancias × 2) son 60 esperando ≈ 1,3 s. Con más instancias hay que bajarlo (≈ 65 / (instancias × 2)). Recomendación pendiente de medir: `FORM_LOCK_TIMEOUT_MS` de 3000 a ~1500 (la cola acotada casi no debería llegar al tope; 1500 solo recorta el peor caso). No se cambió el valor por defecto: una variable por corrida.
- **Navegador** (`templates/form_public.html`): reintenta 502/503/504 y el 429 que NO es de la app (texto plano; los de la app traen JSON con `detail` y no se reintentan), respeta `Retry-After` como mínimo, espera creciente 1,5 → 3 → 6 → 12 s más azar, con la MISMA `sid`, hasta ~150 s en total (antes 5 intentos y ~35 s: con 80 % de rebote quedaban sin inscribir ~26 % de los usuarios). La apertura (`state`) también reintenta (~40 s) en vez de decir «no disponible».
- **Generador:** mismas reglas de reintento; los intentos «ocupado» se cuentan aparte («… (contrapresión 503)») y no son fallos; cada usuario que envía deja su resultado final («[usuario] inscrito / cupo lleno / se rindió tras N reintentos», con el tiempo total) y el informe los muestra en tablas propias.
- **Quién devuelve «Rate exceeded.»/429:** la app solo devuelve 429 en `forms_public.py::_limit` (límite por IP de envíos/beacon, JSON en español, `PUBLIC_LIMIT_FACTOR`), `security.py` (consultas públicas de certificados) y el inicio de sesión (`routers/auth.py`). `state` no tiene ningún limitador y en el código no existe el texto «Rate exceeded.» (inglés, texto plano): ese 429 es de la infraestructura de Google (cola de espera de Cloud Run desbordada), no de la app.

- **Criterio de aprobación de formularios (fijado con Juan David, corrida 7 en adelante)**, en `scripts/loadgen_report.py::forms_criteria`: `state` p95 < 2 s y p99 < 5 s (la página no cuenta: la sirve la CDN); ≥ 99 % de los usuarios que envían terminan «inscrito» o «cupo lleno»; p95 del tiempo TOTAL de quien se inscribe < 120 s (meta 60 s tras la función SQL única); 0 respuestas 5xx distintas de 503 «busy» **salvo la infraestructura** (aprobado por el responsable del proyecto tras la corrida 10): los 502/503/504 cuyo cuerpo NO es el JSON de la app (HTML de Google, «502 infra», «503 infra», «504 infra»), los 429 de infraestructura («Rate exceeded.») y las peticiones sin respuesta (cédula: «tiempo agotado», «error de red») se reportan aparte, con su tasa sobre el total de intentos, y NO fallan el criterio si la tasa es ≤ 0,1 % de los intentos Y el 100 % de los usuarios que envían terminaron con resultado; cualquier otro 5xx (500, 502, 504 y los 502/503/504 JSON de la app sin marca `busy`, «… app») sigue fallando. Cada respuesta se cuenta UNA vez: las líneas «[fuera de la app] …» son espejos de latencia y no se suman; ninguna tarea del generador «SATURADO»; y en la base (línea `LOAD_VERIFY`, que el informe lee si está en el mismo archivo) inscripciones confirmadas = min(capacidad, usuarios únicos que envían), 0 sobreventas, 0 cédulas o `sid` repetidas. La contrapresión se reporta aparte y no cuenta como fallo.
- **Duración del generador de formularios:** con reintentos de hasta ~150 s el peor usuario termina hacia 59 s (rampa) + 40 s (apertura) + 30 s (pensar) + 150 s = ~280 s, así que `LOAD_DURATION` de formularios pasó de 180 a 360 s (modo pequeño, de 120 a 180 s); el tiempo máximo de la tarea es `LOAD_DURATION + 240` = 600 s. Los usuarios que aún reintentan al agotarse `LOAD_DURATION` ya no desaparecen: salen como «[usuario] no terminó» (fallo).
- **DECISIÓN PENDIENTE para producción: `jobs.kick()` y la CPU de Cloud Run.** El servicio público usa CPU solo durante las peticiones (`deploy.sh` sin `--no-cpu-throttling`). Desde 600ebed la analítica y `kick()` corren después de responder; con tráfico hay CPU, pero con la instancia ociosa (o apagándose justo después) la tarea puede quedar en pausa o perderse. Consecuencias: la marca «submit» de analítica solo alimenta el abandono (`forms.py`, `abandoned = starts - sent`), perderla no toca la inscripción; un `kick()` perdido no pierde el trabajo (está en la tabla `jobs`; lo ejecuta cualquier `kick()` posterior o el barrido `sweep` del Job horario `golden-ops-hourly`, minuto 5: retraso máximo ≤ 1 h en producción; en staging el Scheduler está pausado). Solo afecta a formularios con `feed: realtime` (el de la prueba de carga es `manual` y no encola nada). Opciones, sin implementar: (a) agrupar `kick()` a una llamada por segundo por proceso y hacerlo ANTES de responder solo si de verdad se encoló algo (costo despreciable); (b) `--no-cpu-throttling` en el servicio público (CPU siempre asignada a las instancias vivas; costo: se factura la CPU de todo el tiempo que la instancia esté viva, no solo el de las peticiones). No se cambia nada hasta que se decida.
**D2.3 · Corrida 7 (commit 76390e6, publico 10 instancias calientes, Firebase, 10.000 aperturas, ~5.026 envíos, cupo 4.000): CUMPLE el criterio de formularios.** `state` p95 110 ms / p99 560 ms; envío p95 840 ms; 4.000 inscritos + 1.026 «cupo lleno»; 0 fallos reales; contrapresión (503 «busy» con reintento) en 35 % de los primeros intentos; p95 del tiempo total de quien se inscribe 8,6 s (límite 120 s, meta 60 s); generadores sin saturar; base: 4.000 confirmadas / 0 sobreventas / 0 duplicados. Recuento de las tres corridas: corrida 5 (10 instancias, antes de los cambios) `state` p50 6 s y envío p50 9,5 s con 1.660 × 503; corrida 6 (20 instancias) `state` p50 1,5 s pero ~80 % de 503 (más turnos = más gente en la cola del bloqueo); corrida 7 (con 600ebed/d2e3171): la precomprobación sin bloqueo, la analítica y `kick()` fuera de la respuesta, el tope de 3 esperas por proceso y los reintentos de ~150 s dejan el envío en el rango de la meta. Lo que se demostró: el cuello de botella era la cola del `FOR UPDATE` reteniendo turnos de Cloud Run, y acotarla (sin cambiar hilos, pool ni concurrencia) libera los turnos para `state`.

**D2.3 · Corrida 8 (commit 76390e6, publico min 2 / max 10, SIN precalentar): NO CUMPLE por dos puntos menores atribuibles al arranque de instancias durante el pico.** `state` p99 7,1 s (límite 5 s) y un 503 de infraestructura de Google (cuenta como 5xx distinto de 503 «busy»); todo lo demás bien: integridad (4.000 confirmadas / 0 sobreventas / 0 duplicados), 100 % de los usuarios con resultado, p95 del tiempo total de quienes se inscriben 32 s (límite 120 s; la corrida 7, con 10 instancias calientes, dio 8,6 s), 64 % de los primeros intentos con contrapresión (35 % en la corrida 7: con 4 procesos el tope por conteo son solo 12 esperas). Lectura: desde 2 instancias el servicio absorbe la ráfaga pero paga el arranque de las nuevas (10-20 s de plataforma, ver «Arranque de una instancia») justo cuando llegan los usuarios; con las instancias ya calientes (corrida 7) el criterio se cumple. De ahí la recomendación de precalentar (paso 4b del runbook D2.4).

**D2.3 · Corrida 9 (b9ba3df, 10 instancias calientes, `LOAD_SUBMIT_RATIO=1`: 10.000 envían) y el reciclaje de procesos.** Integridad OK (4.000 confirmadas / 0 sobreventas / 0 duplicados), 100 % de usuarios con resultado (inscritos p50 1,2 s / p95 26 s; «cupo lleno» p50 23 s / p95 53 s / máx 66 s), `state` p95 140 ms / p99 470 ms, generadores sin saturar, Neon holgado (~0,4 vCPU, ~200 de 905 conexiones, 0 deadlocks). Incumplió solo «0 5xx distintas de 503 busy» (6 503 de infraestructura sobre ~30.000 intentos) y hubo una cola lenta de ~5 % en los POST (p95 9 s, máx ~15 s, casi todo «fuera de la app»). **Causa CONFIRMADA con los registros de Cloud Run (05:41–05:50 UTC):** 20 líneas «Maximum request limit of N exceeded. Terminating process.» (N entre 1515 y 1793) entre 05:43:01 y 05:43:10: los 20 procesos de las 10 instancias se reciclaron por `max_requests` casi a la vez, en medio del pico (con carga pareja y las instancias arrancadas juntas todos llegan al límite a la vez; el jitter por defecto es de solo 300 sobre 1500), y coincidieron con 4 mensajes de Cloud Run «malformed response / connection error» (latencia 2-20 ms) de 3 instancias. Uvicorn registra ese mensaje en nivel INFO, por eso un filtro de WARNING+ no lo muestra. Cambios (sin migraciones):
- **`GUNICORN_MAX_REQUESTS=0` SOLO en el servicio público** (sin dlib; `web` y `biometria` siguen reciclando). Queda fijado en `deploy/gcp/deploy.sh` como argumento extra de `deploy_service` para `$SVC_PUBLICO`, no en `deploy/gcp/env/common.yaml` (que es de los tres servicios). `env_file` lo escribe en el archivo de variables del servicio (`GUNICORN_MAX_REQUESTS: "0"`) y el workflow `cloudrun-deploy.yml` corre `deploy.sh` en cada despliegue de staging y de producción, así que sobrevive al CI (una prueba ejecuta la función real de `deploy.sh` y comprueba el archivo). **Vigilar la memoria de las instancias mínimas, que viven días y ya no se reciclan:** en Cloud Run → servicio `golden-publico` → Métricas → «Utilización de memoria del contenedor» (métrica `run.googleapis.com/container/memory/utilizations`, p95/p99; sale por revisión) durante 24-72 h con instancias mínimas y compararla con la de un arranque reciente; tendencia creciente = fuga. Referencia local: ~185 MB de RSS por proceso sobre 1 GiB (2 procesos). Un «Memory limit of 1024 MiB exceeded» en los registros del sistema sería el síntoma final. Si creciera: un límite alto con jitter grande (p. ej. 50.000 con jitter del 50 %) o un despliegue periódico; los cambios de estado de un despliegue de CI ya reemplazan instancias.
- **`GUNICORN_KEEPALIVE`** (5 por defecto, sin cambio de comportamiento) para alargar el keepalive sin tocar código si la próxima corrida aún muestra 503 dispersos.
- **Contrapresión sin ruido:** los 503 «busy» (marca interna `X-Golden-Busy`, no basta `Retry-After`: el 503 de «base de datos caída» también lo lleva y es un error real) se registran en INFO, no llaman a `on_5xx` y no encienden «Estado del sistema»; los 5xx reales siguen igual, pero `ops.record_5xx` escribe en un hilo (antes lo hacía dentro del bucle de eventos: una consulta síncrona, con el pool agotado hasta `DB_POOL_TIMEOUT`, congelaba todas las peticiones del proceso).
- **`security.is_google_infra` con caché por IP** (recorría ~400 redes por petición de envío, ~0,6 ms).

**D2.3 · Tras la corrida 10 (commit fccadbd, `GUNICORN_MAX_REQUESTS=0` en el público: POST p95 1,2 s, 10.000 envíos, integridad exacta, 0 «Maximum request limit» en los registros).** Cambios previos a la prueba completa (sin migraciones):
- **Reciclaje de `web` (estaciones de cédula):** nueva variable `GUNICORN_MAX_REQUESTS_JITTER` (entero; sin ella sigue en 300). `deploy/gcp/deploy.sh` despliega `web` con `GUNICORN_MAX_REQUESTS=20000` y `GUNICORN_MAX_REQUESTS_JITTER=10000` (el workflow `cloudrun-deploy.yml` corre `deploy.sh`, así que sobrevive al CI) para que los reciclajes no coincidan bajo carga uniforme. NO se tocó biometría (se mide en una prueba larga) ni el público (`max_requests=0`), ni `deploy/gcp/env/common.yaml` (lo comparten los tres servicios).
- **Criterio de infraestructura** en `scripts/loadgen_report.py` (texto arriba, en «Criterio de aprobación de formularios»). El generador (`tests/load/locustfile.py`) ahora etiqueta el 503 JSON de la app sin marca `busy` como «503 app» (falla) y el HTML de Google como «503 infra» (tolerado dentro del 0,1 %).
- **Aviso de espera** en `templates/form_public.html` mientras el envío reintenta (misma `sid`): a los ~10 s «Hay mucha gente inscribiéndose al mismo tiempo; seguimos intentándolo, no cierres esta página»; a ~1 min «Sigue en cola; si el cupo se agota te lo diremos aquí»; `aria-live="polite"`; desaparece con la respuesta final. El texto solo cambia cuando toca reintentar, así que puede aparecer hasta una espera (~12 s) después de los 10 s / 60 s.
- **Limitación conocida y mejora diferida (post-producción): la analítica de «abandonos» sale inflada en aperturas masivas.** El `INSERT` en `form_events` espera al `FOR UPDATE` de `form_reserve_slot` y agota `FORM_EVENT_LOCK_TIMEOUT_MS` (advertencias «no se pudo registrar el evento de envío del formulario»), de modo que hay envíos sin su evento y los «abandonos» (vistas/inicios sin envío) se sobrestiman. No afecta a las inscripciones (la reserva y el `INSERT` de la persona no dependen de ese evento). Opción futura, NO implementada: una migración que use `FOR NO KEY UPDATE` en la reserva, para que la clave foránea de `form_events` no tome un bloqueo que choque con ella. `FORM_LOCK_TIMEOUT_MS` no se cambió (se prueba en una corrida aparte).

**D2.3 · Tras la campaña en staging (2ea77ff): informe, generador de cédula y cliente de la estación (sin tocar despliegue ni `GUNICORN_KEEPALIVE`; el experimento con 620 fue no concluyente y no se adopta).** Hallazgos: ~0,04 % de los escaneos de cédula reciben un 502/503/504 HTML de infraestructura de Google (no pasan por nuestras instancias), hay una petición colgada ~60 s por corrida, y el informe contaba dos veces los 5xx (las líneas espejo «[fuera de la app] …» también llevan «(contrapresión …)»: 5 respuestas «503 app» salían como 10).
- **Criterio de cédula** (`scripts/loadgen_report.py::cedula_criteria`): p95 de «POST checkin-cedula» < 500 ms sin fallos; infraestructura (502/503/504 HTML, 429 de texto plano, sin respuesta) ≤ 0,1 % de las peticiones Y todos los escaneos con resultado final; cualquier otro 5xx falla; y con la línea `LOAD_VERIFY` en el mismo archivo, `access_logs_in_event` ≥ los escaneos 200 del informe (de más = respuestas perdidas tras guardar: no es un error; de menos = se perdió un ingreso confirmado). Sin `LOAD_VERIFY` el informe lo pide.
- **Generador de cédula** (`tests/load/locustfile.py::CedulaScanner`): emula la estación real: tiempo de espera de 10 s por petición (`LOAD_CEDULA_TIMEOUT`) y UN reintento (espera `LOAD_CEDULA_RETRY_WAIT_MS`, 400 ms) ante 502/503/504, error de red o tiempo agotado, con la misma `client_id`. Los intentos que rebotan salen como «… (contrapresión 502 infra | tiempo agotado | error de red)», los reintentos como «POST checkin-cedula (reintento)» y el resultado final por escaneo como «[usuario] escaneo ok | ok tras reintento | sin resultado». El nombre de un intento «ocupado» ahora decide por el cuerpo: «503» = `busy` de la app, «… infra» = no es JSON (HTML de Google), «… app» = JSON de la app sin `busy` (falla). **Decisión a confirmar:** «tiempo agotado» y «error de red» cuentan como infraestructura (dentro del 0,1 %), porque el generador no puede saber si el cuelgue fue de Google o de la instancia; el p95 y los fallos de los demás intentos siguen juzgándose.
- **Cliente real de la estación** (`static/js/directory.js::postWithRetry`, el POST de `/api/checkin-cedula`): 10 s por intento (`AbortController`) y hasta 2 reintentos automáticos (espera 0,4 s y 0,8 s) ante 502/503/504, error de red o tiempo agotado, con aviso discreto («Conexión lenta: reintentando…», `aria-live="polite"`) que se quita al terminar; tras el último intento muestra el error de siempre. Antes eran 3 intentos sin tiempo de espera ni aviso. **Idempotencia: ya existía** (Fase 0): cada acción lleva un `client_id` (`crypto.randomUUID`) que todos los reintentos reusan; el servidor lo busca ANTES de cualquier otra regla (`_replayed_checkin`) y responde el mismo «SÍ» con `replayed: true`, también sin `force`; una carrera entre dos envíos con el mismo `client_id` la resuelve el índice único (0047) y el perdedor recibe el mismo resultado. Pruebas: `tests/test_fase0_ingress_directory.py` (incluida la respuesta perdida tras guardar, sin `force`) y `tests/js/directory_checkin_retry_check.js`. Los 2-5 ingresos de más por corrida son, por inferencia (no verificada en los registros), peticiones que el servidor guardó pero cuya respuesta se perdió o llegó tarde; el generador no enviaba `client_id`, y ahora lo envía.

**Fase 3 · Modo contingencia del quiosco (docs/13 §9), tanda 1.** Decisiones del responsable: fuera de alcance el alta de personas nuevas sin red (sin red, quien no esté en el roster local NO se admite: «No registrado: verificar manualmente»); quien está en el roster local y no consta como admitido en ESE quiosco se admite, se encola con `client_id` y marca de tiempo y el servidor lo marca para revisión al sincronizar si otro quiosco lo admitió antes (no se bloquea); umbral: chequeo de `/health` (3 s) cada 5 s, entra tras 2 fallos seguidos o 2 escaneos consecutivos que agotaron sus reintentos, sale tras 2 chequeos buenos Y una petición autenticada buena; retención del roster local: hasta que el evento finalice y, como máximo, 24 h desde el último refresco, y se borra al cerrar sesión; solo IndexedDB (si falta soporte: aviso y modo normal).
- **Commit 1 · `GET /api/events/{id}/local-roster`** (`app/routers/api.py`, sirve el servicio `web`). Por persona SOLO `h` (huella de la cédula), `n` (nombre para mostrar), `c` (categorías) y `s` (estado «No registrado» / «Registrado» / «Nuevo»); además `v` (versión = ETag, 304 si nada cambió), `generated_at`, `max_age_s` (86.400: vida máxima de la copia), `event` y `salt`. SIN fotos, encodings, teléfono ni correo. Permisos: digitador o superior con acceso al evento (el rol `cliente` no); evento finalizado → 409; límite de 12 descargas por usuario y evento cada 10 min (429). Medido con 8.000 personas (`tests/test_local_roster.py`): ~703 KB sin comprimir, ~132 KB con gzip, ~150 ms en local.
- **La huella con sal es MINIMIZACIÓN, no una protección fuerte.** La huella es SHA-256(sal + «:» + cédula sin espacios ni puntos), 64 bits. La sal es por evento (HMAC de `SECRET_KEY`, sin columna nueva) y VIAJA con el roster: quien tenga el roster puede probar cédulas por fuerza bruta (el espacio de cédulas colombianas es de ~10⁹ y una GPU lo recorre en segundos). Lo que evita es que la cédula aparezca en claro o se lea a simple vista en el dispositivo o en una copia de seguridad, nada más. Las mitigaciones reales son: (1) vida corta de la copia (máximo 24 h desde el último refresco y hasta que el evento finalice); (2) borrado al cerrar sesión y al finalizar el evento; (3) que solo la usen dispositivos de operador, con HTTPS; (4) que el endpoint exija sesión de digitador+ con acceso al evento, con límite de tasa. El QR propio de la escarapela trae la cédula, así que UNA huella cubre cédula y QR.

**Decisiones pendientes tras la corrida 7 (nada de esto está implementado):**
1. **Tope de esperas: DECIDIDO (corrida 8) — se deja el tope por conteo** (`FORM_MAX_LOCK_WAITERS=3` por proceso). El tope por tiempo estimado queda documentado como **opción de reserva**, no implementada: admisión por formulario y por proceso con `max(promedio móvil del tiempo en la zona del bloqueo, edad del envío más antiguo esperando)` frente a un objetivo (~1,5 s), con al menos 1-2 envíos siempre admitidos para no dejar ciego al estimador y un tope duro grande como red de seguridad. Riesgos: el estimador se retrasa ante una cola que crece de golpe (por eso la edad del más antiguo), cada proceso ve solo su parte, hay que llevarlo por formulario, puede oscilar y las pruebas dependen del reloj (reloj inyectable). Se retomaría si una corrida muestra 503 «busy» altos con el `db;dur` de los admitidos muy por debajo del objetivo, un tiempo de retención del bloqueo que varíe mucho durante la corrida, o un número de procesos que cambie durante la rampa (con 2 instancias mínimas son 12 esperas y la corrida 8 dio 64 % de primeros intentos con contrapresión, sin dañar el resultado final).
2. **`kick()` y la CPU de Cloud Run con `feed: realtime`.** Ver la decisión anterior: agrupar `kick()` a una llamada por segundo por proceso y hacerlo antes de responder solo si se encoló algo, o `--no-cpu-throttling` en el servicio público (se factura la CPU de todo el tiempo que la instancia esté viva). El formulario de la prueba es `manual` y no lo ejercita: hay que probarlo con un formulario `realtime`.
3. **`FORM_LOCK_TIMEOUT_MS` de 3000 a ~1500.** Se prueba en la corrida 8 (una variable por corrida); con la cola acotada casi no debería llegar al tope y 1500 solo recorta el peor caso.
4. **Función SQL única en autocommit** (reserva + INSERT en una sola llamada; el bloqueo dura solo la ejecución en el servidor): la mejora que más sube el techo de reservas por segundo; exige migración. Y **servicio aparte para `state`**: pendiente de decidir según la corrida 8.

5. **Nota de producto: quienes se quedan sin cupo tardan 40-70 s en enterarse.** En la corrida 8 los usuarios que al final reciben «cupo lleno» pasan ese tiempo reintentando en silencio. Hoy el formulario deja el botón en «Enviando…» y, en cada reintento, la misma línea fija «Estamos procesando tu inscripción, no cierres esta página…» (`templates/form_public.html`), sin decir que hay mucha gente, cuánto falta ni que el cupo puede agotarse. Propuesta (no implementada): un mensaje que cambie con el tiempo (a los ~10 s «Hay mucha gente inscribiéndose al mismo tiempo; seguimos intentándolo, no cierres esta página», y pasado ~1 min «Sigue en cola; si el cupo se agota te lo diremos aquí»), y que el rechazo por cupo se conozca antes (el `state` ya avisa «cupo lleno» a quien abre después de agotarse).

6. **Analítica de `form_events` en aperturas masivas (recomendación: `FOR NO KEY UPDATE`, sin implementar).** En el pico salen decenas de avisos por segundo «no se pudo registrar el evento de envío del formulario N»: el INSERT en `form_events` (FK a `web_forms`) pide `FOR KEY SHARE` sobre la fila que la reserva tiene con `FOR UPDATE` (`0049_form_atomic_reserve.py`) y vence a los 2 s, así que casi toda la analítica de «submit» se pierde y «abandonos» (`forms.py`: `starts - sent`) queda inflado. El `beacon` (`view` al abrir y `start` al escribir, ~2 por usuario, sin `lock_timeout`) tiene el mismo problema y no lo ejercita el generador: en producción cada uno retiene un turno de Cloud Run, un hilo y una conexión mientras espera la cola del bloqueo. Opciones: (a) `FOR NO KEY UPDATE` en `form_reserve_slot` (recomendada): sigue siendo exclusivo entre reservas pero no choca con `FOR KEY SHARE`; el único sitio que crea `FormSubmission` es `_reserve_and_store` (después del bloqueo) y no hay otro `FOR UPDATE` sobre `web_forms`, así que cupo y duplicados no dependen de que las FK esperen; costo: migración `CREATE OR REPLACE FUNCTION` (instantánea, con `downgrade`); pruebas: una conexión con la reserva abierta y otra que inserta un `FormEvent` (debe terminar al instante), una tercera reserva que debe bloquearse, y las pruebas de último cupo, misma cédula y cupo por variable repetidas. (b) Quitar la FK (migración, bloqueo breve de ambas tablas, pierde integridad) o encolar en lote (más código, buffer que se pierde al apagar, el INSERT del lote sigue haciendo fila). (c) Aceptar la pérdida y documentar que «abandonos» no es fiable en aperturas masivas (parche). Mientras tanto: dar al `beacon` su propio `lock_timeout` corto y que pierda la marca, y que el generador mande beacons.
7. **Reciclaje por `max_requests` en `web` y `biometria` (sin implementar).** Cada proceso se recicla entre 1500 y 1800 peticiones (1500 + jitter 0-300), contando TODAS (también sondas). **web** (2 procesos por instancia; 2 instancias mínimas en un evento = 4 procesos): a ~57 escaneos/s en total son ~14 peticiones/s por proceso, o sea un reciclaje cada ~2 min por proceso y todos dentro de una ventana de ±10 s (sincronizados, como en la corrida 9); con ~3 peticiones/s en total (5-6 estaciones) son ~0,75/s por proceso: cada ~37 min y desfasados. Un evento de 8.000 personas son ~30.000 peticiones: ~4-5 reciclajes por proceso. Riesgo de web sin reciclar: sus informes con pandas/openpyxl y el directorio de miles de personas pueden fragmentar memoria (no medido). Recomendación: mantener el reciclaje pero con un límite alto y jitter grande (p. ej. 20.000 con jitter de 10.000, lo que exige una variable `GUNICORN_MAX_REQUESTS_JITTER`), de modo que no coincida con un pico. **biometria** (1 proceso web por instancia, 2 procesos dlib hijos, concurrencia 2): un reciclaje deja la instancia SIN servicio mientras arranca (segundos: proceso, modelo dlib, matriz del evento) y hace fallar los reconocimientos de ese momento; con ~1 petición/s por instancia son ~25-45 min, y a ~4/s ~7 min. La fuga de memoria que motivó el reciclaje vive en los hijos con dlib; lo más seguro es reciclar SOLO esos hijos (`ProcessPoolExecutor(max_tasks_per_child=N)`, disponible en la imagen con Python 3.14 y compatible con `spawn`), dejar `GUNICORN_MAX_REQUESTS=0` en biometria y medir primero la memoria de la instancia en una prueba larga; mientras no haya esa medición, un límite alto con jitter grande. En ambos, evitar reciclajes sincronizados de toda la flota.

**Parámetro del generador: proporción de los que envían.** `LOAD_SUBMIT_RATIO` (0 a 1; por defecto 0,5 = ~5.000 envíos con 10.000 aperturas; 1 = 10.000 envíos). Se pasa desde la terminal: `LOAD_SUBMIT_RATIO=1 bash deploy/loadtest/run_phase4.sh run` (`run_phase4.sh` lo valida —un valor inválido no lanza nada—, lo escribe en el archivo de variables de cada Job y `run_task.py` lo vuelve a validar; `scripts/load_cfg.py::submit_ratio`). Con 1, `cupo confirmado = min(capacidad, usuarios únicos que envían)` = la capacidad; el resto sale «cupo lleno», y hay más contrapresión al inicio (el doble de envíos en la misma ventana).
**Arranque de una instancia del servicio público (análisis en local, imagen real, 1 CPU; nada implementado).** `/health` responde a los ~3,4 s con 2 procesos; con `--preload` o con 1 solo proceso, a ~1,9 s. Importaciones: 1,6 s de CPU en total, sin dlib ni face_recognition (solo los procesos hijos del modelo); sobran para el público pandas (244 ms), numpy (126 ms) y openpyxl (89 ms). Cada proceso importa la app por su cuenta (sin `--preload`), así que en 1 vCPU se pelean la CPU. La sonda de arranque de `deploy.sh` usa `/ready` con `periodSeconds=5` (la instancia se declara lista en un múltiplo de 5 s: 0-5 s extra), y `/ready` abre la conexión a Neon y crea el cliente de GCS. El resto de los 10-20 s de la gráfica de Cloud Run es plataforma (descarga de la imagen de 722 MB, sandbox gen2), que no se mide en local. Recortes seguros propuestos, por orden: sonda de arranque a 1 s (subiendo `failureThreshold` para conservar los ~180 s), `--preload` solo en el público con `engine.dispose()` en `post_fork`, importaciones perezosas de pandas/openpyxl/numpy, evaluar 1 proceso, y una imagen sin dlib/tesseract/pg client para el público. `GUNICORN_MAX_REQUESTS`: con el valor por defecto (1500) cada reinicio de proceso cuesta ~1,8 s de CPU y vacía la caché, y a alta tasa bajó la página de 366 a 160 req/s en local; en el servicio público quedó en 0 (ver la corrida 9).

- **Simulacros** (mientras corre la cédula de 30 min; ambos con el generador ya en marcha):
  1. *Matar una instancia*: `gcloud run services update golden-web-staging --region "$REGION" --update-env-vars CHAOS_ENABLED=1` (una vez), y en el minuto ~10:
     `curl -s -X POST -H "X-Ops-Token: $OPS_TOKEN" https://golden-web-staging-<número>.<región>.run.app/api/ops/simulate-crash` (repetirlo 2-3 veces para tumbar varias). Solo funciona con
     `DEPLOY_ENV=staging` + `CHAOS_ENABLED=1` + credencial (producción responde 404). Quitar la variable al terminar: `--remove-env-vars CHAOS_ENABLED`. Aprobado si `verify` muestra
     `access_logs_in_event` ≥ las respuestas 200 de «POST checkin-cedula» (ningún ingreso confirmado se pierde; puede haber 5xx durante el reemplazo).
  2. *Reiniciar el cómputo de Neon*: en el minuto ~5 de una corrida de formularios (`LOAD_THINK_MAX=120` alarga el pico) con la llave de Neon en una variable de entorno (no en el chat):
     `curl -s -X POST "https://console.neon.tech/api/v2/projects/$NEON_PROJECT_ID/endpoints/$NEON_ENDPOINT_ID/restart" -H "Authorization: Bearer $NEON_API_KEY"` (también sirve el botón
     *Restart compute* de la consola). Aprobado si `verify` da `oversold=0`, `duplicate_persons=0`, `duplicate_sids=0` y el número de confirmadas = respuestas 200 del primer envío («POST envio»).
  El simulacro 3 (red del kiosco cortada) queda para la Fase 3 (modo contingencia).

**D2.4 Runbook del día del cambio (semana 3; producción; lo ejecuta Juan David, ningún paso lo corre Claude Code).** La VM `golden-biometrics-prod` **se apaga, NO se borra**, y es la vuelta atrás.
Requisitos: Fase 4 aprobada en staging, región decidida, `bootstrap.sh production` corrido (rama `production` de Neon con ventana de historia de 1 día, `SECRET_KEY` y `FACE_ENCRYPTION_KEY`
ACTUALES de la VM en Secret Manager), autorización explícita de Juan David para cada acción de producción (merge a `main`, activar el despliegue de producción de `cloudrun.yml` hoy con `if: false`).
1. **T-2 días:** bajar el TTL del DNS de `app.golden-eventos.com` en Cloudflare a 300 s; avisar la ventana (sin eventos ni aperturas de formularios); confirmar `deploy-allowed` en la VM.
2. **Ventana — congelar:** `curl -s -H "X-Ops-Token: …" https://app.golden-eventos.com/api/ops/deploy-allowed` sin eventos; detener el cron de la VM (respaldos, purga) y activar solo lectura de la VM (parar el servicio: `sudo systemctl stop facial-recognition`).
3. **Respaldo final y datos:** en la VM `scripts/backup_db.sh` (guardar el `.sql.gz`), y después, desde la VM (tiene `pg_dump`/`psql` 18):
   ```bash
   python scripts/migrate_db_to_neon.py --source-url "$VM_DATABASE_URL" --target-owner-secret golden-db-owner-url-production --migrate      # cuenta filas antes/después; hasta 0051; una diferencia = detener
   python scripts/migrate_files_to_gcs.py --source ~/Facial-Recognition/data --bucket "$APP_BUCKET" --prefix app --biometric-prefix biometric      # APP_BUCKET: `source deploy/gcp/config.sh production`; bucket NUEVO en us-east4
   python scripts/migrate_files_to_gcs.py --source ~/Facial-Recognition/data --bucket "$APP_BUCKET" --prefix app --biometric-prefix biometric --verify-only
   ```
   (con `golden_app` ya creado en la rama `production`; los archivos admiten una primera pasada días antes y otra en la ventana). Las fotos biométricas viejas de la VM pasan al bucket con su reloj de
   retención nuevo: `face_captured_at` queda con la constancia de autorización o con la fecha de la migración `0051` (ver B2).
   **3b. Copiar el contenido de los BUCKETS de la VM a los buckets NUEVOS de producción** (`golden-datos-…` → `<proyecto>-golden-app-us-east4`, `golden-backups-…` → `<proyecto>-golden-backups-us-east4`; desde Cloud Shell, no
   necesita la VM; solo lee los viejos y solo escribe en los nuevos; se puede repetir):
   ```bash
   gcloud config set run/region us-east4                       # o export REGION=us-east4
   bash deploy/gcp/copy_vm_buckets.sh --dry-run                # qué copiaría
   bash deploy/gcp/copy_vm_buckets.sh                          # copia y comprueba
   bash deploy/gcp/copy_vm_buckets.sh --verify                 # solo comprueba
   ```
   Mapa: `data/<cliente>/known_people/…` → `app/biometric/<cliente>/known_people/…` (fotos biométricas con su prefijo y su ciclo de vida de 1 día); el resto de `data/<cliente>/…` → `app/<cliente>/…`; los volcados de la VM
   `db/…` → `db/vm/…` del bucket de respaldos nuevo (se borran a los 30 días como todo `db/`). NO se copian `config/.env` (secretos: van en Secret Manager), `uploads/` ni temporales. **Comprobación de conteos:** el script imprime
   `OK fotos biométricas: N = N`, `OK archivos en total: M = M` y `OK volcados de la VM: K = K`, y un `rsync` en seco que no debe listar nada por copiar (rsync compara tamaño y suma de verificación); sale con error si algo difiere.
   Es equivalente (y con MD5 desde el disco) a los `migrate_files_to_gcs.py` de arriba: úsalo para adelantar trabajo días antes o si la VM ya no está.
4. **Desplegar:** activar el workflow de producción (o `deploy/gcp/deploy.sh production`); comprobar `…/health` y `…/ready` de cada servicio y `Estado del sistema`.
   **4b. Precalentar el servicio público antes de abrir un formulario grande — RECOMENDADO POR LA CORRIDA 8.** Desde 2 instancias el arranque de las nuevas (10-20 s) cae justo en el pico (corrida 8: `state` p99 7,1 s y un 503 de Google); con 10 ya calientes (corrida 7) el criterio se cumple. Unos minutos antes de abrir (5-10 min) y al terminar volver a 2:
   ```bash
   gcloud run services update golden-publico --region "$REGION" --min-instances 10        # antes de abrir (en staging: golden-publico-staging)
   gcloud run services update golden-publico --region "$REGION" --min-instances 2         # al terminar
   ```
   **Ojo con `app/warmup.py`:** `apply()` compara el mínimo actual con el del plan y lo corrige; el Job horario (minuto 5) o un `kick()` (abrir un formulario, pasar un evento a «en proceso») dejarían el mínimo otra vez en `WARM_PUBLICO_MIN` (2, o 0 si no hay una apertura registrada en la última hora). Para que el 10 sobreviva a la ventana: subir `WARM_PUBLICO_MIN` a 10 en el Job de operaciones durante el evento (y devolverlo a 2 después), o hacer ambos cambios juntos. Un despliegue de CI también reemplaza las variables y el mínimo (`--env-vars-file`). Fórmula propuesta para automatizarlo (no implementada): `n = ceil(esperados / ventana_s × factor_pico / 60 × seguridad)` acotado entre `WARM_PUBLICO_MIN` y `WARM_PUBLICO_MAX` (6 por defecto, nunca por encima del máximo del servicio), con `esperados` = cupo del formulario (o un valor por defecto), ventana 120 s, factor de pico 2, seguridad 1,5 y 60 usuarios nuevos/s como capacidad cómoda de una instancia (medido en local, directo a `run.app`): con 10.000 en 2 min salen ~5; la corrida 7 (10 calientes) y la 8 (2 sin precalentar) indican que 10 es un valor seguro para 10.000 usuarios. Recortes de arranque adicionales en «Arranque de una instancia».
5. **Dominio:** conectar `app.golden-eventos.com` al sitio de Firebase Hosting (consola de Firebase → Hosting → Agregar dominio) y en Cloudflare cambiar el registro a los que indique Firebase con **proxy
   apagado (solo DNS)**; esperar el certificado. Ahora sí `TRUST_CF_CONNECTING_IP=0` y `XFF_STRIP_GOOGLE=1` (D2.2, opción D).
   **5b. Repetir la prueba de IP por el DOMINIO PROPIO** (DNS ya cambiado, Cloudflare solo DNS, sin proxy): `curl -s -H "X-Ops-Token: $OPS_TOKEN" https://app.golden-eventos.com/api/ops/client-ip` (y otra vez con `-H "X-Forwarded-For: 1.2.3.4"`). Debe verse
   `x_forwarded_for` = `[tu IP real, una IP de Google]` (`hops: 2`, `google_infra: [false, true]`), `chosen_ip` = tu IP real, y la falsa DESCARTADA. **Si aparece cualquier otra entrada** (una tercera, una IP de Cloudflare 104.x/172.64.x/
   162.158.x, etc.) NO sigas: significa que el proxy de Cloudflare quedó encendido o hay un salto que no se esperaba; corrige el DNS (nube gris) y repite.
6. **Encender lo programado:** reanudar `golden-ops-hourly` (`gcloud scheduler jobs resume golden-ops-hourly --location "$REGION"`) y correr UNA vez `backup-daily` (comando de D.1) y `check-backups`.
7. **Monitores → `/health`:** el chequeo de Google «GoldenWeb readyz» y el monitor de UptimeRobot pasan a `https://app.golden-eventos.com/health` (NO `/healthz`: en Cloud Run da 404 de Google; y no `/ready`:
   toca la base y Neon no se apagaría). `bootstrap.sh production` ya crea `golden-health-production`; borrar el chequeo viejo.
8. **Verificación:** iniciar sesión; kiosco por cédula y por rostro (con el flujo de verificación); un formulario público de prueba y su correo; `__session` con `Secure`; pago de prueba de Wompi (mismo
   webhook: la URL no cambia); `/sistema` en verde (respaldo «hace 0 h»); `gcloud run jobs execute golden-ops --region "$REGION" --wait` sin errores.
9. **Apagar la VM (no borrarla):** `gcloud compute instances stop golden-biometrics-prod --zone us-central1-a`; conservar disco y snapshots al menos 30 días.
10. **Vuelta atrás:** hasta el primer dato real nuevo en Neon: en Cloudflare devolver el DNS a la IP de la VM (con proxy), `gcloud compute instances start golden-biometrics-prod --zone us-central1-a`,
    `sudo systemctl start facial-recognition`, y volver a poner los monitores en `/healthz` de la VM; detener `golden-ops-hourly` (`pause`). **Pasado ese punto** lo ingresado en Neon debe volver a la VM antes de
    reabrirla: `pg_dump` de Neon con el dueño (`--no-owner --no-privileges`) y restaurarlo en la VM con el procedimiento de `docs/recuperacion_desastre.md` (se pierde solo lo escrito durante la restauración).
11. **Limpieza (semana +1):** borrar `gs://<bucket-datos>/data/` y `config/.env` de la VM y sus volcados viejos (R4), y las copias con historia de Neon >1 día.
Tabla de costos por componente: pendiente (no se pidió en esta sesión).

### Sesión 4 — Mover a otra región: staging de us-east1 a us-east4 y producción directo en us-east4 (decisión de Juan David, 2026-09-29)
**Decisión:** `us-east4` (Virginia del Norte, junto a Neon en AWS us-east-1). `us-east1` y `us-east4` son ambas Nivel 1 (mismo precio de Cloud Run, verificado en la lista oficial de ubicaciones; la nota
contraria de docs/13 §15 y del handoff quedó desactualizada). **Todo lo regional vive en la MISMA región** (servicios, Jobs, Artifact Registry, Cloud Tasks, Scheduler y bucket) para no pagar tráfico entre regiones.
La región ya no está escrita en ningún script: `deploy/gcp/config.sh` la toma de `REGION` o de `gcloud config set run/region <región>` y falla si falta; el workflow usa la variable `GCP_REGION` del Environment
de GitHub (sin valor por defecto: sin la variable no despliega). `deploy/loadtest/run_phase4.sh` lee todo de `config.sh`.

**Qué es regional y qué se hace con cada cosa** (nada se «mueve»: se crea en la región nueva y se borra la vieja):
| Recurso | ¿Regional? | En la región nueva | Lo de la región vieja |
|---|---|---|---|
| Servicios de Cloud Run (`web`, `publico`, `biometria`) | sí | se RECREAN: `bootstrap.sh` (imagen de relleno + permisos por recurso) y luego el despliegue | se borran |
| Cloud Run Jobs (`migrate`, `bulk`, `ops`) | sí | se RECREAN igual | se borran |
| Artifact Registry (`golden-staging` / `golden`) | sí | repositorio nuevo (bootstrap); las imágenes NO se copian: el workflow reconstruye (la caché de capas es de GitHub) | se borra el repositorio (las imágenes viejas cobran almacenamiento) |
| Cloud Tasks (`golden-jobs*`) | sí | cola nueva (bootstrap); `CLOUD_TASKS_URL` y la cola salen de `config.sh` | se borra cuando esté vacía; lo pendiente NO se copia: la tabla `jobs` de la base es la fuente de verdad y el paso `sweep` del Job de ops lo retoma |
| Cloud Scheduler (`golden-ops-hourly`, solo producción) | sí | se recrea EN PAUSA (bootstrap) | se borra |
| Bucket de archivos y respaldos | sí, y la ubicación NO se puede cambiar | bucket NUEVO `<proyecto>-golden-staging-<región>` (staging) o `<proyecto>-golden-app-<región>` y `<proyecto>-golden-backups-<región>` (producción); los nombres son únicos en todo Google Cloud, por eso llevan la región | staging: se COPIA el contenido y se borra el viejo. Producción: no hay nada que copiar (los archivos de la VM se suben directo al bucket nuevo); los buckets de la VM (`data/`, `config/`, volcados) NO se tocan hasta apagarla |
| Reglas de Firebase Hosting (`rewrites` con `serviceId` + `region`) | llevan la región | `make_config.py` las regenera con la región nueva y el workflow publica el sitio: ES el cambio de tráfico del dominio público | no hay que borrar nada (el sitio y el dominio son globales) |
| Chequeo de disponibilidad y su alerta (Monitoring) | el host lleva la región | `bootstrap.sh` detecta el host viejo y los recrea | (los reemplaza) |
| Secret Manager, cuentas de servicio, Workload Identity, presupuesto, canal de correo, Neon, DNS de Cloudflare | no | sin cambios | — |
| Variables con región que calcula `deploy.sh`: `CLOUD_TASKS_URL`, cola, `BULK_JOB_NAME`, `OPS_JOB_NAME`, `WARM_SERVICE_*`, `GCS_BUCKET`/`BACKUP_BUCKET`, `PUBLIC_BASE_URL` (sin Firebase) | sí | se actualizan solas al redesplegar | — |

**Procedimiento en orden — staging** (sin corte: la región nueva se prepara y verifica antes de cambiar el tráfico; lo corre Juan David en Cloud Shell desde el clon de `migra/fase1-2`, con el proyecto de staging en `gcloud config`):
```bash
git pull && export OLD_REGION=us-east1 REGION=us-east4 && gcloud config set run/region "$REGION"
# 1) inventario (solo lee): qué hay en la región vieja y qué falta en la nueva
bash deploy/gcp/move_region.sh staging plan
# 2) crea lo regional NUEVO: repositorio de imágenes, bucket, cola, servicios y Jobs con imagen de relleno, permisos, chequeo de disponibilidad
FIREBASE_DEPLOY=1 bash deploy/gcp/bootstrap.sh staging          # idempotente: no vuelve a pedir los secretos que ya existen; imprime las variables de GitHub
# 3) GitHub → Settings → Environments → staging → Variables: GCP_REGION = us-east4 (el resto no cambia)
# 4) copia el contenido del bucket viejo al nuevo (primero en seco)
bash deploy/gcp/move_region.sh staging copy --dry-run && bash deploy/gcp/move_region.sh staging copy
# 5) despliega: relanza el workflow «Cloud Run» (o un push a migra/fase1-2). Construye la imagen en el repositorio NUEVO, corre las migraciones (mismo Neon), despliega los 3 servicios y los
#    Jobs en us-east4 y publica Firebase Hosting con las reglas nuevas: desde aquí el sitio público (web.app) responde desde us-east4
# 6) respaldos en la región nueva (el bucket nuevo empieza vacío y check-backups lo exige)
gcloud run jobs execute "golden-ops-staging" --region "$REGION" --args="-m,app.ops_runner,backup" --wait
gcloud run jobs execute "golden-ops-staging" --region "$REGION" --args="-m,app.ops_runner,backup-daily" --wait
# 7) verifica la región nueva (servicios, Jobs, cola, /health, /ready, sitio público, variables hacia us-east4) Y el bucket nuevo: está en la región, CORS con PUT desde EXACTAMENTE la lista de config.sh, versiones,
#    ciclo de vida (uploads/ a 1 día, respaldos a 30) y el permiso de firma de URLs de la cuenta de la app
bash deploy/gcp/move_region.sh staging verify
# 8) ~1 día de observación (Estado del sistema en verde; la cola vieja se vacía sola); después limpia lo VIEJO (pide escribir la región)
bash deploy/gcp/move_region.sh staging cleanup
```
Después: actualizar el texto de la URL de Cloud Run de staging donde se haya anotado (`golden-web-staging-<número>.us-east4.run.app`), y repetir las mediciones de D2.1 en la región nueva como referencia. La contraseña de
`revisor.staging`/datos sintéticos siguen en la base (Neon no se mueve). Mientras conviven las dos regiones el costo extra es despreciable (sin instancias mínimas no hay cobro inactivo; un poco de almacenamiento).

**Orígenes de CORS del bucket (una sola definición).** `cors_origins()` en `deploy/gcp/config.sh` los calcula desde el proyecto y la región; `bootstrap.sh` los aplica sobre la plantilla `deploy/gcs-app-cors.json` (solo cambia su `origin`) y `move_region.sh verify` exige EXACTAMENTE esa lista (falta uno o sobra uno = FALTA). **Staging:** la URL pública, `https://<sitio>.web.app`, `https://<sitio>.firebaseapp.com` y la URL `run.app` del servicio web (para probar directo). **Producción:** el dominio propio y los dos sitios de Firebase; `run.app` NUNCA (se filtra aunque `PUBLIC_BASE_URL` lo trajera). Un bucket que quedó con orígenes distintos (p. ej. creado antes de este cambio) se corrige volviendo a correr `bootstrap.sh <entorno>`.

**Idempotencia de `bootstrap.sh` (comprobado):** en una segunda corrida NO rota nada: `put_secret` deja los secretos que ya tienen valor, y la cadena de `golden_app` (`scripts/neon_app_role.py --rotate`) solo se genera si el secreto `database-url` no tiene
valor; rotar exige pedirlo (`ROTATE="database-url"`). Los secretos son globales del proyecto: mover de región no los toca.

**Producción directamente en us-east4** (no hay nada que mover: su bootstrap todavía no se corrió): `gcloud config set run/region us-east4` (o `REGION=us-east4` en cada comando) y `bash deploy/gcp/bootstrap.sh production` /
GitHub Environment `production` con `GCP_REGION=us-east4`. Crea los buckets NUEVOS `<proyecto>-golden-app-us-east4` (archivos bajo `app/`) y `<proyecto>-golden-backups-us-east4` (`bootstrap.sh` avisa si un bucket no está en la región del
entorno). Ya NO se reutilizan los buckets de la VM: están en otra región y cada foto o respaldo cruzaría regiones. Los comandos de subida del runbook usan el bucket que imprime `config.sh`
(`source deploy/gcp/config.sh production; echo $APP_BUCKET`).

**Limpiar lo viejo para que no cueste** (lo hace `cleanup`; se niega si la cola vieja tiene tareas, salvo `FORCE=1`): servicios y Jobs, cola, tarea de Scheduler, repositorio de Artifact Registry y el bucket viejo de staging con
todas sus versiones (dos confirmaciones escritas). No borra nada de producción sin escribir «produccion», ni los buckets de la VM. Al día siguiente revisa Facturación → Informes agrupado por SKU y por ubicación: no debe
quedar consumo en la región vieja. Lo que sí queda a propósito: secretos, cuentas de servicio, Workload Identity y Neon (globales).

### Sesión 3 — estado (2026-09-29): scripts y pasos listos (D.2); faltan las corridas en la nube de Juan David
- [x] 1. Latencia app→Neon y región: decidida `us-east4` (docs/13 §15); falta ejecutar el traslado de staging (sección «Mover a otra región») y repetir la medición allí
- [~] 2. `XFF_CLIENT_INDEX`: diagnóstico `GET /api/ops/client-ip` y procedimiento en «D2.2»; falta el tráfico real detrás de Firebase
- [~] 3. Prueba de carga distribuida y simulacros 1 y 2: `deploy/loadtest/` + `scripts/seed_load_staging.py` + `scripts/loadgen_report.py` y pasos en «D2.3»; falta correrlos
- [x] 4. Runbook del día del cambio (VM apagada, monitores a `/health`, `golden-ops-hourly`, vuelta atrás): «D2.4» (tabla de costos por componente: pendiente)
- [ ] 5. Revisión final de pruebas y ruff tras las corridas; luego Fase 3 (modo contingencia del kiosco) en otra rama

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
