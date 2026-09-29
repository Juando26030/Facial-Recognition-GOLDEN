# Golden Biometrics — Facial Recognition GOLDEN

SaaS de control de acceso e inscripción para eventos de Golden Logísticas: registro por cédula, QR o reconocimiento facial, escarapelas,
formularios web públicos con pagos (Wompi), ruleta, estadísticas y reportes. FastAPI + SQLAlchemy (síncrono) + PostgreSQL + Alembic;
frontend Jinja2 + JS plano; motor facial `face_recognition`/dlib. Repo público: https://github.com/Juando26030/Facial-Recognition-GOLDEN

**Para retomar el trabajo en curso lee primero [`docs/HANDOFF.md`](docs/HANDOFF.md).** El detalle de cada sprint (porqués, bugs reales y
cómo se arreglaron) está en [`docs/historial.md`](docs/historial.md). Los documentos de producto (`docs/00`–`06`) los mantiene otra sesión:
si no coinciden con el código, manda el código y este archivo.

## Infraestructura: hoy y destino
- **Hoy (producción):** VM `golden-biometrics-prod` (us-central1-a, e2-custom 2 vCPU/4 GB), Gunicorn 3 procesos (`deploy/gunicorn.conf.py`,
  `deploy/facial-recognition.service`), Postgres local (la app usa el rol `golden_app`), Nginx + Cloudflare, dominio
  `app.golden-eventos.com`. Despliegue: push a `main` → `.github/workflows/deploy.yml` (runner self-hosted en la VM; congela si hay eventos).
  Respaldos por cron a los buckets de GCS; ver [`docs/recuperacion_desastre.md`](docs/recuperacion_desastre.md).
- **Destino (rama `migra/fase1-2`, sin desplegar):** Cloud Run (3 servicios de UNA imagen: `publico`, `web`, `biometria`; Jobs de
  migraciones, carga masiva y operaciones) + Neon Postgres 18 + Cloud Storage + Cloud Tasks + Cloud Scheduler + Firebase Hosting (dominio) +
  Secret Manager + Workload Identity Federation. Plan: [`docs/13`](docs/13_ARQUITECTURA_ESCALABILIDAD.md); progreso y decisiones:
  [`docs/15_MIGRACION.md`](docs/15_MIGRACION.md); resultados de carga y facial: [`docs/14`](docs/14_FASE0_RESULTADOS.md).

## Mapa del código
```
app/main.py            app, middlewares (CSRF por Origin, cookie de sesión, no-store en HTML, logs), rutas de páginas
app/database.py        engine (pool persistente, pre_ping, reintentos); DATABASE_URL obligatoria
app/models.py          modelos; app/auth.py roles y permisos (require_role, effective_roles, get_event_for_staff)
app/routers/           api.py (registro, reconocimiento, directorio, carga masiva), events, forms/forms_public/form_payments,
                       badges, roulette, ops (/health, /ready, /sistema, /internal/jobs/run), …
app/storage.py         archivos: LocalStorage | GcsStorage (STORAGE_BACKEND); claves como acme/known_people/1001.jpg
app/uploads.py         subida directa de archivos grandes (URLs firmadas / PUT local)
app/jobs.py            cola en Postgres; la despierta un hilo (JOBS_BACKEND=db) o Cloud Tasks (cloudtasks)
app/bulk_jobs.py       carga masiva con progreso: hilo (BULK_BACKEND=thread) o Cloud Run Job (cloudrun, app/bulk_runner.py)
app/faces.py           reconocimiento: matriz del evento en memoria, cálculo en procesos hijo (face_worker.py), biometrics.py
app/formlib.py         lógica pura de formularios; app/formsvc.py lo que toca la base (cupo atómico: form_reserve_slot)
app/ops.py             estado del sistema; app/ops_runner.py Job horario (respaldos, purga, cola, precalentamiento: app/warmup.py)
app/appmode.py         APP_MODE all|publico|web|biometria (app/entrypoints/); qué rutas sirve cada servicio
app/crypto.py, privacy.py   cifrado del rostro (FACE_ENCRYPTION_KEY) y retención/purga biométrica
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
ruff check $(git diff --name-only --diff-filter=AM main...HEAD -- '*.py')   # CI solo revisa archivos nuevos o tocados
docker compose -f deploy/docker-compose.yml build && docker compose -f deploy/docker-compose.yml up publico web biometria   # usa .env.staging
STORAGE_EMULATOR_HOST=http://localhost:4443 python -m pytest -q tests/test_migrate_files.py   # con fsouza/fake-gcs-server corriendo
```

## Reglas técnicas (romperlas ya causó caídas o bugs reales; detalle en docs/historial.md)
- **Endpoints `def`, no `async def`** (todo el acceso a base es síncrono). Excepción: `submit` de formularios y `webhook` de Wompi, que leen
  el cuerpo y usan `run_in_threadpool`. Los `UploadFile` se leen con `file.file.read()`.
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
- **Permisos:** `STAFF_ROLES` = cliente < digitador < coordinador < comercial < admin < super_admin, con excepciones por rol
  (`require_role_excluding`, `effective_roles` para el doble rol coordinador+comercial). Dos puertas distintas: `get_event_for_staff`
  (acceso) y `require_event_in_progress` (registrar/reconocer).
- **Biometría:** consentimiento expreso antes de guardar un rostro; cifrado con `FACE_ENCRYPTION_KEY` (perderla = perder los rostros);
  retención 180 días tras el fin del evento (`scripts/purge_biometrics.py`); umbral 0,55 y `RECOGNITION_JITTERS=2` (docs/14 §6.2).
- Mensajes al usuario en español; identificadores en inglés; respuestas como dicts planos.

## Reglas de trabajo
- Toda rama que no sea `main` se puede empujar. **Nada a `main`, ningún merge, ningún despliegue a producción y ninguna migración en
  producción sin autorización explícita de Juan David para ESA acción.** No crear recursos de nube: los crea él (p. ej. `bootstrap.sh`).
- Un commit + push por pieza terminada (con sus pruebas pasando) y la lista de progreso de `docs/15_MIGRACION.md` al día.
- **Secretos nunca en el repo ni en el chat** (solo nombres de variables): van a `.env`/`.env.staging` (ignorados) o a Secret Manager
  (el bootstrap los pide a ciegas). Nada de fotos, encodings ni datos reales en el repo, logs o commits; resultados solo agregados.
- Pruebas de carga nunca contra producción. Ante una ambigüedad: decidir, documentar el porqué y seguir (salvo que Juan David pida que
  se le pregunte).
- El `.env` de la VM se edita o se le agregan líneas; nunca se reemplaza con el local (incidente real, ver historial).
- Windows: `.gitattributes` fuerza LF en `*.sh`/`*.yml`; con PowerShell/bash cuidado con `\f`, `\n` y comillas al generar archivos.
