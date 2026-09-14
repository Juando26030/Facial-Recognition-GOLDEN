# Golden Biometrics — Facial Recognition GOLDEN

## Qué es esto
SaaS de control de acceso e identidad por reconocimiento facial, pensado para reemplazar planillas/tarjetas físicas en sedes de "Golden Logísticas". Backend FastAPI + PostgreSQL, motor biométrico con `face_recognition` (dlib), frontend server-rendered (Jinja2 + JS plano). Pensado para desplegarse en una VM de Google Cloud detrás de Nginx/Cloudflare, con systemd gestionando los procesos.

Repo: https://github.com/Juando26030/Facial-Recognition-GOLDEN

## Arquitectura
```
app/
  main.py           FastAPI app: SessionMiddleware, /  (dashboard) y /kiosk/{event_id}, incluye routers
  database.py       Engine SQLAlchemy, lee DATABASE_URL desde .env (obligatorio, sin fallback)
  models.py         Tenant, User, AccessLog, StaffUser, Event, EventStaffAuthorization
  auth.py           Hashing (bcrypt), get_current_staff, require_role(minimum), get_event_for_staff
  biometrics.py     BiometricEngine: extracción y comparación de encodings faciales
  reports.py        ReportManager: genera reporte Excel (pandas + openpyxl)
  routers/
    api.py            Endpoints biométricos (recognize/register/users/report) bajo /api, event-scoped
    auth.py            /login, /logout
    tenants.py          CRUD de clientes (tenants) bajo /api/tenants
    events.py          CRUD de eventos (/api/events, /api/my-events, /api/events/search,
                        /api/cities) + cuentas digitador/cliente atadas a un evento
                        (/api/events/{id}/staff-users, .../assign-existing)
    staff.py            Cuentas coordinador/admin (no digitador/cliente, ver Roles y permisos)
  cities_data.py    Carga app/cities_by_country.json (dataset real GeoNames) — ver sección de ciudades
  cities_by_country.json   ~20,300 ciudades reales (GeoNames), generado offline una vez
alembic/            Migraciones versionadas (ver sección Migraciones) — reemplaza Base.metadata.create_all
scripts/create_staff_user.py   Bootstrap del primer Super Admin (o cualquier cuenta) desde la terminal
static/
  js/clockpicker.js   Selector de hora tipo reloj analógico (custom, sin dependencias) — ver abajo
  js/toast.js         showToast()/showConfirm() — reemplazo no-bloqueante de alert()/confirm()
  js/app.js           Lógica del kiosko (escáner, registro, directorio, etc.)
templates/          dashboard.html (`/`), kiosk_select.html (`/kiosk/{event_id}`),
                    kiosk.html (`/kiosk/{event_id}/facial`), login.html, staff.html
data/<tenant>/known_people/   Fotos de registro por tenant (gitignored, no confundir con app/cities_by_country.json — ese NO está en la carpeta "data/")
```

### Navegación (2026-09-15)
`/` ya NO es el escáner — es un dashboard según rol:
- `coordinador`/`admin`/`super_admin`: lista de **Tenants (clientes)**, expandible a sus **Eventos**, con formularios inline para crear cliente/evento. Cada evento tiene un botón "Ingresar" que lleva a `/kiosk/{event_id}`.
- `digitador`: lista plana de sus eventos autorizados y activos (`GET /api/my-events`), mismo botón "Ingresar".

`/kiosk/{event_id}` es la pantalla de escaneo/registro/directorio/reporte (el viejo `index.html`, ahora `kiosk.html`), **atada a un evento concreto**: `app/main.py` valida el acceso con `get_event_for_staff` antes de renderizarla (404/403 → redirige a `/`), y le inyecta `window.EVENT_ID` al JS. Todas las llamadas de `static/js/app.js` a `/api/recognize`, `/api/register`, `/api/users*`, `/api/bulk_register`, `/api/report` ahora mandan `event_id` (query param o campo del FormData) — el backend resuelve el `tenant_id` a partir del evento, ya no hay tenant fijo.

