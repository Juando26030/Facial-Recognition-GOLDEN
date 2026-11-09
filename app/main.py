import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlsplit

import anyio.to_thread
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError as PoolTimeoutError
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import report_jobs
from app import bodylimit, form_client, appmode, bulk_jobs, crypto, faces, idle, jobs, obs, ops, publicurl, sessions, timing
from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant, WebForm
from app.routers import print_stations, shared_print
from app import reprint as reprint_core
from app.routers import event_history as event_history_router      # Fase 5: historial de cambios del evento por campo
from app.routers import staff_credentials as staff_credentials_router      # Fase 4: reenvío de credenciales por correo
from app.routers import reprint as reprint_router      # Fase 1B: reimpresión con permisos
from app.routers import stats_links as stats_links_router      # enlaces de solo lectura a las estadísticas
from app.routers import print_settings
from app.routers import api, areas_inventory, auth as auth_router, badges, calendar as calendar_router, cedula, downloads, aceptar as aceptar_router, door as door_router, consents as consents_router, privacy_requests as privacy_requests_router, certificates_public, analytics, digital_public, form_client as form_client_router, form_payments, form_refunds, forms, forms_public, ops as ops_router, roulette, event_docs, event_report, event_states, events, final_database, legal_public, parametros, privacy as privacy_router, signatures, staff, stats, super_events, tenants, uploads as uploads_router, inventory as inventory_router
from app import download_perms
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff, is_inventory_only, split_roles
from app import brandcolor, lastname, personform, registro_gear
from app.routers import person_form as person_form_router      # formulario de persona diseñado por el admin (apagado con PERSON_FORM_ENABLED=0)
from app.routers import form_transfer      # exportar / importar un formulario entre entornos (solo admin)
from app.routers import event_transfer as event_transfer_router      # exportar / importar un EVENTO completo entre entornos (solo super_admin)
from app.routers import pledge as pledge_router      # Fase 4: compromiso digital del digitador
from app.routers import login_approval as login_approval_router      # S1: ingreso de digitadores autorizado por el coordinador
from app.routers import delivery as delivery_router      # Fase 5: entrega al cliente (enlace /entrega/<token>, encuesta de satisfacción, descarga de la base final)
from app.routers import event_template as event_template_router      # Fase 2: plantilla de evento (GET personal con acceso; PUT admin+)

jobs.load_handlers(jobs.GENERAL_KINDS | jobs.FACE_KINDS)          # todos los manejadores registrados AL ARRANCAR, en cualquier modo (antes payments_reconcile solo al llamar /internal/jobs/run)

obs.configure_logging()       # logs en JSON a stdout (formato de Cloud Logging), con datos personales enmascarados
log = logging.getLogger("golden.app")

IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"
SECRET_KEY = os.getenv("SECRET_KEY")
from app import secretcheck  # noqa: E402

_secret_problem = secretcheck.problem(os.getenv("ENVIRONMENT", "development"), SECRET_KEY)      # S11: fuera de desarrollo, nada de clave vacía, de ejemplo o corta
if _secret_problem:
    raise RuntimeError(_secret_problem)


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
    crypto.assert_ready()                         # producción sin FACE_ENCRYPTION_KEY: no arranca (falla cerrado)
    jobs.assert_handlers(appmode.MODE)            # sin el manejador de un trabajo que Cloud Tasks le manda a ESTE servicio: no arranca (falla cerrado)
    worker = None
    if os.getenv("JOBS_WORKER", "on") != "off" and not jobs.uses_cloud_tasks():
        worker = jobs.Worker()
        worker.start()
    if appmode.loads_model():
        await asyncio.get_running_loop().run_in_executor(None, ops.model_ready)        # precalienta dlib (en los procesos hijo): el primer escaneo no paga la carga del modelo
    publicurl.check_at_startup()          # avisa en el log si en producción falta PUBLIC_BASE_URL o apunta al host de Cloud Run
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
    title="GoldenWeb 2.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_WHEN_MUST_CHANGE = ("/cambiar-contrasena", "/logout", "/static/", "/login", "/api/password-policy")


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
async def idle_gate(request, call_next):
    """Cierre de sesión por inactividad del personal (app/idle.py, docs/22). Sin consultas a la base: la última actividad va en la cookie de sesión. Pasado el tiempo (el del evento en proceso, o el
    general), la sesión se borra: las páginas llevan a /login?expirada=1 y las llamadas reciben 401 «session_expired». Solo renuevan la sesión las navegaciones y /api/session/touch."""
    session = request.scope.get("session")
    path = request.url.path
    if not session or not session.get("staff_user_id") or idle.exempt_path(path):
        return await call_next(request)
    nav = idle.is_navigation(request.method, request.headers)
    if idle.absolute_expired(session) or idle.expired(session):          # tope absoluto de admin/super_admin (B7) o inactividad
        session.clear()
        if nav:
            return RedirectResponse("/login?expirada=1", status_code=302)
        return JSONResponse({"detail": "session_expired"}, status_code=401, headers={"Cache-Control": "no-store"})
    if (nav or path == idle.TOUCH_PATH) and request.headers.get(idle.PASSIVE_HEADER) != "1":
        idle.renew(session, reset_event=nav)
    elif not isinstance(session.get("la"), int):
        session["la"] = idle.now()
    if not isinstance(session.get("iat"), int):          # cookie anterior al tope absoluto: corre desde ahora (desplegar no expulsa a nadie)
        session["iat"] = idle.now()
    token = idle.bind(session)
    try:
        return await call_next(request)
    finally:
        idle.unbind(token)


