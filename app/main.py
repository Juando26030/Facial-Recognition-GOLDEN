import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_db
from app.models import StaffUser
from app.routers import api, auth as auth_router, events, staff, tenants
from app.auth import ROLE_HIERARCHY, get_event_for_staff

IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"
SECRET_KEY = os.getenv("SECRET_KEY")
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definida. Requerida en producción para firmar la sesión.")

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

app.mount("/static", StaticFiles(directory="static"), name="static")
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
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
    })


@app.get("/kiosk/{event_id}")
async def kiosk_page(event_id: int, request: Request, db: Session = Depends(get_db)):
    staff_user = _page_staff(request, db)
    if not staff_user:
        return RedirectResponse("/login", status_code=302)
    try:
        event = get_event_for_staff(event_id, db, staff_user)
    except HTTPException:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request=request, name="kiosk.html", context={
        "staff_name": staff_user.full_name or staff_user.username,
        "staff_role": staff_user.role,
        "event": event,
    })


@app.get("/admin/staff")
async def staff_page(request: Request):
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="staff.html", context={"staff_role": request.session.get("staff_role")})