**Selección de método de registro (2026-09-17) — preparado para multi-método simultáneo.** El negocio va a tener más de una forma de registrar gente en el mismo evento (facial, QR, ...) y **al mismo tiempo** (una persona usando cara, otra usando QR, para el mismo evento, en paralelo) — por eso el "método" es una elección de la SESIÓN/pestaña de quien está operando, no una propiedad del Evento. Flujo real:
- `GET /kiosk/{event_id}` (`main.py: kiosk_entry`) ya no renderiza directo el escáner. Para `cliente` (que no registra nada) sigue yendo directo a `kiosk.html` (su vista de Estadísticas+Directorio). Para todos los demás roles, renderiza `templates/kiosk_select.html`: una pantalla con tarjetas para elegir el método.
- Hoy solo existe un método real: **Facial**, en `GET /kiosk/{event_id}/facial` (`main.py: kiosk_facial`) → el `kiosk.html` de siempre. **QR** aparece en la pantalla de selección como tarjeta deshabilitada ("Próximamente") — no hay backend ni UI para QR todavía, es un placeholder a propósito.
- El redirect automático de `digitador`/`cliente` con un solo evento activo (`main.py: dashboard`) sigue apuntando a `/kiosk/{event_id}` (no directo a `/facial`), así que un digitador SÍ ve la pantalla de selección de método aunque tenga un solo evento — solo `cliente` se salta ese paso.
- **Para cuando se agregue un segundo método de verdad:** cada método debería vivir en su propia ruta (`/kiosk/{event_id}/<método>`) con su propio template, todos escribiendo `AccessLog` con el mismo `event_id` — así el Directorio en Vivo y el Reporte, que ya son agnósticos de cómo se registró a alguien, siguen funcionando igual sin cambios. Las pestañas de gestión (Directorio, Carga Masiva, Exportar, Usuarios del Evento) hoy viven dentro de `kiosk.html` (el método Facial) — cuando exista un segundo método, vale la pena evaluar si esas pestañas de gestión se separan a una vista común en vez de duplicarse por método.

**Notificaciones (2026-09-17):** `static/js/toast.js` reemplaza `alert()`/`confirm()` en todo el proyecto (`dashboard.html`, `kiosk.html`, `staff.html`, `app.js`) — `showToast(mensaje, "success"|"error")` (pill que aparece arriba a la derecha y se desvanece solo, sin bloquear) y `showConfirm(mensaje)` (modal no-bloqueante que devuelve una `Promise<boolean>`, hay que usarlo con `await` dentro de una función `async`). No queda ningún `alert`/`confirm` nativo del navegador en el código — si se agrega un flujo CRUD nuevo, usar estos dos en vez del nativo.

### Modelo de datos
- `Tenant(id, name, contact_name, contact_phone, contact_email)` — un **cliente** de Golden (empresa para la que se hace el evento), con su contacto. No confundir con `StaffUser` (cuentas de staff interno).
- `User(id, tenant_id)` — la **persona biométrica** registrada (empleado/visitante/asistente). Clave primaria compuesta. Guarda `face_encoding` como JSON en un `Text`.
- `AccessLog(id, tenant_id, user_id, timestamp, record_type, event_id, registered_by_staff_id)` — bitácora de reconocimiento/registro ("Nuevo", "Existente", "Actualizado"). `event_id` y `registered_by_staff_id` **ya se llenan** desde `routers/api.py` en cada acción — la auditoría de "quién registró a quién en qué evento" está conectada de punta a punta.
- `StaffUser(id, username, password_hash, full_name, role, tenant_id, is_active, created_by_id)` — cuenta de staff interno. `role` es uno de `STAFF_ROLES` en `models.py`. Para digitadores, `username` es la cédula.
- `Event(id, tenant_id, event_code, name, location, address, country, city, start_date, end_date, setup_date, event_time_start/end, setup_time_start/end, coordinator_staff_id, notes, status, created_by_id)` — una sesión de registro puntual dentro de un tenant. `start_date`/`end_date`/`setup_date` son **`Date`, no `DateTime`** (migración `0005`) — la hora vive por separado en los 4 campos `*_time_*` (`"HH:MM"`), pedirla dos veces en el mismo campo no tenía sentido. `coordinator_staff_id` apunta a un `StaffUser` con `role='coordinador'` (validado en `routers/events.py`). Todos los campos son obligatorios al crear un evento (`EventIn` en `routers/events.py`) salvo `notes`.
  - **Ciclo de vida de `status` (2026-09-18, migración `0006`, `EVENT_STATUSES` en `models.py`):** `creado` (default al crear, nadie puede registrar todavía) → `en_proceso` (lo activa manualmente coordinador+ con el botón "Iniciar evento" — es el ÚNICO estado en el que `digitador`/`cliente` pueden entrar a `/kiosk/{id}`, ver `get_event_for_staff`) → `finalizado` (botón "Finalizar evento", coordinador+; cierra el evento). `admin`+ puede "Reabrir" un evento `finalizado` de vuelta a `en_proceso` como corrección. `PATCH /api/events/{id}` valida que `status` sea uno de los tres valores. Eliminar un evento (`DELETE`, admin+) ahora muestra un `showConfirm` mencionando el estado actual antes de borrar.
