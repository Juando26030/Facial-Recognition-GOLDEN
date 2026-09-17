import os
import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.routers import api, auth as auth_router, badges, calendar as calendar_router, cedula, events, parametros, staff, stats, tenants
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff

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
app.include_router(stats.router, prefix="/api")
app.include_router(parametros.router, prefix="/api")
app.include_router(calendar_router.router, prefix="/api")


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
            "staff_role": _display_role(staff_user.role, staff_user.secondary_role),
        })

    # coordinador/admin/super_admin (Sprint 2.3, 2026-09-16): el panel combinado (árbol
    # Cliente→Eventos) se partió en secciones del menú lateral nuevo — Clientes es el punto de
    # entrada por defecto ahora, ver templates/clientes.html.
    return RedirectResponse("/clientes", status_code=302)


@app.get("/clientes")
async def clientes_page(request: Request):
    redirect = _require_page_role(request, "coordinador")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="clientes.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "sidebar_active": "clientes",
    })


@app.get("/clientes/{tenant_id}/nuevo-evento")
async def nuevo_evento_page(tenant_id: str, request: Request, db: Session = Depends(get_db)):
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
async def eventos_page(request: Request):
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
async def calendario_page(request: Request):
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
async def configuracion_page(request: Request):
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
        "sidebar_active": "eventos",
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
    # exclude_roles (Sprint 2.4 Fase 6, 2026-09-16, pedido explícito): 'comercial' queda por
    # ENCIMA de 'coordinador' en STAFF_ROLES (hereda su acceso operativo por diseño, Fase 0), pero
    # explícitamente NO debe ver "Adjuntar Base de Datos" — un min_role jerárquico no alcanza para
    # excluir un rol que está por encima del mínimo.
    return _resolve_kiosk_page(event_id, request, db, "kiosk_roster.html", min_role="coordinador", exclude_roles=["comercial"])


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
async def kiosk_parametros(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Parámetros del Evento (Sprint 2.2, 2026-09-16, pedido explícito) — coordinador+ define por
    campo si es obligatorio, qué tipo de control usar y si debe generar estadística sola al
    entrar a Estadísticas. Mismo mínimo de rol que Adjuntar Base de Datos/Usuarios del Evento.
    'comercial' excluido explícitamente (Sprint 2.4 Fase 6, 2026-09-16, pedido explícito) — queda
    por ENCIMA de 'coordinador' en STAFF_ROLES, así que min_role solo no alcanza para bloquearlo."""
    return _resolve_kiosk_page(event_id, request, db, "kiosk_parametros.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/escarapela")
async def kiosk_badge_editor(event_id: int, request: Request, db: Session = Depends(get_db)):
    """Editor visual de la escarapela del evento (Sprint 2, Épico 2) — mismo mínimo de rol que
    Adjuntar Base de Datos (coordinador+); la impresión en sí (no el diseño) se dispara desde
    /kiosk/{event_id}/registro, disponible para digitador+. 'comercial' excluido explícitamente
    (Sprint 2.4 Fase 6) — no debe diseñar NI imprimir escarapelas."""
    return _resolve_kiosk_page(event_id, request, db, "badge_editor.html", min_role="coordinador", exclude_roles=["comercial"])


@app.get("/kiosk/{event_id}/escarapela/imprimir/{user_id}")
async def kiosk_badge_print(event_id: int, user_id: str, request: Request, db: Session = Depends(get_db)):
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
async def staff_page(request: Request):
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
