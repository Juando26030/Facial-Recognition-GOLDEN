# GoldenWeb 2.0 (repositorio Facial-Recognition GOLDEN)

Plataforma de gestión de identidades y acceso para eventos de Golden Eventos y Logística S.A.S.: registro por cédula, QR o reconocimiento facial **voluntario**, escarapelas, formularios web públicos
con pagos (Wompi), ruleta, estadísticas y reportes. FastAPI + SQLAlchemy (síncrono) + PostgreSQL (Neon) en Cloud Run + Alembic; frontend Jinja2 + JS plano; motor facial `face_recognition`/dlib; modo de
contingencia sin conexión en el quiosco (IndexedDB). Consentimiento explícito de la persona, registrado de forma inmutable (`audit_consent_logs`), y borrado de lo biométrico a los 7 días de finalizado
el evento. Bloque legal del piloto: `docs/legal/` (textos de la auditora, decisiones y pendientes). Repo público: https://github.com/Juando26030/Facial-Recognition-GOLDEN

**Reglas inamovibles y decisiones de Juan David (consolidado): [`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`](docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md).** **Para retomar el trabajo en curso lee primero [`docs/ESTADO_2026-11-11.md`](docs/ESTADO_2026-11-11.md), [`docs/REGLAS_Y_FORMA_DE_TRABAJO.md`](docs/REGLAS_Y_FORMA_DE_TRABAJO.md) y [`docs/HANDOFF.md`](docs/HANDOFF.md).** El detalle de cada sprint (porqués, bugs reales y
cómo se arreglaron) está en [`docs/historial.md`](docs/historial.md). Lo que falta construir (decidido con Juan David) está en [`docs/16_BACKLOG_PRODUCTO.md`](docs/16_BACKLOG_PRODUCTO.md) y el servidor local sin internet en [`docs/17_SERVIDOR_LOCAL.md`](docs/17_SERVIDOR_LOCAL.md). **Para poner producción en Cloud Run: [`docs/19_GUIA_PRODUCCION.md`](docs/19_GUIA_PRODUCCION.md)** (la ejecuta Juan David; Claude no corre nada en la nube). **Antes de dar CUALQUIER comando de despliegue lee [`deploy/gcp/README.md`](deploy/gcp/README.md)** (formato exacto del comando, `FORCE=1`, `ONEDRIVE_DRIVE_ID`, comprobar rama/commit). Los documentos de producto (`docs/00`–`06`) los mantiene otra sesión:
si no coinciden con el código, manda el código y este archivo.

## Infraestructura: hoy y heredado
- **Hoy (producción, desde el 28-oct-2026):** Cloud Run `us-east4` (3 servicios de UNA imagen: `golden-web`, `golden-publico`, `golden-biometria`;
  Jobs de migraciones, carga masiva y operaciones) + Neon Postgres 18 + Cloud Storage + Cloud Tasks + Cloud Scheduler + Firebase Hosting (dominio
  `app.golden-eventos.com`) + Secret Manager + Workload Identity Federation. Staging: lo mismo en un proyecto aparte (`staging.golden-eventos.com`).
  Hoy se despliega a mano con `deploy/gcp/manual_deploy.sh` (ver [`deploy/gcp/README.md`](deploy/gcp/README.md) y qué corre dónde en
  [`CHANGELOG.md`](CHANGELOG.md)); `main` va atrasado respecto de producción hasta que Juan David autorice ponerlo al día
  ([`docs/revision_2026-11-22/02_codigo_calidad_repo.md`](docs/revision_2026-11-22/02_codigo_calidad_repo.md) §4.1). Respaldos y recuperación:
  [`docs/19_GUIA_PRODUCCION.md`](docs/19_GUIA_PRODUCCION.md) § «Recuperación ante desastre en Cloud Run + Neon». Arquitectura:
  [`docs/13`](docs/13_ARQUITECTURA_ESCALABILIDAD.md); progreso y decisiones de la migración: [`docs/15_MIGRACION.md`](docs/15_MIGRACION.md);
  resultados de carga y facial: [`docs/14`](docs/14_FASE0_RESULTADOS.md).
- **Heredado (ya NO es producción):** VM `golden-biometrics-prod` (Gunicorn + Postgres local + Nginx; `deploy/gunicorn.conf.py`,
  `deploy/facial-recognition.service`, `.github/workflows/deploy.yml` solo manual). Ver [`deploy/LEEME.md`](deploy/LEEME.md) y
  [`docs/recuperacion_desastre.md`](docs/recuperacion_desastre.md) (solo sirve si se volviera a la VM).

