# Migración a Cloud Run + Neon (Fases 1-2)

Rama `migra/fase1-2`. Plan y decisiones de fondo: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` (§4-8, §11, §14-16).
Este archivo se completa en la sesión 3 (runbook del día del cambio + costos); por ahora lleva la lista de progreso.

## Progreso (se actualiza en cada commit)

### Sesión 1 — la app queda lista para Cloud Run + Neon
- [x] 1. Cupo atómico: `form_reserve_slot()` (migración 0049) + wrapper en `formsvc` + `_submit` + pruebas de concurrencia
- [x] 2. `GcsStorage` en `app/storage.py`
- [x] 3. Backend Cloud Tasks en `app/jobs.py` (Postgres sigue como alternativa)
- [x] 4. Directorio paginado e incremental en `static/js/directory.js`
- [x] 5. Dockerfile multi-etapa + 3 puntos de entrada — imagen construida (Python 3.14, dlib compilado en la etapa de ruedas), los tres servicios arriba con `deploy/docker-compose.yml` contra Neon staging (`/readyz` 200 en los tres; `publico`/`web` sin dlib, ~275 MiB cada uno; `biometria` con el modelo, ~300 MiB) y prueba del emulador de Cloud Storage (`fsouza/fake-gcs-server`) en verde. Arreglado de paso: `STORAGE_BACKEND=` vacío (como lo deja la plantilla) tumbaba `/readyz`; ahora vacío = local
- [x] 6. `.env.staging` lleno por Juan David (incluida una `FACE_ENCRYPTION_KEY` propia de staging, válida y distinta de la local). Migraciones corridas en la rama staging de Neon (vacía, Postgres 18, `us-east-1`) por la conexión directa: queda en `0049_form_atomic_reserve (head)`. Contenedor probado contra ella: login, Directorio con 3.000 personas sintéticas (`scripts/seed_staging_demo.py`: 3 páginas de 1.000 y el incremental cada 15 s actualiza los contadores sin recargar) y subida directa de un documento de 20 MB. **Latencia de referencia desde el PC de desarrollo (Bogotá) a Neon us-east-1:** `SELECT 1` mediana 81 ms (p95 85, mínimo 79), igual por el pooler que directa; abrir conexión ~500 ms (TLS + channel binding), por eso el pool reutiliza conexiones; `/readyz` del servicio web ~0,33 s en caliente (primera ~1,4 s). Esta medición NO sirve para elegir región (sale desde Colombia): la región se decide en la sesión 3 con la medición desde Cloud Run; el bootstrap queda con `us-east1` por defecto y `us-east4` como alternativa. Nota: las cadenas de `.env.staging` usan el rol dueño (`golden_db_owner`); para mínimo privilegio, crear un rol de app para la app y dejar el dueño solo a las migraciones

### Sesión 2 — en curso
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
- [ ] 2. `deploy/gcp/bootstrap.sh` completo e idempotente (con costos al inicio)
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

### Sesión 3 — pendiente
Prueba de carga distribuida, medición de latencia, este documento completo (runbook + costos), CLAUDE.md, revisión final.

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