# E1 (Fase 3, nov-2026): la política que SÍ se aplica suma `form-action 'self'` (ningún <form> del repo apunta fuera del sitio; lo fija tests/test_seguridad_fase3b.py) y,
# además, una política completa en modo «Report-Only»: no bloquea nada, los avisos salen en la consola del navegador. Dos políticas: la del panel y la de los formularios
# públicos `/f/*` (que además cargan Wompi y el traductor de Google y se incrustan en el sitio del cliente, por eso sin `frame-ancestors`). Se conserva 'unsafe-inline'
# en script-src/style-src mientras haya bloques en línea (tests/test_csp_trinquete.py los hace bajar); con eso script-src todavía no frena un XSS, pero connect-src,
# img-src y form-action ya cortan la salida de datos. Cuando la consola salga limpia en staging se pasa a obligatoria. Sin `report-uri` (no hay ruta de reportes; ver docs/FASE_3_SEGURIDAD.md).
# CSP_REPORT_ONLY=0 apaga la cabecera de prueba.
_CSP_REPORT_ONLY = os.getenv("CSP_REPORT_ONLY", "1") == "1"
_CSP_PANEL = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
              "img-src 'self' data: blob: https://tile.openstreetmap.org https://cdnjs.cloudflare.com; font-src 'self' data:; media-src 'self' blob:; "
              "connect-src 'self' https://nominatim.openstreetmap.org https://storage.googleapis.com; frame-src 'self' blob:; worker-src 'self' blob:; "
              "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
_CSP_PUBLIC_FORM = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://checkout.wompi.co https://translate.google.com "
                    "https://translate.googleapis.com https://www.gstatic.com; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://www.gstatic.com; "
                    "img-src 'self' data: blob: https://tile.openstreetmap.org https://cdnjs.cloudflare.com https://www.gstatic.com https://www.google.com https://translate.googleapis.com; "
                    "font-src 'self' data:; media-src 'self' blob:; connect-src 'self' https://nominatim.openstreetmap.org https://storage.googleapis.com https://*.wompi.co https://translate.googleapis.com; "
                    "frame-src 'self' blob: https://*.wompi.co https://translate.google.com; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'")      # sin frame-ancestors: se incrusta a propósito


@app.middleware("http")
async def security_headers(request, call_next):
    """Cabeceras de seguridad globales (Fase 0C, pasada 2: B1/D8). No pisan lo que la ruta ya haya fijado.
    - nosniff: el navegador no «adivina» el tipo de un archivo subido.
    - frame-ancestors/object-src/base-uri: nadie puede incrustar el panel, ni meter <object>/<base>.
    - Un SVG (logos antiguos o de otros orígenes) se sirve en «sandbox» y sin scripts, aunque lo abran como documento."""
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    embeddable = request.url.path.startswith("/f/")      # los formularios públicos pueden incrustarse en el sitio del cliente
    if not embeddable:
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(self), payment=(self)")      # la cámara y la ubicación (widget de mapa) solo las usa la propia app
    if IS_PRODUCTION:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    if h.get("content-type", "").startswith("image/svg"):
        h["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    else:
        h.setdefault("Content-Security-Policy", ("" if embeddable else "frame-ancestors 'self'; ") + "object-src 'none'; base-uri 'self'; form-action 'self'")
        if _CSP_REPORT_ONLY:
            h.setdefault("Content-Security-Policy-Report-Only", _CSP_PUBLIC_FORM if embeddable else _CSP_PANEL)
    return response


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
    session_cookie=os.getenv("SESSION_COOKIE", "session"),   # detrás de Firebase Hosting debe ser «__session»: es la única cookie que deja pasar
    same_site="lax",
    https_only=IS_PRODUCTION,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)          # el directorio de miles de personas baja de ~2 MB a ~150 KB