- `EventStaffAuthorization(event_id, staff_user_id, authorized_by_id)` — qué cuenta de staff puede operar en qué evento. **Ya se aplica en la práctica**: `app/auth.get_event_for_staff()` la exige para `digitador` (403 si no está autorizado, o si el evento ya está `cerrado`) en `/kiosk/{event_id}` y en cada endpoint de `/api` que recibe `event_id`. `coordinador`/`admin`/`super_admin` no la necesitan (alcance global sobre todos los tenants/eventos).

### Roles y permisos (`app/auth.py`)
`STAFF_ROLES` (`models.py`) = `("cliente", "digitador", "coordinador", "admin", "super_admin")`. `require_role("x")` exige ese nivel de jerarquía o superior — **pero `cliente` NO es realmente parte de esta jerarquía**, solo ocupa el nivel más bajo numéricamente para que `require_role("digitador")` lo excluya automáticamente de recognize/register (que es lo único que importa: un cliente jamás debe poder registrar/reconocer). Para todo lo que SÍ necesita ver (directorio, su propia lista de eventos) los endpoints usan `get_current_staff` en vez de `require_role`, precisamente para no quedar atados a esa jerarquía — ver `/api/users` y `/api/my-events` en `routers/api.py` y `routers/events.py`.

| Acción | Requisito |
|---|---|
| Reconocer / registrar persona en SU evento autorizado (`/api/recognize`, `/api/register`) | rol `digitador` o superior |
| Ver directorio en vivo de un evento (`GET /api/users`), ver "mis eventos" (`GET /api/my-events`) | cualquier staff autenticado con autorización a ese evento (incluye `cliente` y `digitador`) |
| Editar perfil, carga masiva, descargar reporte, crear/editar cliente y evento, crear/quitar usuarios temporales (digitador) de un evento | rol `coordinador` o superior |
| Borrado permanente (logs de un usuario, eliminar evento/cliente), crear/desactivar cuentas `coordinador`/`cliente`, reautorizar un digitador o cliente existente para otro evento | rol `admin` o superior |
| Crear cuentas `admin` | `super_admin` (único caso que no es "jerarquía", hardcodeado en `routers/staff.py`) |

**Fix (2026-09-16): un Super Admin podía desactivarse a sí mismo** (o a otro Super Admin) desde `/admin/staff` — como esa tabla se muestra sin filtrar para `super_admin`, se ve a sí mismo en la lista, y `PATCH /staff/{id}/deactivate` no tenía ningún chequeo de auto-desactivación ni de "nunca desactivar un super_admin". Corregido: un `super_admin` nunca puede desactivarse vía ese endpoint, y nadie puede desactivar su propia cuenta. La UI (`staff.html`) también oculta los botones de Desactivar/Borrar en la propia fila y en cualquier fila `super_admin`. Si esto ya te pasó y quedaste sin poder entrar, se arregla directo en la base (no hay otra forma, por definición no puedes loguearte para usar el botón de reactivar): `UPDATE staff_users SET is_active = true WHERE username = '<tu_usuario>';`.

**Borrado permanente de cuentas de staff (2026-09-16):** `DELETE /api/staff/{id}` (distinto de `/deactivate`, que solo desactiva) — cada rol solo borra lo que tiene directamente debajo, tabla `DELETABLE_ROLES_BY` en `routers/staff.py`: `coordinador` → solo `digitador`; `admin` → `coordinador`/`digitador`/`cliente`; `super_admin` → `admin`/`coordinador`/`digitador`/`cliente`. Nadie puede borrarse a sí mismo. No borra en cascada `Event`/`AccessLog` (son datos de negocio reales) — las referencias a la cuenta borrada quedan en `NULL`, solo se borran las filas de `EventStaffAuthorization` propias (esas sí pierden sentido sin la cuenta). UI: botón "Borrar permanente" en `/admin/staff` y en la pestaña "Usuarios Temporales" del kiosko.

