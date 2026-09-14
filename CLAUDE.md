# Golden Biometrics — Facial Recognition GOLDEN

## Qué es esto
SaaS de control de acceso e identidad por reconocimiento facial, pensado para reemplazar planillas/tarjetas físicas en sedes de "Golden Logísticas". Backend FastAPI + PostgreSQL, motor biométrico con `face_recognition` (dlib), frontend server-rendered (Jinja2 + JS plano). Pensado para desplegarse en una VM de Google Cloud detrás de Nginx/Cloudflare, con systemd gestionando los procesos.

Repo: https://github.com/Juando26030/Facial-Recognition-GOLDEN

## Arquitectura
```
app/
  main.py           FastAPI app: SessionMiddleware, monta /static y templates, incluye routers
  database.py       Engine SQLAlchemy, lee DATABASE_URL desde .env (obligatorio, sin fallback)
  models.py         Tenant, User, AccessLog, StaffUser, Event, EventStaffAuthorization
  auth.py           Hashing (bcrypt), get_current_staff, require_role(minimum) — jerarquía de roles
  biometrics.py     BiometricEngine: extracción y comparación de encodings faciales
  reports.py        ReportManager: genera reporte Excel (pandas + openpyxl)
  routers/
    api.py            Endpoints biométricos (recognize/register/users/report) bajo /api, protegidos por rol
    auth.py            /login, /logout
    events.py          CRUD de eventos bajo /api/events
    staff.py            Gestión de cuentas de staff y autorización por evento bajo /api/staff
alembic/            Migraciones versionadas (ver sección Migraciones) — reemplaza Base.metadata.create_all
scripts/create_staff_user.py   Bootstrap del primer Super Admin (o cualquier cuenta) desde la terminal
static/             CSS/JS + (antes) el .env real — YA CORREGIDO, ver sección Seguridad
templates/          index.html (kiosko), login.html, events.html, staff.html
data/<tenant>/known_people/   Fotos de registro por tenant (gitignored)
```

### Modelo de datos
- `Tenant(id, name)` — soporte multi-tenant a nivel de esquema.
- `User(id, tenant_id)` — la **persona biométrica** registrada (empleado/visitante). Clave primaria compuesta. Guarda `face_encoding` como JSON en un `Text`. No confundir con `StaffUser`.
- `AccessLog(id, tenant_id, user_id, timestamp, record_type, event_id, registered_by_staff_id)` — bitácora de eventos de reconocimiento/registro ("Nuevo", "Existente", "Actualizado"). Las dos últimas columnas (auditoría: qué evento, qué cuenta de staff) existen en el esquema pero **todavía no se llenan desde el flujo del kiosko** — ver backlog.
- `StaffUser(id, username, password_hash, full_name, role, tenant_id, is_active, created_by_id)` — cuenta de staff interno (quien opera el sistema, no quien es registrado). `role` es uno de `STAFF_ROLES` en `models.py`. Para digitadores, `username` es la cédula.
- `Event(id, tenant_id, name, location, start_date, end_date, status, created_by_id)` — una sesión de registro puntual dentro de un tenant (`status`: `activo`/`cerrado`).
- `EventStaffAuthorization(event_id, staff_user_id, authorized_by_id)` — qué cuenta de staff puede operar en qué evento. Obligatorio en el diseño para `digitador` (acceso temporal, se revoca dejando de reautorizar); no se exige para `coordinador`/`admin`/`super_admin` (alcance de tenant/global).

### Roles y permisos (`app/auth.py`)
Jerarquía fija en `STAFF_ROLES` (`models.py`), de menor a mayor: `digitador < coordinador < admin < super_admin`. `require_role("x")` exige ese rol o superior — la jerarquía funciona porque cada rol es superset del anterior en este sistema (no hay permisos "cruzados" que un rol tenga y otro no salvo los casos explícitos de abajo).