if timing.active():                                  # diagnóstico de esperas (SERVER_TIMING / LOG_SLOW_WAITS_MS): apagado por defecto, sin costo si está apagado
    from app.database import engine as _engine
    timing.install_db(_engine)
    app.add_middleware(timing.TimingMiddleware)
app.add_middleware(bodylimit.BodyLimitMiddleware)             # C3/R3-07: tope de cuerpo en las rutas públicas (413 antes de leer nada)
app.add_middleware(obs.RequestLogMiddleware, on_5xx=ops.record_5xx)     # el más externo: mide y registra TODA petición (incluidos los errores)

app.mount("/static", StaticFilesNoCacheInDev(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


from app import staticver  # noqa: E402

staticver.install(templates)
templates.env.filters["fromjson"] = json.loads

REMOTE_LOGO_URL = "https://www.goldenlogisticas.com/wp-content/uploads/2025/07/logo-golden-con-letras-1.png"
LOCAL_LOGO_FILE = os.path.join("static", "img", "logo-golden.png")          # copia PROPIA del logo: se sirve desde /static y el service worker del quiosco la guarda, así el logo se ve sin red
LOCAL_LOGO_URL = "/static/img/logo-golden.png"


def default_logo_url() -> str:
    """Logo por defecto del header: `DEFAULT_LOGO_URL` si se define; si no, la copia propia `static/img/logo-golden.png` cuando existe (se ve sin red), y si todavía no está, la URL de Golden."""
    return os.getenv("DEFAULT_LOGO_URL") or (LOCAL_LOGO_URL if os.path.exists(LOCAL_LOGO_FILE) else REMOTE_LOGO_URL)


DEFAULT_LOGO_URL = default_logo_url()          # (compatibilidad: el valor al arrancar)


def event_logo_url(event):
    """URL del logo del header para las páginas de un evento (ítem 1, reunión 2026-09-21): el de
    Golden por defecto, ninguno si se ocultó, o el propio del evento. Vacío = no dibujar <img>."""
    mode = getattr(event, "logo_mode", "default")
    if mode == "hidden":
        return ""
    if mode == "custom" and event.logo_path:
        return f"/api/events/{event.id}/logo"
    return default_logo_url()


def golden_logo_attrs():
    """Atributo style del logo de Golden en el encabezado: el alto global que fija el super administrador en Configuración → Apariencia (30–80 px; 50 por defecto)."""
    from markupsafe import Markup
    from app import logosize
    return Markup(f'style="--gw-logo-h:{logosize.get()}px;"')  # nosec B704 - un entero acotado 30-80; es una variable CSS: en celular manda la regla propia del encabezado


def event_logo_attrs(event):
    """Atributos del <img> del logo del encabezado: con logo propio, el alto elegido para ESE evento (30–80 px; el header mide 80) y, en modo «banner», que rellene el ancho disponible
    del header (recortando lo que sobre); con el logo de Golden, el alto global de Configuración → Apariencia."""
    from markupsafe import Markup
    if getattr(event, "logo_mode", "default") != "custom" or not event.logo_path:
        if getattr(event, "logo_mode", "default") == "hidden":
            return Markup("")
        own = int(getattr(event, "logo_height", None) or 50)
        if own != 50:           # el evento fijó SU tamaño (50 es el de fábrica): vale para este evento aunque muestre el logo de Golden; si no, el global de Configuración
            return Markup(f'style="--gw-logo-h:{max(30, min(80, own))}px;"')  # nosec B704 - entero acotado 30-80
        return golden_logo_attrs()
    height = max(30, min(80, int(getattr(event, "logo_height", None) or 50)))
    if getattr(event, "logo_fit", "logo") == "banner":
        return Markup(f'style="height:{height}px; width:100%; object-fit:cover;" data-banner="1"')  # nosec B704 - height es un entero acotado 30-80
    return Markup(f'style="height:{height}px;"')  # nosec B704 - height es un entero acotado 30-80


templates.env.globals["company_name"] = (os.getenv("COMPANY_NAME") or "Golden Eventos y Logística S.A.S.").strip()      # nombre de la sociedad en pantalla (variable COMPANY_NAME; sin ella, el nombre de siempre)
templates.env.globals["event_logo_url"] = event_logo_url
templates.env.globals["public_base_url"] = publicurl.base          # dirección pública (PUBLIC_BASE_URL) para los enlaces que muestra el panel: QR del cartel, enlaces de formularios, webhook
templates.env.globals["event_logo_attrs"] = event_logo_attrs
templates.env.globals["golden_logo_attrs"] = golden_logo_attrs
templates.env.globals["print_settings_json"] = print_settings.settings_json       # valores de impresión del evento con el significado actual (sin lo de versiones viejas)


def _include(router, prefix: str = "") -> None:
    """`app.include_router` que respeta APP_MODE: en un modo que no es `all` solo incluye las rutas de ESE servicio (ver app/appmode.py)."""
    if appmode.MODE != "all":
        keep = APIRouter()
        keep.routes.extend(r for r in router.routes if appmode.route_allowed(prefix + getattr(r, "path", "")))
        router = keep
    app.include_router(router, prefix=prefix)

_include(auth_router.router)
_include(pledge_router.router, prefix="/api")      # Fase 4: compromiso digital del digitador (lado del coordinador; el público es el motor de formularios)
_include(login_approval_router.router)      # S1: ingreso de digitadores autorizado por el coordinador y desbloqueo de cuentas (app/login_control.py)
_include(api.router, prefix="/api")
_include(events.router, prefix="/api")
_include(event_states.router, prefix="/api")
_include(event_template_router.router, prefix="/api")      # Fase 2: plantilla de evento (campos, vista de creación y vista del calendario)
_include(staff.router, prefix="/api")
_include(tenants.router, prefix="/api")
_include(downloads.router, prefix="/api")      # Fase 4: bases de digitadores y de clientes (app/download_perms.py)
_include(badges.router, prefix="/api")
_include(cedula.router, prefix="/api")
_include(stats.router, prefix="/api")
_include(parametros.router, prefix="/api")
_include(person_form_router.router, prefix="/api")
_include(privacy_router.router, prefix="/api")
_include(consents_router.router, prefix="/api")
_include(door_router.router, prefix="/api")
_include(privacy_requests_router.router, prefix="/api")
_include(aceptar_router.router)      # /aceptar/<evento> y /api/aceptar/ (públicas)
_include(legal_public.router)      # /privacidad, /terminos, /reembolsos (públicas)
_include(event_report.router, prefix="/api")
_include(final_database.router, prefix="/api")      # Fase 5: base de datos final del evento (subir/reemplazar/descargar; coordinador+)
_include(event_docs.router, prefix="/api")
_include(uploads_router.router, prefix="/api")   # subida directa al almacenamiento (archivos grandes)
_include(super_events.router, prefix="/api")
_include(areas_inventory.router, prefix="/api")
_include(inventory_router.router, prefix="/api")      # catálogo de inventario (Super Admin) y líneas de inventario por evento con regla de cuadre (Fase 5)
_include(analytics.router, prefix="/api")
_include(report_jobs.router, prefix="/api")      # reporte Excel en segundo plano, con progreso
_include(forms.router, prefix="/api")
_include(form_client_router.router, prefix="/api")      # estadísticas de un formulario + acceso de cliente por formulario (solo agregados)
_include(form_refunds.router, prefix="/api")   # reembolsos de pagos (admin+)
_include(forms_public.router)  # /f/<evento>/<formulario>, público (sin login) a propósito
_include(form_payments.router)  # cotización y confirmación del pago Wompi + webhook (público: Wompi no tiene sesión)
_include(roulette.router, prefix="/api")
_include(print_stations.router, prefix="/api")     # puestos de impresión configurados desde Parámetros y política de sesiones (0072)
_include(shared_print.router, prefix="/api")   # impresión compartida de escarapelas (apagada por defecto, por evento)
_include(event_history_router.router, prefix="/api")      # GET /api/events/{id}/change-history (coordinador del evento, comercial, admin)
_include(staff_credentials_router.router, prefix="/api")      # reenviar credenciales / correo del digitador / interruptor del evento (coordinador+)
_include(reprint_router.router, prefix="/api")      # reimpresión con permisos del coordinador (Fase 1B)
_include(stats_links_router.router, prefix="/api")      # crear/ver/revocar enlaces de estadísticas (coordinador+)
_include(stats_links_router.public_router)      # /ver/e/<token>, /ver/f/<token> y /api/ver/<token>/...: solo lectura, sin sesión
_include(delivery_router.router, prefix="/api")      # Fase 5: enlace de entrega al cliente y correo (comercial+)
_include(delivery_router.public_router)      # /entrega/<token>: encuesta y descarga de la base final (público, servicio `publico`)
_include(reprint_router.public_router)      # /reimpresion/<token>: enlace de correo de un solo uso (el GET solo muestra)
_include(print_settings.router, prefix="/api")   # valores de impresión de escarapelas por evento (cinta, giro, recorte)
_include(roulette.public_router)  # /r/<token>, pantalla del proyector (sin login)
_include(certificates_public.router)  # /c/<token>, público (sin login) a propósito
_include(certificates_public.staff_router, prefix="/api")
_include(digital_public.router)  # /b/<token>, público (sin login) a propósito
_include(signatures.router, prefix="/api")
_include(calendar_router.router, prefix="/api")
_include(form_transfer.router, prefix="/api")      # exportar / importar un formulario entre entornos (solo admin)
_include(event_transfer_router.router, prefix="/api")      # exportar / importar un evento completo (solo super_admin)
_include(ops_router.router)          # /healthz, /readyz, /api/ops/*
_include(ops_router.pages)           # /sistema


def _page_staff(request: Request, db: Session):
    """Trae el StaffUser real de la sesión (no solo el string de rol). None si no hay sesión válida."""
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        return None
    staff = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()
    if staff is not None and sessions.is_replaced(db, request, staff):
        request.session.clear()
        return None
    return staff


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
    roles = {role} | set(split_roles(secondary_role))
    if role != "super_admin" and "admin" in roles:
        return "admin"
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
    roles = [role] + split_roles(secondary_role)
    if max(ROLE_HIERARCHY[r] for r in roles) < ROLE_HIERARCHY[minimum_role]:
        return RedirectResponse("/", status_code=302)
    return None


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)

    if staff_user.role == "cliente" and form_client.is_form_client(db, staff_user):
        return RedirectResponse("/mi-formulario", status_code=302)       # cliente de FORMULARIO: su única pantalla son las estadísticas de ese formulario

    if is_inventory_only(staff_user):
        return RedirectResponse("/inventario", status_code=302)          # almacén / contabilidad sin otro rol: su única pantalla es el inventario

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
        "can_dl_digitadores": download_perms.can_download_roles(request.session.get("staff_role"), request.session.get("staff_secondary_role"), download_perms.KIND_DIGITADORES),
        "can_dl_clientes": download_perms.can_download_roles(request.session.get("staff_role"), request.session.get("staff_secondary_role"), download_perms.KIND_CLIENTES),
    })


