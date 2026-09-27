# Migración a Cloud Run + Neon (Fases 1-2)

Rama `migra/fase1-2`. Plan y decisiones de fondo: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` (§4-8, §11, §14-16).
Este archivo se completa en la sesión 3 (runbook del día del cambio + costos); por ahora lleva la lista de progreso.

## Progreso (se actualiza en cada commit)

### Sesión 1 — la app queda lista para Cloud Run + Neon
- [x] 1. Cupo atómico: `form_reserve_slot()` (migración 0049) + wrapper en `formsvc` + `_submit` + pruebas de concurrencia
- [x] 2. `GcsStorage` en `app/storage.py`
- [x] 3. Backend Cloud Tasks en `app/jobs.py` (Postgres sigue como alternativa)
- [x] 4. Directorio paginado e incremental en `static/js/directory.js`
- [~] 5. Dockerfile multi-etapa + 3 puntos de entrada — escrito; FALTA construirlo y levantarlo (Docker Desktop no arranca en este equipo)
- [~] 6. `.env.staging.example` + `.env.staging` en `.gitignore` (hecho) → FALTA: Juan David llena `.env.staging`, luego migraciones y contenedor contra Neon staging

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
- Cola con Cloud Tasks (`JOBS_BACKEND=cloudtasks`): la tabla `jobs` sigue siendo la fuente de verdad; Cloud Tasks solo despierta a
  `POST /internal/jobs/run` (token OIDC de `JOBS_INVOKER_SA`, audiencia `CLOUD_TASKS_URL`, o `X-Ops-Token`). Una tarea por
  segundo como máximo (`kick-<segundo>`) y cada reintento programa la suya. Sin Cloud Scheduler para la cola: el barrido de
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
