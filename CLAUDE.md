# Golden Biometrics — Facial Recognition GOLDEN

## Qué es esto
SaaS de control de acceso e identidad por reconocimiento facial, pensado para reemplazar planillas/tarjetas físicas en sedes de "Golden Logísticas". Backend FastAPI + PostgreSQL, motor biométrico con `face_recognition` (dlib), frontend server-rendered (Jinja2 + JS plano). Pensado para desplegarse en una VM de Google Cloud detrás de Nginx/Cloudflare, con systemd gestionando los procesos.

Repo: https://github.com/Juando26030/Facial-Recognition-GOLDEN

## Arquitectura
```
app/
  main.py           FastAPI app, monta /static y templates, incluye el router /api
  database.py       Engine SQLAlchemy, lee DATABASE_URL desde .env (obligatorio, sin fallback)
  models.py         Tenant, User, AccessLog (SQLAlchemy declarative)
  biometrics.py     BiometricEngine: extracción y comparación de encodings faciales
  reports.py        ReportManager: genera reporte Excel (pandas + openpyxl)
  routers/api.py    Todos los endpoints REST bajo /api
static/             CSS/JS + (antes) el .env real — YA CORREGIDO, ver sección Seguridad
templates/          index.html (SPA simple servida por Jinja2)
data/<tenant>/known_people/   Fotos de registro por tenant (gitignored)
```

### Modelo de datos
- `Tenant(id, name)` — soporte multi-tenant a nivel de esquema.
- `User(id, tenant_id)` — clave primaria compuesta. Guarda `face_encoding` como JSON en un `Text`.
- `AccessLog(id, tenant_id, user_id, timestamp, record_type)` — bitácora de eventos ("Nuevo", "Existente", "Actualizado").

### Multi-tenant: real pero no explotado
El modelo soporta múltiples tenants, pero `app/routers/api.py` tiene **hardcodeado** `CURRENT_TENANT = "golden_hq"` (línea 19). Todos los endpoints filtran por ese tenant fijo. Para servir más de un cliente hay que sacar el tenant del request (subdominio, header, JWT, etc.), no solo de la constante.

### Motor biométrico (`app/biometrics.py`)
- `num_jitters=25` en registro inicial, `10` en reconocimiento — más remuestreo al registrar para un encoding más estable.
- Tolerancia de comparación ajustada a **0.55** (default de la librería es 0.6, la bajaron a propósito para ser más estrictos y reducir falsos positivos).
- Sin control de calidad de imagen (blur, múltiples caras, spoofing) antes de generar el encoding.

## Convenciones del proyecto
- Español para nombres de negocio (mensajes de API, comentarios de dominio); código e identificadores técnicos en inglés/estándar.
- Sin capa de servicios: los routers hablan directo con SQLAlchemy y con `BiometricEngine`. Está bien para el tamaño actual; si crece, separar en servicios antes de que `api.py` se vuelva inmanejable.
- Los endpoints devuelven dicts planos (`{"result": ..., "data": ...}`), no hay schemas Pydantic de respuesta.

## Seguridad — incidente resuelto (2026-09-14)
Se encontró y corrigió una exposición de credenciales real en producción:
1. **`static/.env` estaba commiteado al repo público** con la cadena de conexión real de PostgreSQL. Como `static/` se monta directo como `StaticFiles` en `/static` (`app/main.py:13`), ese archivo era descargable por HTTP en producción (`/static/.env` devolvía 200 con la credencial en texto plano — confirmado y luego verificado como cerrado). → Se movió a `.env` en la raíz (gitignored) y se quitó del índice de git.
2. **`app/database.py` tenía esa misma credencial quemada como valor por defecto** si `DATABASE_URL` no estaba seteada. → Ahora la app falla al arrancar (`RuntimeError`) si no hay `DATABASE_URL` en el entorno, en vez de caer silenciosamente a una credencial real.
3. Se agregó `.env.example` con placeholders y se reforzó `.gitignore` (`.env`, `static/.env`, `data/`, `known_people/`, `__pycache__/`).
4. **La contraseña de PostgreSQL en producción fue rotada** y el `.env` del servidor actualizado con la nueva.
5. **El historial de git fue reescrito** (`git filter-repo`, force-push a `main`) para eliminar tanto el archivo `static/.env` como cualquier commit anterior de `app/database.py` que contuviera la credencial vieja como texto plano. Si tienes un clon local anterior a esta fecha, su historial ya no coincide con `origin/main` — no hagas `git pull` normal sobre él, hay que resincronizar (`git fetch origin && git reset --hard origin/main`, perdiendo cualquier commit local no pusheado) o volver a clonar.

## Qué falta (backlog real, no aspiracional)
- **Sin autenticación/autorización en ningún endpoint.** `/api/register`, `/api/recognize`, `/api/users/{id}` (PATCH/DELETE de logs), `/api/bulk_register` están completamente abiertos. Cualquiera que llegue a la URL puede registrar, borrar logs o descargar el reporte de eventos. Es el hueco más grande antes de exponer esto a internet en serio.
- **Sin tests.** No hay carpeta `tests/` ni configuración de pytest.
- **Sin migraciones.** `Base.metadata.create_all(bind=engine)` en `main.py:9` crea tablas al vuelo; no hay Alembic. Cualquier cambio de esquema en producción es manual.
- **Sin CI/CD.** No hay `.github/workflows/`. El objetivo es: push a `main` → GitHub Actions se conecta por SSH a la VM de GCP → `git pull` + restart de los servicios systemd. Pendiente de datos concretos de la VM (IP, usuario SSH, si ya existe llave de despliegue) para armarlo.
- **Multi-tenant no explotado** (ver arriba) — hoy es de un solo tenant en la práctica.
- **`bulk_register` no valida CSV/ZIP de forma robusta**: `except: pass` silencioso al procesar imágenes del zip (`api.py:147`), puede ocultar errores reales de registros que no se cargaron.
- **README ausente** — no hay instrucciones de instalación/arranque para alguien nuevo en el proyecto.
- **`requirements.txt` sin versiones fijadas** — riesgo de que una actualización de `face_recognition`/`dlib` rompa el build en un entorno nuevo.

## Cómo correrlo localmente
```bash
pip install -r requirements.txt
cp .env.example .env   # y editar DATABASE_URL
uvicorn app.main:app --reload
```
Requiere PostgreSQL corriendo y accesible con la URL de `.env`. `face_recognition` depende de `dlib`, que en Windows suele requerir Visual C++ Build Tools o usar un wheel precompilado.

## Infraestructura objetivo (producción)
- VM Google Cloud (Ubuntu), IP pública estática.
- Nginx como reverse proxy + terminación TLS (certificados gestionados ahí).
- Cloudflare delante como proxy/DNS.
- Systemd para mantener vivos PostgreSQL, la app FastAPI (uvicorn/gunicorn) y reiniciarlos si caen.
- Nada de esto está automatizado todavía desde este repo (no hay `Dockerfile`, ni unit files de systemd versionados, ni el workflow de GitHub Actions). Es el siguiente paso natural del backlog de CI/CD.