## Mapa del código
```
app/main.py            app, middlewares (CSRF por Origin, cookie de sesión, no-store en HTML, logs), rutas de páginas
app/database.py        engine (pool persistente, pre_ping, reintentos); DATABASE_URL obligatoria
app/models.py          modelos; app/auth.py roles y permisos (require_role, effective_roles, get_event_for_staff)
app/routers/           api.py (registro, reconocimiento, directorio, carga masiva), events, forms/forms_public/form_payments,
                       badges, roulette, ops (/health, /ready, /sistema, /internal/jobs/run), …
app/pruebas/          páginas de prueba sin datos (lector de cédula PDF417 en /pruebas/lector-cedula; docs/PRUEBA_LECTOR_CEDULA.md)
app/storage.py         archivos: LocalStorage | GcsStorage (STORAGE_BACKEND); claves como acme/known_people/1001.jpg
app/uploads.py         subida directa de archivos grandes (URLs firmadas / PUT local)
app/jobs.py            cola en Postgres; la despierta un hilo (JOBS_BACKEND=db) o Cloud Tasks (cloudtasks)
app/bulk_jobs.py       carga masiva con progreso: hilo (BULK_BACKEND=thread) o Cloud Run Job (cloudrun, app/bulk_runner.py)
app/name_index.py      cédula no encontrada → candidatos por NOMBRE (índice por cliente; misma regla que api._identity_name_matches; no recorrer personas a mano)
app/faces.py           reconocimiento: matriz del evento en memoria, cálculo en procesos hijo (face_worker.py), biometrics.py
app/formlib.py         lógica pura de formularios; app/formsvc.py lo que toca la base (cupo atómico: form_reserve_slot)
app/ops.py             estado del sistema; app/ops_runner.py Job horario (respaldos, purga, cola, precalentamiento: app/warmup.py)
app/appmode.py         APP_MODE all|publico|web|biometria (app/entrypoints/); qué rutas sirve cada servicio
app/crypto.py, privacy.py   cifrado del rostro (FACE_ENCRYPTION_KEY) y retención/purga biométrica
app/server_keys.py, server_lock.py, routers/server_keys.py   llaves de producto del servidor local (docs/17_SERVIDOR_LOCAL.md § Llaves): crear/ver/deshabilitar, instalador liviano, bloqueo al deshabilitar
app/event_transfer.py, event_transfer_jobs.py   exportar/importar un evento completo entre entornos (docs/18_EXPORTAR_EVENTOS.md); solo super_admin
static/js/             app.js (kiosco), directory.js, toast.js, form-render.js, badge-render.js, …
templates/             páginas Jinja2; alembic/versions/ migraciones; tests/ pytest (+ tests/js)
scripts/               create_staff_user, bench_jitters, purge_biometrics, neon_app_role, migrate_db_to_neon, migrate_files_to_gcs, …
deploy/                gunicorn, systemd, nginx (VM) · gcp/ (bootstrap.sh, deploy.sh, config.sh, env/) · firebase/ · docker-compose.yml
```

## Comandos
```bash
pip install -r requirements.txt && cp .env.example .env        # local (Windows: usar Python 3.13; la VM y la imagen usan 3.14)
alembic upgrade head                                           # migraciones (en Neon: con DIRECT_DATABASE_URL = rol dueño)
python scripts/create_staff_user.py --username admin --role super_admin
uvicorn app.main:app --reload --port 5000
python -m pytest -q                                            # base propia golden_test (se crea sola; se niega sin «test» en el nombre)
node tests/js/directory_paging_check.js
ruff check .                                                    # el CI revisa TODO el repo (desde 0B); opcional: pip install pre-commit && pre-commit install
docker compose -f deploy/docker-compose.yml build && docker compose -f deploy/docker-compose.yml up publico web biometria   # usa .env.staging
STORAGE_EMULATOR_HOST=http://localhost:4443 python -m pytest -q tests/test_migrate_files.py   # con fsouza/fake-gcs-server corriendo
```

## Reglas técnicas (romperlas ya causó caídas o bugs reales; detalle en docs/historial.md)
- **Endpoints `def`, no `async def`** (todo el acceso a base es síncrono). Excepción: `submit` de formularios y `webhook` de Wompi, que leen
  el cuerpo y usan `run_in_threadpool`, y `page`/`state`/`quote` del formulario público (sirven una caché en el bucle de eventos, sin hilo ni base). Los `UploadFile` se leen con `file.file.read()`.
- **Configuración solo por variables de entorno** (`.env.example`, `.env.staging.example`, `deploy/gcp/env/common.yaml`). Nada de valores
  de producción en el código.