| Acción | Rol mínimo |
|---|---|
| Reconocer / registrar persona (`/api/recognize`, `/api/register`) | `digitador` |
| Ver directorio, editar perfil, carga masiva, descargar reporte, crear/editar evento | `coordinador` |
| Borrado permanente (logs de un usuario, eliminar evento), crear/desactivar cuentas `coordinador`/`digitador`, autorizar digitador para un evento | `admin` |
| Crear cuentas `admin` | `super_admin` (único caso que no es "jerarquía", está hardcodeado en `routers/staff.py`) |

**Pendiente de conectar:** hoy cualquier cuenta autenticada (incluido un `digitador`) puede llamar `/api/recognize` y `/api/register` sin que se valide `EventStaffAuthorization` — la tabla y el endpoint para autorizar existen (`POST /api/staff/{id}/authorize-event/{id}`, con UI en `/admin/staff`), pero el flujo del kiosko (`index.html`/`app.js`) todavía no pide "elegir evento activo" antes de escanear. Falta decidir la UX de eso (¿selector de evento al iniciar sesión? ¿un evento activo por dispositivo?) antes de cablearlo.

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
- ~~Sin autenticación~~ **Resuelto (2026-09-14):** login + 4 roles (ver sección Roles y permisos). Lo que sigue faltando de esto: conectar `EventStaffAuthorization` al flujo real de recognize/register (ver nota arriba), CSRF explícito (mitigado parcial por `SameSite=Lax`), rate limiting de intentos de login, y una UI de "olvidé mi contraseña" (hoy solo un admin puede resetear, manualmente, no hay endpoint para eso todavía).
- **Sin tests.** No hay carpeta `tests/` ni configuración de pytest.
- ~~Sin migraciones~~ **Resuelto (2026-09-14):** Alembic (ver sección Migraciones abajo). `Base.metadata.create_all` ya no se llama desde `main.py`.
- ~~Sin CI/CD~~ **Resuelto (2026-09-14):** `.github/workflows/deploy.yml` corre en un runner self-hosted instalado directo en la VM (`golden-biometrics-prod`). Se eligió self-hosted y no SSH-desde-GitHub porque el proyecto tiene **OS Login activado** en GCP, que bloquea el acceso SSH por llave externa — el runner evita ese problema porque corre dentro de la VM, no entra desde afuera. En cada push a `main`: `git fetch` + `git reset --hard origin/main` + `systemctl restart facial-recognition`. También soporta disparo manual (`workflow_dispatch`).
  - **Nota de seguridad:** el repo es público. El workflow solo se dispara con `push` a `main` (requiere permiso de escritura al repo), nunca con `pull_request`, así que un PR externo no puede ejecutar código en el runner de producción. Si en algún momento se agrega un trigger de `pull_request` o `pull_request_target`, hay que exigir aprobación manual para colaboradores externos — de lo contrario cualquiera podría correr código arbitrario en la VM de producción a través de un PR.
- **Multi-tenant no explotado** (ver arriba) — hoy es de un solo tenant en la práctica.
- **`bulk_register` no valida CSV/ZIP de forma robusta**: `except: pass` silencioso al procesar imágenes del zip (`api.py:147`), puede ocultar errores reales de registros que no se cargaron.
- **README ausente** — no hay instrucciones de instalación/arranque para alguien nuevo en el proyecto.
- **`requirements.txt` sin versiones fijadas** — riesgo de que una actualización de `face_recognition`/`dlib` rompa el build en un entorno nuevo.
- **Sin roles/permisos granulares por usuario individual** — se decidió a propósito quedarse con 4 roles fijos en código por ahora (más simple, no hay todavía un catálogo real de "acciones" del sistema grande para armar un checklist granular). Si hace falta más adelante, revisar esta decisión.
- **Backup solo local** (`~/backups` en la VM, cron diario, rotación 7 días vía `pg_dump`). Backup offsite (bucket GCS) no está armado.
- **Monorepo:** el repo hoy sigue siendo solo este módulo en la raíz. Ya se decidió la estrategia (monorepo, `apps/<módulo>/`) pero la reestructuración física (mover esto a `apps/facial-recognition/`) todavía no se ejecutó — es la próxima rama.

