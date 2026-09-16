import os
import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser
from app.routers import api, auth as auth_router, badges, cedula, events, staff, tenants
from app.auth import ROLE_HIERARCHY, get_event_for_staff

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


app = FastAPI(
    title="Golden Biometrics SaaS",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production",
    same_site="lax",
    https_only=IS_PRODUCTION,
)

app.mount("/static", StaticFilesNoCacheInDev(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(auth_router.router)
app.include_router(api.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(staff.router, prefix="/api")
app.include_router(tenants.router, prefix="/api")
app.include_router(badges.router, prefix="/api")
app.include_router(cedula.router, prefix="/api")


def _page_staff(request: Request, db: Session):
    """Trae el StaffUser real de la sesión (no solo el string de rol). None si no hay sesión válida."""
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        return None
    return db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()


def _require_page_role(request: Request, minimum_role: str):
    """Para páginas simples que solo necesitan el rol (no el objeto completo): sin sesión -> /login;
    sin permiso suficiente -> /."""
    role = request.session.get("staff_role")
    if not role:
        return RedirectResponse("/login", status_code=302)
    if ROLE_HIERARCHY[role] < ROLE_HIERARCHY[minimum_role]:
        return RedirectResponse("/", status_code=302)
    return None


@app.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
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
        "staff_role": staff_user.role,
    })


@app.get("/kiosk/{event_id}")
async def kiosk_entry(event_id: int, request: Request, db: Session = Depends(get_db)):
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
        return templates.TemplateResponse(request=request, name="kiosk_registro.html", context={
            "staff_name": staff_user.full_name or staff_user.username,
            "staff_role": staff_user.role,
            "event": event,
            "optional_labels": [],  # cliente no ve "Registro Individual", no hace falta calcularlos
        })

    return templates.TemplateResponse(request=request, name="kiosk_select.html", context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
        "event": event,
    })


def _resolve_kiosk_page(event_id: int, request: Request, db: Session, template_name: str, min_role: str = None, extra_context: dict = None):
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
    if min_role and ROLE_HIERARCHY.get(staff_user.role, -1) < ROLE_HIERARCHY[min_role]:
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
    context = {
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
        "event": event,
        "optional_labels": optional_labels,
        "optional_labels_json": optional_labels_json,
    }
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(request=request, name=template_name, context=context)


@app.get("/kiosk/{event_id}/registro")
async def kiosk_registro(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Pantalla única de registro (2026-09-21, reemplaza los antiguos /facial y /cedula
    separados) — un solo Directorio en Vivo con búsqueda por cédula/nombre/empresa, y el escáner
    de cámara aparece o no según `event.facial_enabled` (se enciende solo al subir un roster con
    fotos, ver bulk_register). Se dejaron de exponer dos "métodos" distintos porque ambos
    compartían exactamente el mismo directorio y la diferencia real era una sola cosa: si hay
    fotos cargadas o no."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_registro.html")


@app.get("/kiosk/{event_id}/facial")
@app.get("/kiosk/{event_id}/cedula")
async def kiosk_registro_legacy_redirect(event_id: int):
    """Rutas viejas (antes de la unificación Facial/Cédula) — quien tenga un enlace guardado cae
    igual a la pantalla de Registro unificada en vez de un 404."""
    return RedirectResponse(f"/kiosk/{event_id}/registro", status_code=302)


@app.get("/kiosk/{event_id}/roster")
async def kiosk_roster(event_id: int, request: Request, db: Session = Depends(get_db)):
    return _resolve_kiosk_page(event_id, request, db, "kiosk_roster.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/usuarios")
async def kiosk_usuarios(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Gestión de cuentas digitador/cliente de este evento (Sprint 2.2 Fase B, 2026-09-16) — antes
    vivía como pestaña "Usuarios del Evento" dentro de /kiosk/{event_id}/registro; se mueve a su
    propia ruta, mismo patrón que "Escarapelas"/"Adjuntar Base de Datos". Mismo mínimo de rol que
    antes (coordinador+ para crear digitador, admin+ dentro del template para cliente/asignar)."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_usuarios.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/estadisticas")
async def kiosk_estadisticas(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Reporte + gráficos del evento (Sprint 2.2 Fase B, 2026-09-16) — antes vivía como pestaña
    "Exportar Reporte" dentro de /kiosk/{event_id}/registro; se mueve a su propia ruta. Por ahora
    solo trae el export de siempre — el módulo de gráficos por variable llega en la Fase D."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_estadisticas.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/escarapela")
async def kiosk_badge_editor(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Editor visual de la escarapela del evento (Sprint 2, Épico 2) — mismo mínimo de rol que
    Adjuntar Base de Datos (coordinador+); la impresión en sí (no el diseño) se dispara desde
    /kiosk/{event_id}/registro, disponible para digitador+."""
    return _resolve_kiosk_page(event_id, request, db, "badge_editor.html", min_role="coordinador")


@app.get("/kiosk/{event_id}/escarapela/imprimir/{user_id}")
async def kiosk_badge_print(event_id: int, user_id: str, request: Request, db: Session = Depends(get_db)):
    """Vista de SOLO la escarapela de una persona, a tamaño real (mm), para imprimir — se abre en
    una pestaña/ventana aparte desde el botón "Imprimir Escarapela" (o sola, si el evento tiene
    auto_print_badge activo) sin sacar al digitador de la pantalla de Registro."""
    return _resolve_kiosk_page(event_id, request, db, "badge_print.html", extra_context={
        "print_user_id": user_id,
        "print_user_id_json": json.dumps(user_id).replace("</", "<\\/"),
    })


@app.get("/admin/staff")
async def staff_page(request: Request):
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="staff.html", context={
        "staff_role": request.session.get("staff_role"),
        "staff_username": request.session.get("staff_username"),
    })
