import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.routers import api, auth as auth_router, events, staff
from app.auth import ROLE_HIERARCHY

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


@app.get("/")
async def read_index(request: Request):
    if not request.session.get("staff_user_id"):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request=request, name="index.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": request.session.get("staff_role"),
    })


def _require_page_role(request: Request, minimum_role: str):
    """Para páginas (no /api): sin sesión -> /login; sin permiso suficiente -> /. Evita mostrarle
    un JSON 401/403 crudo a alguien navegando el kiosko."""
    role = request.session.get("staff_role")
    if not role:
        return RedirectResponse("/login", status_code=302)
    if ROLE_HIERARCHY[role] < ROLE_HIERARCHY[minimum_role]:
        return RedirectResponse("/", status_code=302)
    return None


@app.get("/admin/events")
async def events_page(request: Request):
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="events.html", context={"staff_role": request.session.get("staff_role")})


@app.get("/admin/staff")
async def staff_page(request: Request):
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="staff.html", context={"staff_role": request.session.get("staff_role")})