def _nuevo_evento_response(request: Request, tenant: Optional[Tenant], sidebar_active: str, back_url: str):
    """Misma pantalla y mismo formulario para las dos entradas (Clientes -> «Nuevo evento» y pestaña Eventos -> «Nuevo evento»).
    Con `tenant` el cliente ya viene asignado (no se pide); con None la pantalla muestra el primer campo «Cliente» (lista con buscador)."""
    _roles = {request.session.get("staff_role")} | set(split_roles(request.session.get("staff_secondary_role")))
    return templates.TemplateResponse(request=request, name="nuevo_evento.html", context={
        "pure_coordinator": not ({"comercial", "admin", "super_admin"} & _roles),
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "staff_id": request.session.get("staff_user_id"),
        "sidebar_active": sidebar_active,
        "tenant_id": tenant.id if tenant else "",
        "tenant_name": tenant.name if tenant else "",
        "pick_tenant": tenant is None,
        "back_url": back_url,
    })


@app.get("/clientes/{tenant_id}/nuevo-evento")
def nuevo_evento_page(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    """Sprint 2.4 Fase 1 (2026-09-16, pedido explícito): "Crear evento" pasa a ser una pantalla
    dedicada en vez del formulario inline que aparecía bajo el cliente expandido en /clientes —
    mismo formulario/JS de siempre (createEvent), reubicado. coordinador+, mismo mínimo
    que POST /api/events (el coordinador puro queda fijado como coordinador y sin elegir comercial)."""
    redirect = _require_page_role(request, "coordinador")      # 4-nov-2026: el coordinador también crea eventos
    if redirect:
        return redirect
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return RedirectResponse("/clientes", status_code=302)
    return _nuevo_evento_response(request, tenant, "clientes", "/clientes")


@app.get("/eventos/nuevo")
def nuevo_evento_desde_eventos_page(request: Request):
    """Fase 2 (7-nov-2026): crear evento también desde la pestaña Eventos. Es el MISMO formulario que /clientes/{id}/nuevo-evento,
    con el campo «Cliente» (lista con buscador) como primer dato. Mismos permisos que la otra entrada y que POST /api/events;
    la lista de clientes sale de GET /api/tenants, que ya limita lo que cada rol puede ver."""
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return _nuevo_evento_response(request, None, "eventos", "/eventos")


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


@app.get("/inventario")
def inventario_page(request: Request):
    """Inventario de los eventos (Fase 5): pantalla de las cuentas de almacén y contabilidad (con o sin otros roles) y de coordinador+. Lo que cada rol puede editar lo decide el servidor (app/routers/inventory.py)."""
    role = request.session.get("staff_role")
    if not role:
        return RedirectResponse("/login", status_code=302)
    roles = {role} | set(split_roles(request.session.get("staff_secondary_role")))
    if not (roles & {"almacen", "contabilidad"}) and max(ROLE_HIERARCHY[r] for r in roles) < ROLE_HIERARCHY["coordinador"]:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request=request, name="inventario.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(role, request.session.get("staff_secondary_role")),
    })