- **Base de datos compatible con el pooler de Neon (modo transacción):** nada de `SET` de sesión, tablas temporales, `LISTEN/NOTIFY` ni
  advisory locks de sesión; `FOR UPDATE` sí. Migraciones por conexión directa. **Revision id de Alembic ≤ 32 caracteres**; migraciones
  escritas a mano. La sesión usa `autoflush=False`: tras `db.add(User(...))` hace falta `db.flush()` antes de crear filas que dependan de
  él, y en cargas por lotes, un SAVEPOINT por fila.
- **Archivos solo por `app/storage.py`** (`get_storage()`), nunca `open()`/`FileResponse` sobre `data/`. Fotos biométricas con
  `photo_key()` (prefijo `BIOMETRIC_KEY_PREFIX` en la nube).
- **Trabajo en segundo plano por `app/jobs.py`** (`enqueue` en la misma transacción, después `kick()`; manejadores idempotentes). Lo
  largo (cargas de fotos, respaldos) va en Cloud Run Jobs, nunca en un hilo en Cloud Run.
- **Horas internas en UTC** (`datetime.utcnow()`); hora local solo al mostrar/leer (`app/timeutil.py`).
- **Nada de datos personales en logs** (cédulas, nombres, correos, encodings; `app/obs.py` enmascara lo que puede).
- **Salud:** `/health` no toca nada (lo usan monitores y la sonda de vida); `/ready` toca la base: SOLO sonda de arranque. En Cloud Run
  nunca rutas que terminen en «z» (`/healthz` da 404 de Google; `/healthz`/`/readyz` quedan para la VM). Nada frecuente
  puede tocar la base (Neon no se apagaría).
- **`/internal/*` solo con token OIDC de Google** de la cuenta invoker del entorno (`google_invoker` en `app/routers/ops.py`).
- **Detrás de Firebase Hosting:** solo pasa la cookie `__session` (`SESSION_COOKIE`), `CF-Connecting-IP` no es confiable
  (`TRUST_CF_CONNECTING_IP=0`, `XFF_CLIENT_INDEX`), 60 s máximo por petición.
- **Frontend:** `showToast`/`showConfirm`/`showPrompt` de `toast.js`, nunca `alert`/`confirm`/`prompt`; delegación de eventos para HTML
  generado (nada de `onclick` inline); en plantillas siempre `url_for('static', ...)` (agrega `?v=`); no mutar el subárbol de `e.target`
  antes de que el evento termine de burbujear; los formularios de datos no se cierran al hacer clic afuera.
- **Coordinador temporal (16-nov-2026):** `staff_users.event_only` (rol coordinador SOLO sobre sus eventos asignados; sin clientes, CRM, configuración ni otros eventos). La regla de rutas permitidas es `app/event_only.py` (lista de PERMITIDOS: una ruta global nueva queda cerrada hasta agregarla); detalle y decisiones en [`docs/COORDINADOR_TEMPORAL.md`](docs/COORDINADOR_TEMPORAL.md).
- **Permisos:** `STAFF_ROLES` = cliente < digitador < coordinador < comercial < admin < super_admin, con excepciones por rol
  (`require_role_excluding`, `effective_roles` para el doble rol coordinador+comercial). Dos puertas distintas: `get_event_for_staff`
  (acceso) y `require_event_in_progress` (registrar/reconocer).
- **Biometría (L1-L4, 2026-10):** la aceptación la da la PERSONA en la pantalla de la auditora y queda en `audit_consent_logs` (solo INSERT, 3 años; `app/consent.py`); sin aceptación registrada no hay reconocimiento facial (`app/faces.py`); el vector se calcula DESPUÉS de aceptar, por tarea (`app/enroll.py`), nunca en la puerta; menores de 18 años sin biometría (`app/minors.py`); supresión y revocación en `app/privacy.py` (`DELETE /api/attendees/{id}/purge-data`); los textos legales son LITERALES de la auditora (`app/legal_texts_data.py`, no se editan). Además: consentimiento expreso antes de guardar un rostro; cifrado con `FACE_ENCRYPTION_KEY` (perderla = perder los rostros);
  retención 7 días tras finalizar TODOS los eventos de la persona, tope 180 días desde la captura (`app/privacy.py`, paso `purge` del Job de ops); umbral 0,55, `RECOGNITION_JITTERS=2` y regla DUDOSO `MATCH_MARGIN` (docs/14 §6.2-6.3); el operador verifica con foto de registro y candidatos (`/api/recognize/*`).