## Migraciones (Alembic)
El esquema ya no se crea con `Base.metadata.create_all` — vive como migraciones versionadas en `alembic/versions/`.
```bash
alembic upgrade head          # aplica todas las migraciones pendientes
alembic revision -m "mensaje" # crea una migración nueva vacía (escribirla a mano, no autogenerate: no hay DB de referencia limpia garantizada)
```
**Importante para la VM de producción y cualquier DB que ya tenía las tablas `tenants`/`users`/`access_logs` de antes de que existiera Alembic** (creadas por el viejo `create_all`): la primera vez, en vez de `alembic upgrade head` derecho, hay que marcar la migración baseline como ya aplicada sin ejecutarla (`alembic stamp 0001_baseline`) y de ahí sí `alembic upgrade head` (que solo corre `0002_auth_roles_events` en adelante). Una DB nueva/vacía sí corre `upgrade head` normal desde el principio.

Para crear la primera cuenta (Super Admin, no hay UI para esto por diseño — sería circular): `python scripts/create_staff_user.py --username <tu_usuario> --role super_admin --full-name "..."`.

## Flujo de git (a partir de 2026-09-14)
- Toda rama que no sea `main` se puede empujar libremente — `deploy.yml` solo dispara con push a `main`, así que una rama nunca toca producción sola.
- Cambios de código/esquema: rama nueva → implementar → avisar al dueño del repo → él prueba en su entorno local (tiene Postgres + `pgAdmin4` con una copia de `golden_db`) → si aprueba, merge a `main` → el runner self-hosted despliega solo.
- No mergear a `main` sin autorización explícita, aunque el cambio "se vea listo".

## Cómo correrlo localmente
```bash
pip install -r requirements.txt
cp .env.example .env   # y editar DATABASE_URL (ENVIRONMENT=development deja /docs abierto)
alembic upgrade head   # crea/actualiza el esquema (ver sección Migraciones si la DB ya existía desde antes de Alembic)
python scripts/create_staff_user.py --username admin --role super_admin   # si no tienes cuenta todavía
uvicorn app.main:app --reload --port 5000
```
Requiere PostgreSQL corriendo y accesible con la URL de `.env`. `face_recognition` depende de `dlib`, que en Windows suele requerir Visual C++ Build Tools o usar un wheel precompilado.

## Infraestructura (producción)
- VM Google Cloud (`golden-biometrics-prod`, Ubuntu), IP pública estática, **OS Login activado** (bloquea SSH por llave externa/metadata — por eso el runner de CI/CD es self-hosted y no SSH-desde-afuera).
- Nginx como reverse proxy + terminación TLS (certificados Certbot). `sites-enabled/golden` — un solo server block, nada raro servido fuera de la app.
- Cloudflare delante como proxy/DNS.
- Postgres escucha solo en `localhost` (confirmado), `pg_hba.conf` exige `scram-sha-256` incluso en loopback — no hace falta endurecer nada ahí. `ufw` inactivo (normal en GCP, el firewall real es a nivel de red del proyecto, no se tocó).
- **La app se conecta con el rol `golden_app`** (mínimo privilegio sobre `golden_db`), no con el superusuario `postgres` (resuelto 2026-09-14). El rol `postgres` queda solo para administración manual.
- Backup diario automático (`pg_dump` + cron a las 3am, rotación local de 7 días en `~/backups`).
- Systemd (`facial-recognition.service`) mantiene viva la app FastAPI; se reinicia solo si cae.
- Deploy automático vía runner self-hosted de GitHub Actions instalado en la propia VM (ver `.github/workflows/deploy.yml`): en cada push a `main` instala dependencias, corre `alembic upgrade head`, y reinicia el servicio.
- Sigue faltando: `Dockerfile` y los unit files de systemd versionados en el repo (hoy `facial-recognition.service` solo existe en `/etc/systemd/system/` de la VM, no en git); backup offsite.