**Usuario `cliente` (2026-09-16, ajustado 2026-09-17):** al igual que `digitador`, se crea y se autoriza **desde dentro de un evento** (pestaña "Usuarios del Evento" en `/kiosk/{event_id}`, `POST /api/events/{id}/staff-users` con `role=cliente`) — NO desde `/admin/staff` (ese formulario solo crea `coordinador`, y `super_admin` además `admin`). La diferencia con `digitador`: crear una cuenta `cliente` exige `admin`+ (un `coordinador` solo puede crear `digitador` ahí mismo). Asignar una cuenta `cliente`/`digitador` YA EXISTENTE a otro evento también se hace desde esa misma pestaña ("Asignar cuenta ya existente", `admin`+, `POST .../staff-users/assign-existing`) — el viejo `POST/DELETE /staff/{id}/authorize-event/{id}` en `routers/staff.py` se quitó, quedó reemplazado por esto. Al loguearse con exactamente un evento activo autorizado, `cliente` entra derecho a `/kiosk/{event_id}` igual que `digitador`, pero ahí solo ve dos pestañas: **Estadísticas** (placeholder, todavía sin diseñar/mockeado) y **Directorio en Vivo**.

**Usuarios temporales (digitador) — flujo real (2026-09-16):** ya NO se crean desde `/admin/staff` (esa opción se quitó del formulario a propósito). Se crean desde dentro del evento (`/kiosk/{event_id}`, pestaña "Usuarios Temporales", visible para `coordinador`+), vía `POST /api/events/{event_id}/temp-users` — crea el `StaffUser` y la `EventStaffAuthorization` en la misma transacción, así que quedan asociados al evento desde el primer momento, nunca "sueltos". `/admin/staff` conserva un formulario aparte para **reautorizar** (no crear) un digitador ya existente en un evento distinto — eso sigue siendo `admin`+.

### Multi-tenant: ahora sí explotado
Ya no hay `CURRENT_TENANT` hardcodeado en ningún router. El tenant de cada operación se resuelve siempre a partir del `Event` (`event.tenant_id`), y los tenants se crean/administran de verdad desde `/` (coordinador+) vía `/api/tenants`.

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
- ~~Sin autenticación~~ **Resuelto (2026-09-14):** login + 4 roles. ~~Sin conectar EventStaffAuthorization~~ **Resuelto (2026-09-15):** ver `get_event_for_staff` y sección Navegación. Sigue faltando: CSRF explícito (mitigado parcial por `SameSite=Lax`), rate limiting de intentos de login, y una UI de "olvidé mi contraseña" (hoy solo un admin puede resetear, manualmente).
- **Sin tests.** No hay carpeta `tests/` ni configuración de pytest.
- ~~Sin migraciones~~ **Resuelto (2026-09-14):** Alembic (ver sección Migraciones abajo). `Base.metadata.create_all` ya no se llama desde `main.py`.
- ~~Sin CI/CD~~ **Resuelto (2026-09-14):** `.github/workflows/deploy.yml` corre en un runner self-hosted instalado directo en la VM (`golden-biometrics-prod`). Se eligió self-hosted y no SSH-desde-GitHub porque el proyecto tiene **OS Login activado** en GCP, que bloquea el acceso SSH por llave externa — el runner evita ese problema porque corre dentro de la VM, no entra desde afuera. En cada push a `main`: instala deps, `alembic upgrade head`, `systemctl restart facial-recognition`. También soporta disparo manual (`workflow_dispatch`).
  - **Nota de seguridad:** el repo es público. El workflow solo se dispara con `push` a `main` (requiere permiso de escritura al repo), nunca con `pull_request`, así que un PR externo no puede ejecutar código en el runner de producción. Si en algún momento se agrega un trigger de `pull_request` o `pull_request_target`, hay que exigir aprobación manual para colaboradores externos.