@app.get("/configuracion/plantilla-evento")
def plantilla_evento_page(request: Request):
    """Diseñar la plantilla de eventos (Fase 2): vista de creación y vista del calendario. Solo admin y super_admin (cualquier otro rol vuelve al inicio)."""
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="plantilla_evento.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "sidebar_active": "configuracion",
    })


@app.get("/impresion-usb")
def impresion_usb_page(request: Request):
    """Prueba y ajuste de la impresión directa de escarapelas en la Brother QL por USB (WebUSB desde Chrome de Android o de escritorio; ver static/js/ql-usb.js). Digitador o más."""
    redirect = _require_page_role(request, "digitador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="impresion_usb.html", context={})


def contingency_enabled() -> bool:
    """Modo contingencia del quiosco (copia local de la lista + service worker `/kiosk/sw.js`). APAGADO por defecto; lo prende `CONTINGENCY_ENABLED=1` (staging, desde deploy/gcp/config.sh).
    Encenderlo en producción exige constancia legal escrita, pruebas en dispositivos reales y decisión de Juan David (docs/15, D2.5d)."""
    return os.getenv("CONTINGENCY_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


@app.get("/kiosk/sw.js", include_in_schema=False)
def kiosk_service_worker():
    """Service worker del quiosco (static/js/kiosk-sw.js): solo guarda el caparazón de `/kiosk/<id>/registro` y `/static/*` para recargar la página sin red; nunca la API ni el roster. Va en
    `/kiosk/` (su alcance por defecto es esa carpeta: solo controla las páginas del quiosco) y ANTES de `/kiosk/{event_id}`. `__BUILD__` = revisión de Cloud Run + huella del archivo:
    cada despliegue cambia el contenido, el navegador instala el worker nuevo y éste borra los cachés viejos. Sin caché HTTP, para que el navegador vea siempre la última versión."""
    if not contingency_enabled():       # apagado: un worker que se desregistra y borra sus cachés (quien lo tenía de antes queda limpio en su próxima visita)
        source = open(os.path.join("static", "js", "kiosk-sw-off.js"), encoding="utf8").read()
        return Response(source, media_type="application/javascript", headers={"Cache-Control": "no-cache, max-age=0"})
    source = open(os.path.join("static", "js", "kiosk-sw.js"), encoding="utf8").read()
    build = f"{os.getenv('K_REVISION', 'local')}-{hashlib.sha1(source.encode(), usedforsecurity=False).hexdigest()[:10]}"
    return Response(source.replace("__BUILD__", build), media_type="application/javascript", headers={"Cache-Control": "no-cache, max-age=0"})


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
    person_form = personform.active(db, event, field_configs)          # None con PERSON_FORM_ENABLED apagado o el evento sin él: todo se ve y funciona como siempre
    context = {
        "person_form_json": json.dumps(person_form).replace("</", "<\\/") if person_form else "null",
        "person_form_env": personform.env_enabled(),
        "person_form_can_design": personform.env_enabled() and max(ROLE_HIERARCHY[r] for r in staff_roles) >= ROLE_HIERARCHY["admin"],
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": _display_role(staff_user.role, staff_user.secondary_role),
        "event": event,
        "optional_labels": optional_labels,
        "optional_labels_json": optional_labels_json,
        "field_configs": field_configs,
        "field_configs_json": field_configs_json,
        "field_labels": {cfg["key"]: cfg["label"] for cfg in field_configs},
        "sidebar_active": "eventos",
        "contingency_enabled": contingency_enabled(),
        "registro_gear": registro_gear.can_see_gear(db, event.id, staff_roles),        # Plan 7: engranaje «Configuración del registro» (solo visual)
        "search_unified": os.getenv("SEARCH_UNIFIED", "1") != "0",       # Fase 1A: buscador único en el directorio; SEARCH_UNIFIED=0 vuelve a las 3 cajas
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


@app.get("/kiosk/{event_id}/rostro")
def kiosk_rostro(event_id: int, request: Request, db: Session = Depends(get_db)):
    """B1: pantalla de autoservicio «Entrar con mi rostro» (la persona pulsa; el equipo está abierto con una cuenta del personal). Ver app/routers/door.py."""
    from app.routers.api import NOT_FOUND_FACE
    return _resolve_kiosk_page(event_id, request, db, "kiosk_rostro.html", extra_context={"not_found": NOT_FOUND_FACE})


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
    from app import event_rules
    from app.routers.api import OVERWRITE_BIRTH_LABEL
    event_obj = db.get(Event, event_id)
    return _resolve_kiosk_page(event_id, request, db, "kiosk_roster.html", min_role="coordinador", exclude_roles=["comercial"],
                               extra_context={"roster_blocked": event_rules.roster_block_reason(event_obj) if event_obj is not None else None, "overwrite_birth_label": OVERWRITE_BIRTH_LABEL,
                                              # «Solo agregar personas nuevas»: con el evento en proceso, o con la base ya cargada (nunca finalizado)
                                              "append_available": event_obj is not None and not event_rules.roster_block_reason(event_obj, append_only=True) and (event_obj.status == "en_proceso" or bool(event_obj.roster_uploaded))})


@app.get("/kiosk/{event_id}/usuarios")
def kiosk_usuarios(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Gestión de cuentas digitador/cliente de este evento (Sprint 2.2 Fase B, 2026-09-16) — antes
    vivía como pestaña "Usuarios del Evento" dentro de /kiosk/{event_id}/registro; se mueve a su
    propia ruta, mismo patrón que "Escarapelas"/"Adjuntar Base de Datos". Mismo mínimo de rol que
    antes (coordinador+ para crear digitador, admin+ dentro del template para cliente/asignar)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_usuarios.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/usuarios/hoja")
def kiosk_usuarios_hoja(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Hoja IMPRESA (A4, cuadro de impresión normal del navegador) con las cuentas temporales del evento: nombre, cédula como usuario e instrucciones. Sin contraseñas. No es la impresión de escarapelas."""
    from app import staff_credentials
    staff_user = _page_staff(request, db)
    rows = []
    if staff_user is not None and effective_roles(staff_user) - {"comercial"}:
        rows = (db.query(StaffUser).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
                .filter(EventStaffAuthorization.event_id == event_id, StaffUser.role == "digitador", StaffUser.is_active == True, StaffUser.archived_at.is_(None))      # noqa: E712
                .order_by(StaffUser.full_name, StaffUser.username).limit(500).all())
    return _resolve_kiosk_page(event_id, request, db, "kiosk_usuarios_hoja.html", min_role="coordinador", exclude_roles=["comercial"],
                               extra_context={"sheet_rows": [{"name": r.full_name or "", "username": r.username} for r in rows], "login_url": staff_credentials.login_url(str(request.base_url)),
                                              "coordinator_name": staff_credentials.event_info(db, db.get(Event, event_id))["coordinator"] if db.get(Event, event_id) is not None else ""})


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
    return _resolve_kiosk_page(event_id, request, db, "kiosk_parametros.html", min_role="coordinador", exclude_roles=["comercial"], extra_context={"idle_general_minutes": idle.general_minutes(), "reprint_approval_minutes": reprint_core.approval_minutes(), "registro_gear_dig": registro_gear.digitadores_enabled(db, event_id), "last_name_state": lastname.state(db, event_id), "brand_default": brandcolor.DEFAULT_PICK})


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


@app.get("/kiosk/{event_id}/formularios/{form_id}/estadisticas")
def kiosk_form_stats(event_id: int, form_id: int, request: Request, db: Session = Depends(get_db)):
    """Estadísticas de UN formulario (cupos, inscritos, distribución por variables), solo agregados — coordinador+."""
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    try:
        event = get_event_for_staff(event_id, db, staff_user)
    except HTTPException:
        return RedirectResponse("/", status_code=302)
    form = db.query(WebForm).filter(WebForm.id == form_id, WebForm.event_id == event.id).first()
    if not form:
        return RedirectResponse(f"/kiosk/{event_id}/formularios", status_code=302)
    return templates.TemplateResponse(request=request, name="form_stats.html", context={
        "api_url": f"/api/events/{event.id}/forms/{form.id}/stats", "form_name": form.name, "event_name": event.name, "staff_name": staff_user.full_name or staff_user.username,
        "back_url": f"/kiosk/{event.id}/formularios/{form.id}", "back_label": "Volver al formulario", "client_view": False, "form_id": form.id, "event_id": event.id})


@app.get("/mi-formulario")
def mi_formulario_page(request: Request, db: Session = Depends(get_db)):
    """Pantalla del cliente de FORMULARIO: las estadísticas de su formulario y nada más."""
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    if not form_client.is_form_client(db, staff_user):
        return RedirectResponse("/", status_code=302)
    try:
        _, form, event = form_client.resolve(db, staff_user)
    except HTTPException as e:
        return templates.TemplateResponse(request=request, name="form_stats.html", status_code=e.status_code, context={
            "api_url": "", "form_name": "", "event_name": "", "staff_name": staff_user.full_name or staff_user.username, "back_url": "", "back_label": "",
            "client_view": True, "blocked_message": e.detail})
    return templates.TemplateResponse(request=request, name="form_stats.html", context={
        "api_url": "/api/form-client/stats", "form_name": form.name, "event_name": event.name, "staff_name": staff_user.full_name or staff_user.username,
        "back_url": "", "back_label": "", "client_view": True})


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
def kiosk_badge_print(event_id: int, user_id: str, request: Request, users: Optional[str] = None, db: Session = Depends(get_db)):
    """Vista de SOLO la escarapela de una persona, a tamaño real (mm), para imprimir — se abre en
    una pestaña/ventana aparte desde el botón "Imprimir Escarapela" (o sola, si el evento tiene
    auto_print_badge activo) sin sacar al digitador de la pantalla de Registro. 'comercial'
    excluido explícitamente (Sprint 2.4 Fase 6, pedido explícito: "la comercial no debe poder
    imprimir")."""
    # `?users=a,b,c` (29-oct-2026, «Imprimir pendientes»): UNA sola ventana con una página por escarapela (hasta 50); sin él, una sola persona como siempre.
    many = [u.strip() for u in (users or "").split(",") if u.strip()][:50]
    return _resolve_kiosk_page(event_id, request, db, "badge_print.html", exclude_roles=["comercial"], extra_context={
        "print_user_id": user_id,
        "print_user_id_json": json.dumps(user_id).replace("</", "<\\/"),
        "print_users_json": json.dumps(many if len(many) > 1 else [user_id]).replace("</", "<\\/"),
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
        "can_dl_digitadores": download_perms.can_download_roles(request.session.get("staff_role"), request.session.get("staff_secondary_role"), download_perms.KIND_DIGITADORES),
        "can_dl_clientes": download_perms.can_download_roles(request.session.get("staff_role"), request.session.get("staff_secondary_role"), download_perms.KIND_CLIENTES),
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


@app.exception_handler(bodylimit.BodyTooLarge)
async def body_too_large(request: Request, exc: Exception):
    """El cuerpo (sin Content-Length o con uno falso) pasó el tope de su ruta pública mientras se leía: 413, sin 500 ni traza."""
    return JSONResponse({"detail": bodylimit.MSG}, status_code=413, headers={"Connection": "close"})


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