- **Impresión (INAMOVIBLE, 28-oct-2026):** los parámetros probados en la Brother QL-800 (página SIEMPRE de 62 × 99,8 mm, imagen de máximo 96 mm, margen izquierdo 0,5 mm, marca de fin, misma etiqueta compuesta que el USB; **Chrome siempre normal con su cuadro de impresión: nunca `--kiosk-printing`**) están en [`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`](docs/IMPRESION_PARAMETROS_INAMOVIBLES.md) y los fija `tests/test_impresion_parametros_fijos.py`. Cualquier cambio que toque impresión compartida, el diseñador de escarapela, Parámetros, el USB o la ventana de impresión se hace respetándolos; cambiarlos solo si Juan David lo pide expresamente y se repite la prueba física.
- **Todo lo visual** (pantallas, componentes, correos, textos) sigue [`docs/ux/ESTANDARES_VISUALES.md`](docs/ux/ESTANDARES_VISUALES.md): solo tokens `--gw-*` y clases `.gw-*` de `static/css/design-system.css`, muestrario en `docs/ux/guia_visual.html`; nada de colores o tamaños sueltos.
- **Persona de prueba (5-nov-2026):** cada evento nuevo trae la cédula `PRUEBA` (`app/testperson.py`); nunca cuenta en reportes, estadísticas, ruleta ni contadores (usar `testperson.drop_test`/filtros al agregar consultas nuevas). Es la única que se registra/imprime con el evento en «creado». Registrar e imprimir al resto solo con el evento «en proceso».
- **Código de la persona (0140; campo desde 17-nov-2026):** serial aparte de la cédula (`EventAttendee.code`, `app/person_code.py`). El interruptor vive en Parámetros › Campos (arriba de las categorías) y SOLO con él activo existe la clave `code` en `parametros.field_configs_for_event` (bloqueado: solo nombre y posición; obligatorio según `Event.code_required`), y con ella: «Campos de la persona», Registrar/Editar, formulario de persona (`personform.EVENT_DECIDES`) y la variable «Código de la persona (QR)» del diseñador de escarapelas (`badge-print-data` trae `code`). Nunca se ofrece en formularios web públicos ni en la escarapela digital.
- **Inventario «lo define la base», dependientes y bloqueo del digitador (0161, 21-nov-2026):** [`docs/25_INVENTARIO_POR_BASE.md`](docs/25_INVENTARIO_POR_BASE.md). Lo que le toca a cada persona se calcula EN VIVO (`app/inv_assign.py`; reglas puras en `app/inv_assign_core.py`); la entrega guarda `assignment_key` (`h` / `d<uid>`, el uid de `event_dependents` no cambia al copiar el evento) y solo a registrados. El campo «Dependientes» es VIRTUAL: solo con `field_configs_for_event(..., include_virtual=True)` (Parámetros, Editar persona, Estadísticas); el resto nunca lo ve. Toda carga de base muestra vista previa (`app/roster_preview.py`, `mode=normal|append`) y no escribe nada. Candados en `app/config_lock.py` (el engranaje del registro ya no se oculta: pide contraseña).
- **Origen de carga:** `base` / `manual` / `autoregistro`; `manual` se muestra como «Creado nuevo». El estado es solo Registrado / No registrado.
- **Fases 0 y 1 cerradas (5-nov-2026):** [`docs/CIERRE_FASES_0_1.md`](docs/CIERRE_FASES_0_1.md). Siguiente: Fase 2 (diseño y calendario).
- Mensajes al usuario en español; identificadores en inglés; respuestas como dicts planos.

## Reglas de trabajo
- Toda rama que no sea `main` se puede empujar. **Nada a `main`, ningún merge, ningún despliegue a producción y ninguna migración en
  producción sin autorización explícita de Juan David para ESA acción.** No crear recursos de nube: los crea él (p. ej. `bootstrap.sh`).
- Un commit + push por pieza terminada (con sus pruebas pasando) y la lista de progreso de `docs/15_MIGRACION.md` al día.
- **Secretos nunca en el repo ni en el chat** (solo nombres de variables): van a `.env`/`.env.staging` (ignorados) o a Secret Manager
  (el bootstrap los pide a ciegas). Nada de fotos, encodings ni datos reales en el repo, logs o commits; resultados solo agregados.
- Pruebas de carga nunca contra producción, salvo la prueba «rush» que Juan David autorizó el 19-nov-2026 en un evento sintético (solo por [`docs/PRUEBA_CARGA_PRODUCCION.md`](docs/PRUEBA_CARGA_PRODUCCION.md), con sus candados en `deploy/loadtest/run_phase4.sh`). Ante una ambigüedad: decidir, documentar el porqué y seguir (salvo que Juan David pida que
  se le pregunte).
- El `.env` de la VM se edita o se le agregan líneas; nunca se reemplaza con el local (incidente real, ver historial).
- Windows: `.gitattributes` fuerza LF en `*.sh`/`*.yml`; con PowerShell/bash cuidado con `\f`, `\n` y comillas al generar archivos.
