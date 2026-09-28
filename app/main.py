import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import anyio.to_thread
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError as PoolTimeoutError
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import appmode, bulk_jobs, faces, jobs, obs, ops
from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.routers import api, areas_inventory, auth as auth_router, badges, calendar as calendar_router, cedula, certificates_public, analytics, digital_public, form_payments, form_refunds, forms, forms_public, ops as ops_router, roulette, event_docs, event_report, events, legal_public, parametros, privacy as privacy_router, signatures, staff, stats, super_events, tenants, uploads as uploads_router
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff

obs.configure_logging()       # logs en JSON a stdout (formato de Cloud Logging), con datos personales enmascarados
log = logging.getLogger("golden.app")

IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"
SECRET_KEY = os.getenv("SECRET_KEY")
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definida. Requerida en producción para firmar la sesión.")


class StaticFilesNoCacheInDev(StaticFiles):
    """El navegador cacheaba static/js/*.js entre reinicios de uvicorn --reload mientras
    íbamos cambiando app.js, causando bugs fantasma (el código viejo seguía corriendo aunque
    el archivo en disco ya tuviera el fix). En development desactiva el caché del navegador
    para /static/*; en producción se comporta como StaticFiles normal (sí cachea)."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if not IS_PRODUCTION:
            response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Arranque y apagado ordenado. Al recibir SIGTERM (Cloud Run da ~10 s) uvicorn/gunicorn dejan de aceptar peticiones y terminan las que están en curso;
    aquí, además, se detiene el worker de la cola (termina el trabajo actual, no toma más) y las cargas masivas a medias se marcan como interrumpidas."""
    # Hilos para los endpoints síncronos: tantos como conexiones puede abrir el pool de la base (más los cálculos faciales pendientes). Con más, los hilos
    # sobrantes solo esperarían una conexión libre (y acabarían en 503 tras DB_POOL_TIMEOUT); con menos, la base quedaría subutilizada.
    default_threads = int(os.getenv("DB_POOL_SIZE", "10")) + int(os.getenv("DB_MAX_OVERFLOW", "10")) + faces.FACE_CONCURRENCY
    anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.getenv("THREADPOOL_SIZE", default_threads))
    worker = None
    if os.getenv("JOBS_WORKER", "on") != "off" and not jobs.uses_cloud_tasks():
        worker = jobs.Worker()
        worker.start()
    if appmode.loads_model():
        await asyncio.get_running_loop().run_in_executor(None, ops.model_ready)        # precalienta dlib (en los procesos hijo): el primer escaneo no paga la carga del modelo
    log.info("aplicación lista (modo %s)", appmode.MODE)
    yield
    log.info("apagando: deteniendo trabajos en segundo plano")
    if worker:
        worker.stop()
    faces.shutdown()
    interrupted = bulk_jobs.mark_interrupted()
    if interrupted:
        log.warning("%s carga(s) masiva(s) marcadas como interrumpidas por el apagado", interrupted)


