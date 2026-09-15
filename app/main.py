import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser
from app.routers import api, auth as auth_router, events, staff, tenants
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
    así que va directo a kiosk.html. Todos los demás roles eligen primero CÓMO van a registrar
    (facial, QR, ...) — varios métodos pueden convivir en el mismo evento, cada quien entra al
    que le toque; ver /kiosk/{event_id}/facial."""
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    try:
        event = get_event_for_staff(event_id, db, staff_user)
    except HTTPException:
        return RedirectResponse("/", status_code=302)

    if staff_user.role == "cliente":
        return templates.TemplateResponse(request=request, name="kiosk.html", context={
            "staff_name": staff_user.full_name or staff_user.username,
            "staff_role": staff_user.role,
            "event": event,
        })

    return templates.TemplateResponse(request=request, name="kiosk_select.html", context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
        "event": event,
    })


def _resolve_kiosk_page(event_id: int, request: Request, db: Session, template_name: str, min_role: str = None):
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
    return templates.TemplateResponse(request=request, name=template_name, context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
        "event": event,
    })


@app.get("/kiosk/{event_id}/facial")
async def kiosk_facial(event_id: int, request: Request, db: Session = Depends(get_db)):
    return _resolve_kiosk_page(event_id, request, db, "kiosk.html")


@app.get("/kiosk/{event_id}/cedula")
async def kiosk_cedula(event_id: int, request: Request, db: Session = Depends(get_db)):
    return _resolve_kiosk_page(event_id, request, db, "kiosk_cedula.html")


@app.get("/kiosk/{event_id}/roster")
async def kiosk_roster(event_id: int, request: Request, db: Session = Depends(get_db)):
    return _resolve_kiosk_page(event_id, request, db, "kiosk_roster.html", min_role="coordinador")


@app.get("/admin/staff")
async def staff_page(request: Request):
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="staff.html", context={
        "staff_role": request.session.get("staff_role"),
        "staff_username": request.session.get("staff_username"),
    })
