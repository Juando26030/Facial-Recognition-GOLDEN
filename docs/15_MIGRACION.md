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
- [x] 6. `.env.staging` lleno por Juan David (incluida una `FACE_ENCRYPTION_KEY` propia de staging, válida y distinta de la local). Migraciones corridas en la rama staging de Neon (vacía, Postgres 18, `us-east-1`) por la conexión directa: queda en `0049_form_atomic_reserve (head)`. Contenedor probado contra ella: login, Directorio con 3.000 personas sintéticas (`scripts/seed_staging_demo.py`: 3 páginas de 1.000 y el incremental cada 15 s actualiza los contadores sin recargar) y subida directa de un documento de 20 MB. **Latencia de referencia desde el PC de desarrollo (Bogotá) a Neon us-east-1:** `SELECT 1` mediana 81 ms (p95 85, mínimo 79), igual por el pooler que directa; abrir conexión ~500 ms (TLS + channel binding), por eso el pool reutiliza conexiones; `/readyz` del servicio web ~0,33 s en caliente (primera ~1,4 s). La medición real será desde Cloud Run: conviene `us-east4` (Virginia del Norte, junto a AWS us-east-1). Nota: las cadenas de `.env.staging` usan el rol dueño (`golden_db_owner`); para mínimo privilegio, crear un rol de app para la app y dejar el dueño solo a las migraciones

### Sesión 2 — pendiente
`deploy/gcp/bootstrap.sh`, staging en Cloud Run + workflow de GitHub Actions, jobs programados (respaldos, purga,
check_backups, precalentamiento, congelamiento de despliegues), scripts de migración VM→Neon/GCS con verificación.

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
  `fsouza/fake-gcs-server` (se salta si no está `STORAGE_EMULATOR_HOST`). **Pendiente: correrla** (Docker Desktop no arrancó en
  este equipo; ver nota de la sesión).
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
- Docker Desktop en el equipo de Juan David: falla al arrancar («initializing Inference manager… dockerInference»), un socket
  viejo del 4-sep que Windows no deja borrar (error 1920). Arreglo: reiniciar Windows.
