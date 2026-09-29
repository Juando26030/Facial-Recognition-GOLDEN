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

**D2.1 Latencia app → Neon: por qué `/ready` da 43-46 ms (análisis del código; las cifras de RTT se confirman con el script).**
- `/ready` no mide UNA consulta: `ops._db_probe` cronometra `db.execute("SELECT 1")` **incluyendo el préstamo de la conexión del pool**, y el pool tiene `pool_pre_ping=True`, que
  antes de entregar la conexión hace OTRO `SELECT 1`. Son **2 idas y vueltas (RTT)**: 44 ms ≈ 2 × ~22 ms. Una consulta suelta cuesta ~22 ms desde `us-east1`, no 44.
- No es conexión nueva (TCP + TLS + SCRAM, ~0,5 s desde Bogotá; solo la paga la primera petición de una instancia o una conexión que murió), ni «Neon despertando» (esa primera
  consulta tardaría cientos de ms o segundos, y staging tiene la base despierta por el respaldo horario), ni varias consultas: `/ready` hace una sola. `storage.ping()` va aparte y no
  entra en `latency_ms`.
- **Por qué importa para los formularios:** con la fila del formulario bloqueada corren `form_reserve_slot()` (1 RTT) + `INSERT` (1 RTT) + `COMMIT` (1 RTT) = **3 RTT con el bloqueo tomado**.
  Con RTT ≈ 22 ms el bloqueo dura ~66 ms → como mucho **~15 envíos por segundo por formulario** (los demás esperan turno). La meta de la Fase 4 son 5.000 envíos en 120 s = **~42/s**:
  desde `us-east1` NO se alcanzaría con un solo formulario (el `p95 < 2 s` se rompería por la cola del bloqueo). Con RTT ≈ 2-3 ms (`us-east4`, Ashburn, mismo entorno de red que
  `us-east-1`) el bloqueo dura ~9 ms → ~110/s, con margen. Es hipótesis derivada de los 44 ms y de la geografía: **la confirma la medición de abajo**.
- **Decisión (Juan David, 2026-09-29): `us-east4`; procedimiento exacto en «Mover a otra región» (arriba).** (Recomendación original: `REGION=us-east4 bash deploy/gcp/bootstrap.sh staging` y redesplegar; la región de Neon no se toca.) Confirmar antes: (1) la medición
  desde ambas regiones; (2) el precio en cloud.google.com/run/pricing (el handoff anotó que `us-east4` costaba más; no pude verificarlo desde aquí); (3) que Firebase Hosting siga
  soportándola (sí figura en la documentación). Si por costo se quedara `us-east1`, la alternativa de código es que el cupo y el INSERT vayan en UNA sola función SQL en autocommit
  (bloqueo de 1 RTT): más cambio y sin probar; no se hizo.
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

**D2.2 IP real del cliente detrás de Firebase Hosting.** Hoy `TRUST_CF_CONNECTING_IP=0` (Cloudflare solo es DNS: esa cabecera se puede inventar) y `XFF_CLIENT_INDEX=0` (la PRIMERA entrada de
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

**D2.3 Prueba de carga distribuida contra staging** (`deploy/loadtest/`, `scripts/seed_load_staging.py`, `scripts/loadgen_report.py`; generadores = Cloud Run Jobs con Locust; solo staging: el
generador se niega a apuntar a un host sin «staging» y al dominio de producción). Criterios (docs/13 §11): formularios 10.000 aperturas en 60 s + 5.000 envíos en 120 s con 0 errores 5xx, p95 del
envío < 2 s, cero sobrecupos y cero duplicados; cédula 200 estaciones × 30 min (~57/s) p95 < 500 ms; facial referencia 30/s con p95 < 2 s; aislamiento: la latencia de la cédula durante el pico
de formularios sube ≤ 20 %.
  - Datos: 5.000 personas sintéticas y encodings aleatorios en el evento `LOAD-STG` (tenant `carga-staging`), un formulario con **cupo 4.000 < 5.000 envíos** a propósito (el 409 «cupo
    completo» es correcto y se cuenta; sobrecupo = más de 4.000 confirmadas). La clave de `carga_dig` se deriva de `OPS_TOKEN` (nunca se imprime). Sin fotos reales en la nube: el escenario facial usa la
    foto de dominio público (astronauta) o, sin rostro, mide solo la detección.
  - Pasos (en Cloud Shell, desde el clon de `migra/fase1-2`): `bash deploy/loadtest/run_phase4.sh build` → `seed` → (leer `LOAD_SEED`: `event_id`) → `WEB_URL=https://golden-staging-<número>.web.app LOAD_EVENT_ID=<id> run` →
    cuando terminen los Jobs, `report <exec_forms> <exec_cedula> <exec_face>` → `verify` → `cleanup`. El script imprime los comandos exactos. Tope de costo: 20 tareas × 1 vCPU × ≤ 34 min (cédula) +
    3 min (formularios) + 9 min (facial) ≈ 8-9 vCPU-horas ≈ **US$1-3**, sin reintentos y con `task-timeout`; los Jobs se borran en `cleanup`. Neon: el pico sube el cómputo (autoescala): fijar
    el máximo en 2-4 CU para tener tope (`Settings → Compute` en la consola) y comprobarlo antes.
  - Para que el facial no se cuelgue por instancias: el precalentamiento sube `biometria` a mínimo 1 solo si hay un evento en proceso con rostro (sí, `LOAD-STG`); para 30/s hacen falta ~6 instancias
    (≈ 5 escaneos/s por proceso con 2 jitters): subir `--max-instances` y `--min-instances` temporalmente y bajarlos después.
  - Criterios que salen de la base: `verify` imprime `oversold`, `duplicate_persons`, `duplicate_sids` y `access_logs_in_event` (deben ser 0, 0, 0 y ≥ los 200 de «POST checkin-cedula»).
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
4. **Desplegar:** activar el workflow de producción (o `deploy/gcp/deploy.sh production`); comprobar `…/health` y `…/ready` de cada servicio y `Estado del sistema`.
5. **Dominio:** conectar `app.golden-eventos.com` al sitio de Firebase Hosting (consola de Firebase → Hosting → Agregar dominio) y en Cloudflare cambiar el registro a los que indique Firebase con **proxy
   apagado (solo DNS)**; esperar el certificado. Ahora sí `TRUST_CF_CONNECTING_IP=0` y el `XFF_CLIENT_INDEX` verificado en D2.2.
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
# 7) verifica la región nueva (servicios, Jobs, cola, bucket, /health, /ready, sitio público y que las variables apunten a us-east4)
bash deploy/gcp/move_region.sh staging verify
# 8) ~1 día de observación (Estado del sistema en verde; la cola vieja se vacía sola); después limpia lo VIEJO (pide escribir la región)
bash deploy/gcp/move_region.sh staging cleanup
```
Después: actualizar el texto de la URL de Cloud Run de staging donde se haya anotado (`golden-web-staging-<número>.us-east4.run.app`), y repetir las mediciones de D2.1 en la región nueva como referencia. La contraseña de
`revisor.staging`/datos sintéticos siguen en la base (Neon no se mueve). Mientras conviven las dos regiones el costo extra es despreciable (sin instancias mínimas no hay cobro inactivo; un poco de almacenamiento).

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