- ~~Multi-tenant no explotado~~ **Resuelto (2026-09-15)** (ver arriba).
- **`bulk_register` no valida CSV/ZIP de forma robusta**: `except: pass` silencioso al procesar imágenes del zip (`api.py`), puede ocultar errores reales de registros que no se cargaron. Tampoco pide `event_id` desde la UI del formulario CSV todavía más allá de lo ya cableado en `app.js`.
- **README ausente** — no hay instrucciones de instalación/arranque para alguien nuevo en el proyecto.
- **`requirements.txt` sin versiones fijadas** — riesgo de que una actualización de `face_recognition`/`dlib` rompa el build en un entorno nuevo.
- **Sin roles/permisos granulares por usuario individual** — 4 roles fijos en código a propósito (más simple; no hay todavía un catálogo real de "acciones" del sistema grande para armar un checklist granular).
- **Sin edición/eliminación de `StaffUser` más allá de activar/desactivar** — no hay endpoint para cambiar contraseña de otra cuenta o editar su rol una vez creada; hay que desactivarla y crear una nueva si algo queda mal.
- **Pendiente (siguiente push en esta misma rama): archivos adjuntos por evento, cifrados en la base de datos.** Pedido explícito del usuario — subir varios archivos (xlsx/pdf/docx/txt/imágenes) asociados a un evento, guardados cifrados, descargables después por cualquier usuario con acceso al evento. Todavía no implementado. Decisión pendiente de documentar cuando se haga: esquema de cifrado (probable: `cryptography.Fernet` con una `FILE_ENCRYPTION_KEY` nueva en `.env`, cifrado simétrico servidor-side — no hay pedido de cifrado end-to-end donde el servidor no pueda leer el archivo).
- ~~Selector de hora tipo reloj~~ **Resuelto (2026-09-17), bug de selección arreglado el mismo día:** `static/js/clockpicker.js`, widget custom (SVG, sin dependencias externas) — reemplaza el `<input type="time">` nativo en los 4 campos de hora del formulario de evento. `attachClockPicker(input)` sobre un `<input type="text" readonly>`. **Bug real que tuvo:** al hacer clic en un número, `renderFace()` reconstruye el `<svg>` (`innerHTML = ""` + nuevos nodos), lo que **desprende del DOM** al `<circle>` que originó el clic; cuando ese click sigue burbujeando hasta el listener de "cerrar si el clic fue afuera" (en `document`), `popupEl.contains(e.target)` da `false` porque el nodo ya no está en el árbol — y el popup se cierra solo, sin registrar la hora. Se arregló con `e.stopPropagation()` en los círculos (y en el contenedor del popup, como refuerzo). **Lección para cualquier otro widget con popup + reconstrucción de DOM en este proyecto: nunca mutar el subárbol que contiene `e.target` antes de que el evento termine de burbujear — cortar la propagación primero.**
- ~~Ciudades por país~~ **Resuelto de verdad (2026-09-17):** ya no es una lista escrita a mano — `app/cities_by_country.json` (~20,300 ciudades) se generó una sola vez offline desde el dataset público de GeoNames (`cities15000.txt`, CC BY 4.0, ciudades con población ≥15,000 en todo el mundo), filtrado a los ~36 países que soporta el formulario y ordenado por población. `app/cities_data.py` solo carga ese JSON al arrancar; `GET /api/cities?country=X` (en `routers/events.py`) devuelve las primeras 300 (para no mandar un `<datalist>` gigante al navegador en países con miles de ciudades) — Ciudad sigue aceptando texto libre para lo que quede fuera de esas 300. Si se necesita regenerar o ampliar el dataset (otro corte de población, más países), el proceso fue: descargar `cities15000.zip` y `countryInfo.txt` de `download.geonames.org/export/dump/`, y correr un script Python que mapea ISO2→nombre en español y arma el JSON — no quedó versionado el script en el repo, solo el resultado.
- **Corregido (2026-09-16): el formulario de "Nuevo evento" en el dashboard caía a un envío nativo del navegador (recarga con los datos en la URL) en vez de pasar por `fetch`.** La causa más probable era depender de atributos `onsubmit`/`onclick` inline sobre HTML inyectado dinámicamente vía `innerHTML`. Se migró todo `templates/dashboard.html` a **delegación de eventos** (un único listener en el contenedor estable `#tenantsList`, usando atributos `data-action`/`data-*` en vez de `onsubmit`/`onclick` inline) — es el patrón a seguir para cualquier HTML generado dinámicamente en este proyecto de ahora en adelante, no volver a usar `onsubmit="fn(...)"` inline sobre contenido inyectado por JS.
- **Backup solo local** (`~/backups` en la VM, cron diario, rotación 7 días vía `pg_dump`). Backup offsite (bucket GCS) no está armado.
- **Monorepo:** el repo hoy sigue siendo solo este módulo en la raíz. Ya se decidió la estrategia (monorepo, `apps/<módulo>/`) pero la reestructuración física todavía no se ejecutó — es la próxima rama.

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