app = FastAPI(
    lifespan=lifespan,
    title="Golden Biometrics SaaS",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_WHEN_MUST_CHANGE = ("/cambiar-contrasena", "/logout", "/static/", "/login")


@app.middleware("http")
async def csrf_and_password_gate(request, call_next):
    """(1) CSRF (Sprint 4): además de la cookie SameSite=Lax, toda petición que cambia estado y trae `Origin`
    debe venir del MISMO sitio; una página de otro dominio no puede hacer que el navegador de un usuario con
    sesión modifique datos. Sin `Origin` (curl, pruebas, apps) no se rechaza: no es un navegador. La
    comparación usa el Host que reenvía Nginx/Cloudflare. (2) Quien entró con una contraseña temporal
    (`must_change_password`) no puede usar nada más hasta cambiarla."""
    if request.method in _MUTATING:
        origin = request.headers.get("origin")
        if origin and origin != "null":
            allowed = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
            public = os.getenv("PUBLIC_BASE_URL")
            if public:
                allowed.add(urlsplit(public).netloc)
            if urlsplit(origin).netloc not in allowed:
                return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
        elif origin == "null":
            return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
    if request.scope.get("session") and request.session.get("must_change_password") and not request.url.path.startswith(_ALLOWED_WHEN_MUST_CHANGE):
        if request.method == "GET" and "text/html" in request.headers.get("accept", "text/html"):
            return RedirectResponse("/cambiar-contrasena", status_code=302)
        return JSONResponse({"detail": "Debes cambiar tu contraseña antes de continuar"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_cache_html(request, call_next):
    """Las páginas HTML dependen del estado del evento (menú del evento con Áreas/Inventario/
    Certificados según lo activado en Parámetros, etc.) — sin esto, volver con "Atrás" mostraba la
    copia vieja hasta refrescar a mano (bug real, 2026-09-23)."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"     # salvo que la ruta lo haya decidido (el cascarón del formulario público se guarda unos segundos)
    return response


# La sesión se registra DESPUÉS de los middlewares de arriba a propósito: en Starlette el último registrado es el
# más externo, y csrf_and_password_gate necesita leer `request.session` ya cargada.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production",
    same_site="lax",
    https_only=IS_PRODUCTION,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)          # el directorio de miles de personas baja de ~2 MB a ~150 KB
app.add_middleware(obs.RequestLogMiddleware, on_5xx=ops.record_5xx)     # el más externo: mide y registra TODA petición (incluidos los errores)

app.mount("/static", StaticFilesNoCacheInDev(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


from app import staticver  # noqa: E402

staticver.install(templates)
templates.env.filters["fromjson"] = json.loads

DEFAULT_LOGO_URL = os.getenv("DEFAULT_LOGO_URL", "https://www.goldenlogisticas.com/wp-content/uploads/2025/07/logo-golden-con-letras-1.png")


def event_logo_url(event):
    """URL del logo del header para las páginas de un evento (ítem 1, reunión 2026-09-21): el de
    Golden por defecto, ninguno si se ocultó, o el propio del evento. Vacío = no dibujar <img>."""
    mode = getattr(event, "logo_mode", "default")
    if mode == "hidden":
        return ""
    if mode == "custom" and event.logo_path:
        return f"/api/events/{event.id}/logo"
    return DEFAULT_LOGO_URL


def event_logo_attrs(event):
    """Atributos del <img> del logo propio: alto elegido (30–80 px; el header mide 80) y, en modo «banner», que rellene el ancho disponible
    del header (recortando lo que sobre). El logo de Golden por defecto no se toca."""
    from markupsafe import Markup
    if getattr(event, "logo_mode", "default") != "custom" or not event.logo_path:
        return Markup("")
    height = max(30, min(80, int(getattr(event, "logo_height", None) or 50)))
    if getattr(event, "logo_fit", "logo") == "banner":
        return Markup(f'style="height:{height}px; width:100%; object-fit:cover;" data-banner="1"')
    return Markup(f'style="height:{height}px;"')


templates.env.globals["event_logo_url"] = event_logo_url
templates.env.globals["event_logo_attrs"] = event_logo_attrs


def _include(router, prefix: str = "") -> None:
    """`app.include_router` que respeta APP_MODE: en un modo que no es `all` solo incluye las rutas de ESE servicio (ver app/appmode.py)."""
    if appmode.MODE != "all":
        keep = APIRouter()
        keep.routes.extend(r for r in router.routes if appmode.route_allowed(prefix + getattr(r, "path", "")))
        router = keep
    app.include_router(router, prefix=prefix)

_include(auth_router.router)
_include(api.router, prefix="/api")
_include(events.router, prefix="/api")
_include(staff.router, prefix="/api")
_include(tenants.router, prefix="/api")
_include(badges.router, prefix="/api")
_include(cedula.router, prefix="/api")
_include(stats.router, prefix="/api")
_include(parametros.router, prefix="/api")
_include(privacy_router.router, prefix="/api")
_include(legal_public.router)      # /privacidad, /terminos, /reembolsos (públicas)
_include(event_report.router, prefix="/api")
_include(event_docs.router, prefix="/api")
_include(uploads_router.router, prefix="/api")   # subida directa al almacenamiento (archivos grandes)
_include(super_events.router, prefix="/api")
_include(areas_inventory.router, prefix="/api")
_include(analytics.router, prefix="/api")
_include(forms.router, prefix="/api")
_include(form_refunds.router, prefix="/api")   # reembolsos de pagos (admin+)
_include(forms_public.router)  # /f/<evento>/<formulario>, público (sin login) a propósito
_include(form_payments.router)  # cotización y confirmación del pago Wompi + webhook (público: Wompi no tiene sesión)
_include(roulette.router, prefix="/api")
_include(roulette.public_router)  # /r/<token>, pantalla del proyector (sin login)
_include(certificates_public.router)  # /c/<token>, público (sin login) a propósito
_include(certificates_public.staff_router, prefix="/api")
_include(digital_public.router)  # /b/<token>, público (sin login) a propósito
_include(signatures.router, prefix="/api")
_include(calendar_router.router, prefix="/api")
_include(ops_router.router)          # /healthz, /readyz, /api/ops/*
_include(ops_router.pages)           # /sistema


def _page_staff(request: Request, db: Session):
    """Trae el StaffUser real de la sesión (no solo el string de rol). None si no hay sesión válida."""
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        return None
    return db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()


def _display_role(role: str, secondary_role: str = None) -> str:
    """Rol a mostrarle a los templates Jinja (Fase 15, 2026-09-17, doble rol coordinador+
    comercial) — muchísimos templates deciden qué mostrar/ocultar comparando `staff_role` contra
    un solo string (ej. kiosk_select.html: `{% if staff_role != "comercial" %}` para ocultar
    Escarapelas/Adjuntar BD/Parámetros a comercial). Reescribir cada uno de esos checks para que
    entienda un rol secundario sería un cambio mucho más grande que el pedido; en vez de eso, acá
    se decide UNA sola etiqueta a mostrar: si la persona es coordinador Y comercial (en cualquier
    orden), se le muestra como 'coordinador' — el rol estrictamente menos restringido de los dos
    en toda la UI existente — así hereda visualmente todo lo que un coordinador ve, sin tener que
    tocar cada template. La distinción real de permisos (crear tenant/evento, reasignar comercial,
    etc.) ya se resuelve en el backend vía auth.effective_roles(), esto es solo para la UI."""
    roles = {role} | ({secondary_role} if secondary_role else set())
    if {"coordinador", "comercial"} <= roles:
        return "coordinador"
    return role


def _require_page_role(request: Request, minimum_role: str):
    """Para páginas simples que solo necesitan el rol (no el objeto completo): sin sesión -> /login;
    sin permiso suficiente -> /. Considera el rol secundario (Fase 15, doble rol coordinador+
    comercial) guardado en sesión al loguearse — sin esto, alguien coordinador+comercial cuyo rol
    PRIMARIO es 'coordinador' quedaría bloqueado de páginas que piden 'comercial' como mínimo
    (ej. /clientes/{id}/nuevo-evento), aunque también sea comercial de verdad."""
    role = request.session.get("staff_role")
    if not role:
        return RedirectResponse("/login", status_code=302)
    secondary_role = request.session.get("staff_secondary_role")
    roles = [role] + ([secondary_role] if secondary_role else [])
    if max(ROLE_HIERARCHY[r] for r in roles) < ROLE_HIERARCHY[minimum_role]:
        return RedirectResponse("/", status_code=302)
    return None


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)

    if staff_user.role in ("digitador", "cliente"):
        # Ninguno de los dos tiene panel: si tiene exactamente un evento activo autorizado,
        # entra derecho ahí. Con 0 o >1 se le muestra la lista mínima (dashboard.html la maneja).
        authorized_events = (
            db.query(Event)
            .join(EventStaffAuthorization, EventStaffAuthorization.event_id == Event.id)
            .filter(EventStaffAuthorization.staff_user_id == staff_user.id, Event.status == "en_proceso")
            .all()
        )
        if len(authorized_events) == 1:
            return RedirectResponse(f"/kiosk/{authorized_events[0].id}", status_code=302)

        return templates.TemplateResponse(request=request, name="dashboard.html", context={
            "staff_name": staff_user.full_name or staff_user.username,
            "staff_role": _display_role(staff_user.role, staff_user.secondary_role),
        })

    # coordinador/admin/super_admin (Sprint 2.3, 2026-09-16): el panel combinado (árbol
    # Cliente→Eventos) se partió en secciones del menú lateral nuevo — Clientes es el punto de
    # entrada por defecto ahora, ver templates/clientes.html.
    return RedirectResponse("/clientes", status_code=302)


@app.get("/clientes")
def clientes_page(request: Request):
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="clientes.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "sidebar_active": "clientes",
    })


@app.get("/clientes/{tenant_id}/nuevo-evento")
def nuevo_evento_page(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    """Sprint 2.4 Fase 1 (2026-09-16, pedido explícito): "Crear evento" pasa a ser una pantalla
    dedicada en vez del formulario inline que aparecía bajo el cliente expandido en /clientes —
    mismo formulario/JS de siempre (createEvent), reubicado. comercial+ solamente, mismo mínimo
    que POST /api/events."""
    redirect = _require_page_role(request, "comercial")
    if redirect:
        return redirect
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return RedirectResponse("/clientes", status_code=302)
    return templates.TemplateResponse(request=request, name="nuevo_evento.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "staff_id": request.session.get("staff_user_id"),
        "sidebar_active": "clientes",
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
    })


@app.get("/eventos")
def eventos_page(request: Request):
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="eventos.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "staff_id": request.session.get("staff_user_id"),
        "sidebar_active": "eventos",
    })


@app.get("/calendario")
def calendario_page(request: Request):
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="calendario.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "staff_id": request.session.get("staff_user_id"),
        "sidebar_active": "calendario",
    })


@app.get("/configuracion")
def configuracion_page(request: Request):
    """Apariencia (color/tipografía, ver static/js/theme.js — preferencia local del navegador, NO
    vive en la base de datos) está disponible para CUALQUIER staff autenticado (Sprint 2.4,
    ronda 2, pedido explícito: "por computador" aplica a todos, no solo admin). La pestaña
    "Staff y Permisos" (gestión real de cuentas) sigue oculta para no-admin dentro del propio
    template — eso sí sigue siendo admin+ solamente."""
    redirect = _require_page_role(request, "cliente")  # cliente = el mínimo de STAFF_ROLES, o sea "cualquiera logueado"
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="configuracion.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "sidebar_active": "configuracion",
    })


@app.get("/kiosk/{event_id}")
def kiosk_entry(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Punto de entrada al evento. 'cliente' no registra nada (solo ve estadísticas/directorio),
    así que va directo a kiosk_registro.html. Todos los demás roles eligen primero entre Registro
    (unificado, ver /kiosk/{event_id}/registro) y Adjuntar Base de Datos — varios operadores
    pueden convivir en el mismo evento (unos con cámara, otros solo con lector de cédula), cada
    quien entra a Registro y ve lo que corresponda según Event.facial_enabled."""
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    try:
        event = get_event_for_staff(event_id, db, staff_user)
    except HTTPException:
        return RedirectResponse("/", status_code=302)

    if staff_user.role == "cliente":
        # Antes esto era un TemplateResponse manual, sin pasar por _resolve_kiosk_page — le
        # faltaban field_configs_json/optional_labels_json (agregados con Parámetros del Evento),
        # lo que rompía el <script> de kiosk_registro.html (JS inválido) para cualquier cliente
        # que cayera acá vía el auto-redirect desde "/" con un solo evento autorizado. Bug real,
        # encontrado en Sprint 2.3, no reportado por el usuario.
        return _resolve_kiosk_page(event_id, request, db, "kiosk_registro.html")

    return templates.TemplateResponse(request=request, name="kiosk_select.html", context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": _display_role(staff_user.role, staff_user.secondary_role),
        "event": event,
        "sidebar_active": "eventos",
    })


def _resolve_kiosk_page(event_id: int, request: Request, db: Session, template_name: str, min_role: str = None, extra_context: dict = None, exclude_roles: list = None):
    """Boilerplate compartido por cada método de registro: mismo chequeo de acceso
    (get_event_for_staff), mismo contexto de template. Cada método solo elige su propio
    template_name. `min_role` es un segundo chequeo opcional para páginas que además exigen un
    rol mínimo más allá del acceso al evento (ej. la carga de base es coordinador+, mismo mínimo
    que ya exigía POST /api/bulk_register — bug real encontrado en testing, SELECT-03 2026-09-21:
    la página GET no tenía este chequeo, un digitador podía abrirla directo por URL aunque el
    botón de submit le fallara con 403)."""
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    try:
        event = get_event_for_staff(event_id, db, staff_user)
    except HTTPException:
        return RedirectResponse("/", status_code=302)
    # effective_roles (Fase 15, 2026-09-17): considera el rol secundario si tiene uno (doble rol
    # coordinador+comercial) — tanto para el mínimo jerárquico como para exclude_roles abajo.
    staff_roles = effective_roles(staff_user)
    if min_role and max(ROLE_HIERARCHY[r] for r in staff_roles) < ROLE_HIERARCHY[min_role]:
        return RedirectResponse(f"/kiosk/{event_id}", status_code=302)
    # exclude_roles (2026-09-16): para vistas que NO siguen la jerarquía de min_role — ej.
    # Estadísticas la puede ver 'cliente' (que en STAFF_ROLES queda por debajo de 'digitador')
    # pero NO 'digitador'; un simple mínimo jerárquico no puede expresar eso. Con doble rol, solo
    # excluye si TODOS sus roles efectivos están en exclude_roles (mismo criterio que
    # require_role_excluding en auth.py) — coordinador+comercial no queda excluido de Escarapelas/
    # Adjuntar BD/Parámetros, porque también es coordinador de verdad.
    if exclude_roles and staff_roles.issubset(set(exclude_roles)):
        return RedirectResponse(f"/kiosk/{event_id}", status_code=302)
    # Lista (clave, rótulo) ordenada numéricamente (no alfabéticamente — "opcional_10" antes que
    # "opcional_2" si se ordenara como texto) de los campos opcionales que este evento ya tiene
    # nombrados — usada por kiosk_registro.html para mostrar esos campos en el alta manual con su
    # nombre real en vez de "Opcional N" (2026-09-22).
    optional_labels = sorted(event.get_optional_labels().items(), key=lambda kv: int(kv[0].split("_")[1]))
    # Versión ya serializada a JSON, lista para inyectar en un <script> con `| safe` (Jinja2Templates
    # de Starlette no trae el filtro `tojson` de Flask) — el `.replace` evita que una etiqueta se
    # rompa si algún rótulo llegara a contener literalmente "</script>" (2026-09-15, Sprint 2: lo
    # necesita badge_editor.html para poblar el selector de variables con los opcionales reales).
    optional_labels_json = json.dumps(optional_labels).replace("</", "<\\/")
    # Parámetros del Evento (2026-09-16): config real (o default) de cada campo configurable de
    # este evento, calculado acá mismo (no vía fetch aparte) para que el alta manual/edición y el
    # cálculo de estadísticas por defecto lo tengan disponible sin un viaje de red extra — mismo
    # patrón que optional_labels_json arriba.
    field_configs = parametros.field_configs_for_event(db, event)
    field_configs_json = json.dumps(field_configs).replace("</", "<\\/")
    context = {
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": _display_role(staff_user.role, staff_user.secondary_role),
        "event": event,
        "optional_labels": optional_labels,
        "optional_labels_json": optional_labels_json,
        "field_configs": field_configs,
        "field_configs_json": field_configs_json,
        "field_labels": {cfg["key"]: cfg["label"] for cfg in field_configs},
        "sidebar_active": "eventos",
    }
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(request=request, name=template_name, context=context)


@app.get("/kiosk/{event_id}/registro")
def kiosk_registro(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Pantalla única de registro (2026-09-21, reemplaza los antiguos /facial y /cedula
    separados) — un solo Directorio en Vivo con búsqueda por cédula/nombre/entidad, y el escáner
    de cámara aparece o no según `event.facial_enabled` (se enciende solo al subir un roster con
    fotos, ver bulk_register). Se dejaron de exponer dos "métodos" distintos porque ambos
    compartían exactamente el mismo directorio y la diferencia real era una sola cosa: si hay
    fotos cargadas o no."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_registro.html")


@app.get("/kiosk/{event_id}/facial")
@app.get("/kiosk/{event_id}/cedula")
def kiosk_registro_legacy_redirect(event_id: int):
    """Rutas viejas (antes de la unificación Facial/Cédula) — quien tenga un enlace guardado cae
    igual a la pantalla de Registro unificada en vez de un 404."""
    return RedirectResponse(f"/kiosk/{event_id}/registro", status_code=302)


@app.get("/kiosk/{event_id}/roster")
def kiosk_roster(event_id: int, request: Request, db: Session = Depends(get_db)):
    # exclude_roles (Sprint 2.4 Fase 6, 2026-09-16, pedido explícito): 'comercial' queda por
    # ENCIMA de 'coordinador' en STAFF_ROLES (hereda su acceso operativo por diseño, Fase 0), pero
    # explícitamente NO debe ver "Adjuntar Base de Datos" — un min_role jerárquico no alcanza para
    # excluir un rol que está por encima del mínimo.
    return _resolve_kiosk_page(event_id, request, db, "kiosk_roster.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/usuarios")
def kiosk_usuarios(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Gestión de cuentas digitador/cliente de este evento (Sprint 2.2 Fase B, 2026-09-16) — antes
    vivía como pestaña "Usuarios del Evento" dentro de /kiosk/{event_id}/registro; se mueve a su
    propia ruta, mismo patrón que "Escarapelas"/"Adjuntar Base de Datos". Mismo mínimo de rol que
    antes (coordinador+ para crear digitador, admin+ dentro del template para cliente/asignar)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_usuarios.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/estadisticas")
def kiosk_estadisticas(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Reporte + gráficos del evento (Sprint 2.2 Fase B, 2026-09-16) — antes vivía como pestaña
    "Exportar Reporte" dentro de /kiosk/{event_id}/registro; se mueve a su propia ruta.
    Habilitado también para 'cliente' (2026-09-16, pedido explícito: el cliente asignado a un
    evento debe poder ver sus estadísticas) — 'digitador' sigue sin acceso, igual que antes con
    "Exportar Reporte" (no le corresponde ver reportes, solo operar el registro). No se puede
    expresar con min_role (jerárquico): 'cliente' queda por debajo de 'digitador' en STAFF_ROLES,
    así que se excluye a 'digitador' explícitamente en vez de exigir un mínimo.
    `?embed=1` (2026-09-16): la pestaña "Estadísticas" de `cliente` en /kiosk/{event_id}/registro
    la incrusta en un <iframe> para poder alternar con "Directorio en Vivo" sin salir de la
    página — en ese modo se omite el header/franja de contexto propios (ya los tiene la página
    que la contiene) y solo se ve el contenido real."""
    embed = request.query_params.get("embed") == "1"
    return _resolve_kiosk_page(event_id, request, db, "kiosk_estadisticas.html", exclude_roles=["digitador"], extra_context={"embed": embed})


@app.get("/kiosk/{event_id}/parametros")
def kiosk_parametros(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Parámetros del Evento (Sprint 2.2, 2026-09-16, pedido explícito) — coordinador+ define por
    campo si es obligatorio, qué tipo de control usar y si debe generar estadística sola al
    entrar a Estadísticas. Mismo mínimo de rol que Adjuntar Base de Datos/Usuarios del Evento.
    'comercial' excluido explícitamente (Sprint 2.4 Fase 6, 2026-09-16, pedido explícito) — queda
    por ENCIMA de 'coordinador' en STAFF_ROLES, así que min_role solo no alcanza para bloquearlo."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_parametros.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/documentos")
def kiosk_documents(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Documentos del Evento (reunión 2026-09-21, ítem 8) — coordinador+ (comercial incluida)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_documentos.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/ruleta")
def kiosk_roulette(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Ruleta — configuración de comportamiento y ejecución (Sprint 5) — coordinador+."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_ruleta.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/ruleta/visual")
def kiosk_roulette_visual(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Ruleta — configuración visual (fuente, colores, imagen, fondo) — coordinador+."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_ruleta_visual.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/formularios")
def kiosk_forms(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Formularios Web del evento — listado (Sprint 5) — coordinador+."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_formularios.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/formularios/{form_id}")
def kiosk_form_editor(event_id: int, form_id: int, request: Request, db: Session = Depends(get_db)):
    """Editor de un formulario web (diseño, campos, estados, respuestas, analítica) — coordinador+."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_formulario_editor.html", min_role="coordinador", extra_context={"form_id": form_id})


@app.get("/kiosk/{event_id}/legalizaciones")
def kiosk_expenses(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Legalizaciones / gastos del evento (reunión 2026-09-21, ítem 7) — coordinador+ (comercial incluida)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_legalizaciones.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/escarapela")
def kiosk_badge_editor(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Editor visual de la escarapela del evento (Sprint 2, Épico 2) — mismo mínimo de rol que
    Adjuntar Base de Datos (coordinador+); la impresión en sí (no el diseño) se dispara desde
    /kiosk/{event_id}/registro, disponible para digitador+. 'comercial' excluido explícitamente
    (Sprint 2.4 Fase 6) — no debe diseñar NI imprimir escarapelas."""
    return _resolve_kiosk_page(event_id, request, db, "badge_editor.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/areas")
def kiosk_areas(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Control de Áreas (ítem 9a): entrada/salida por zona. digitador+ (comercial excluida)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_areas.html", min_role="digitador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/inventario")
def kiosk_inventory(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Control de Inventario (ítem 9b): entrega de ítems/combos. digitador+ (comercial excluida)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_inventario.html", min_role="digitador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/certificado")
def kiosk_certificate_editor(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Diseñador del certificado (reunión 2026-09-21, ítem 5): el MISMO editor de escarapelas, en modo
    certificado (A4 horizontal). Solo si el módulo está activado en Parámetros; comercial excluida."""
    return _resolve_kiosk_page(event_id, request, db, "badge_editor.html", min_role="coordinador", exclude_roles=["comercial"], extra_context={"template_kind": "certificate"})


@app.get("/kiosk/{event_id}/certificados")
def kiosk_certificates(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Sección Certificados (ítem 5): con el evento Finalizado, genera el ZIP de PDFs."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_certificados.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/escarapela/imprimir/{user_id}")
def kiosk_badge_print(event_id: int, user_id: str, request: Request, db: Session = Depends(get_db)):
    """Vista de SOLO la escarapela de una persona, a tamaño real (mm), para imprimir — se abre en
    una pestaña/ventana aparte desde el botón "Imprimir Escarapela" (o sola, si el evento tiene
    auto_print_badge activo) sin sacar al digitador de la pantalla de Registro. 'comercial'
    excluido explícitamente (Sprint 2.4 Fase 6, pedido explícito: "la comercial no debe poder
    imprimir")."""
    return _resolve_kiosk_page(event_id, request, db, "badge_print.html", exclude_roles=["comercial"], extra_context={
        "print_user_id": user_id,
        "print_user_id_json": json.dumps(user_id).replace("</", "<\\/"),
    })


@app.get("/admin/staff")
def staff_page(request: Request):
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    embed = request.query_params.get("embed") == "1"
    return templates.TemplateResponse(request=request, name="staff.html", context={
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "staff_username": request.session.get("staff_username"),
        "sidebar_active": "configuracion",
        "embed": embed,
    })


# ------------------------------------------------------------------ errores: mensaje amable + identificador; la traza completa solo va al log
def _request_id(request: Request) -> str:
    return (request.scope.get("state") or {}).get("request_id") or obs.request_id_var.get()


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith(("/api/", "/f/", "/c/", "/r/", "/webhooks/")) or request.method != "GET" or "application/json" in request.headers.get("accept", "")


def _error_response(request: Request, status: int, message: str, headers: dict = None) -> JSONResponse | HTMLResponse:
    rid = _request_id(request)
    headers = {**(headers or {}), "X-Request-ID": rid}
    if _wants_json(request):
        return JSONResponse({"detail": message, "request_id": rid}, status_code=status, headers=headers)
    return HTMLResponse(
        f"<!DOCTYPE html><html lang='es'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Algo salió mal</title>"
        f"<body style='font-family:sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;text-align:center'><h2>Algo salió mal</h2><p>{message}</p>"
        f"<p style='color:#666'>Si sigue pasando, avisa a soporte con este código: <strong>{rid}</strong></p><p><a href='/'>Volver al inicio</a></p></body></html>",
        status_code=status, headers=headers)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Cualquier error no controlado: traza completa al log (enmascarada) y un mensaje amable con el identificador para el usuario."""
    log.error("error no controlado en %s %s", request.method, obs.mask_url(request.url.path), exc_info=exc)
    return _error_response(request, 500, "Ocurrió un error inesperado. Ya quedó registrado; puedes intentarlo de nuevo en un momento.")


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeoutError)
async def database_unavailable(request: Request, exc: Exception):
    """La base no respondió (reinicio, cómputo despertando, pool agotado): 503 + Retry-After para que kioscos y formularios reintenten solos."""
    log.error("base de datos no disponible en %s %s", request.method, obs.mask_url(request.url.path), exc_info=exc)
    return _error_response(request, 503, "El servicio está ocupado un momento. Reintenta en unos segundos.", {"Retry-After": "3"})


# ------------------------------------------------------------------ modo de arranque (APP_MODE): deja solo las rutas de este servicio
def _apply_mode() -> None:
    """Las páginas que se declaran directamente en este archivo (`@app.get`) también se filtran por modo; los routers ya se filtraron al incluirlos."""
    if appmode.MODE == "all":
        return
    app.router.routes = [r for r in app.router.routes if type(r).__name__ == "_IncludedRouter" or appmode.route_allowed(getattr(r, "path", ""), is_mount=not hasattr(r, "endpoint"))]


_apply_mode()
