"""Enlaces de SOLO LECTURA a las estadísticas del evento y de un formulario (sin usuario ni contraseña).

Personal (coordinador+ del evento): crear, ver y revocar enlaces. Público: abrir la pantalla con el enlace y leer agregados; no hay ninguna ruta que escriba,
descargue o muestre personas (el enlace nunca llega a `/api/report`, al directorio ni a nada de gestión)."""
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import brandcolor, form_stats, security, stats_links, tv_screen
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import Event, StaffUser, StatsLink, WebForm
from app.routers import analytics as analytics_router
from app.routers import stats as stats_router
from app.timeutil import to_local, utcnow
from app.ttlcache import SlidingLimiter

log = logging.getLogger("golden.statslinks")
router = APIRouter()                 # /api/... (personal)
public_router = APIRouter()          # /ver/... y /api/ver/... (con el enlace)
_limiter = SlidingLimiter()
PAGE_MAX, API_MAX, WINDOW_S = 60, 240, 600
STAFF = require_role("coordinador")
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}


def _link_row(link: StatsLink, form_name: str = "") -> dict:
    return {"id": link.id, "scope": link.scope, "form_id": link.form_id, "form_name": form_name, "label": link.label or "",
            "created_at": link.created_at.isoformat(timespec="seconds") + "Z", "expires_at": link.expires_at.isoformat(timespec="seconds") + "Z",
            "expires_local": to_local(link.expires_at).strftime("%d/%m/%Y %H:%M"), "last_seen_at": (link.last_seen_at.isoformat(timespec="seconds") + "Z") if link.last_seen_at else None}


# ------------------------------------------------------------------------------------------------ Personal
@router.post("/events/{event_id}/stats-links")
def create_link(event_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Crea un enlace. `scope`: «event» (estadísticas del evento) o «form» (con `form_id`). `days`: 1 a 30 (por defecto 7). El enlace completo se devuelve UNA sola vez."""
    event = get_event_for_staff(event_id, db, staff)
    scope = data.get("scope")
    if scope not in ("event", "form"):
        raise HTTPException(status_code=400, detail="Elige si el enlace es de las estadísticas del evento o de un formulario.")
    form = None
    if scope == "form":
        form = db.query(WebForm).filter(WebForm.id == data.get("form_id"), WebForm.event_id == event.id).first() if str(data.get("form_id") or "").isdigit() else None
        if form is None:
            raise HTTPException(status_code=404, detail="Formulario no encontrado")
    if len(stats_links.active_for_event(db, event.id)) >= stats_links.MAX_ACTIVE_PER_EVENT:
        raise HTTPException(status_code=409, detail="Ya hay demasiados enlaces vigentes en este evento. Revoca alguno antes de crear otro.")
    token, link = stats_links.create(db, scope=scope, event=event, form=form, staff=staff, days=data.get("days"), label=str(data.get("label") or ""))
    db.commit()
    base = (str(request.base_url).rstrip("/"))
    url = f"{base}/ver/{'e' if scope == 'event' else 'f'}/{token}"
    tv_url = f"{base}/ver/tv/{token}" if scope == "event" else ""          # la misma credencial de solo lectura también abre la pantalla de TV
    log.info("enlace de estadísticas %s creado (evento %s, alcance %s)", link.id, event.id, scope)
    return {**_link_row(link, form.name if form else ""), "url": url, "tv_url": tv_url}


@router.get("/events/{event_id}/tv")
def staff_tv_data(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Datos de la pantalla de TV para quien proyecta con su propia sesión (coordinador+)."""
    return JSONResponse(tv_screen.snapshot(db, get_event_for_staff(event_id, db, staff)), headers=NO_STORE)


@router.get("/events/{event_id}/stats-links")
def list_links(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    names = {f.id: f.name for f in db.query(WebForm).filter(WebForm.event_id == event.id)}
    return {"links": [_link_row(link, names.get(link.form_id, "")) for link in stats_links.active_for_event(db, event.id)], "max_days": stats_links.MAX_DAYS, "default_days": stats_links.DEFAULT_DAYS}


@router.delete("/events/{event_id}/stats-links/{link_id}")
def revoke_link(event_id: int, link_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    link = db.query(StatsLink).filter(StatsLink.id == link_id, StatsLink.event_id == event.id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Enlace no encontrado")
    stats_links.revoke(db, link)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ Público (con el enlace)
def _limited(request: Request, kind: str, max_hits: int) -> bool:
    ip = security.limit_ip(request)
    return ip is not None and not _limiter.hit((kind, ip), max_hits, WINDOW_S)


def _gone(status: int = 404) -> HTMLResponse:
    """El mismo mensaje para un enlace desconocido, vencido o revocado: no se confirma nada a quien lo adivina."""
    body = ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            "<title>Enlace no disponible</title><style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1.25rem;line-height:1.55;color:#14213d}</style></head>"
            "<body><h1>Este enlace ya no está disponible</h1><p>Venció o fue cancelado. Pide uno nuevo a quien te lo compartió.</p></body></html>")
    return HTMLResponse(body, status_code=status, headers=NO_STORE)


def _json_gone(status: int = 404) -> JSONResponse:
    return JSONResponse({"detail": "Enlace no disponible"}, status_code=status, headers=NO_STORE)


def _touch(db: Session, link: StatsLink) -> None:
    """Última vez visto: se anota como mucho cada 10 minutos para no escribir en cada consulta."""
    if link.last_seen_at is None or utcnow() - link.last_seen_at > timedelta(minutes=10):
        link.last_seen_at = utcnow()
        db.commit()


def _event_of(db: Session, link: StatsLink):
    return db.get(Event, link.event_id)


@public_router.get("/ver/e/{token}")
def event_page(token: str, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "page", PAGE_MAX):
        return _gone(429)
    link = stats_links.resolve(db, token, "event")
    event = _event_of(db, link) if link else None
    if link is None or event is None:
        return _gone()
    _touch(db, link)
    from app.main import templates      # import tardio: main.py importa este módulo
    return templates.TemplateResponse(request=request, name="kiosk_estadisticas.html", headers=NO_STORE, context={
        "event": event, "staff_name": "", "staff_role": "cliente", "embed": True, "stats_base": f"/api/ver/{token}", "public_view": {"title": event.name, "until": to_local(link.expires_at).strftime("%d/%m/%Y %H:%M")}})


def tv_context(event: Event, api_url: str, logo_url: str) -> dict:
    return {"event": event, "tv_api": api_url, "logo_url": logo_url, "brand_css": brandcolor.css(getattr(event, "brand_color", None)), "poll_s": 10}


@public_router.get("/ver/tv/{token}")
def tv_page(token: str, request: Request, db: Session = Depends(get_db)):
    """Pantalla de TV con el mismo enlace de solo lectura de las estadísticas del evento (sin usuario ni contraseña)."""
    if _limited(request, "page", PAGE_MAX):
        return _gone(429)
    link = stats_links.resolve(db, token, "event")
    event = _event_of(db, link) if link else None
    if link is None or event is None:
        return _gone()
    _touch(db, link)
    from app.main import templates
    logo = f"/api/ver/{token}/logo" if event.logo_mode == "custom" and event.logo_path else ""
    return templates.TemplateResponse(request=request, name="kiosk_tv.html", headers=NO_STORE, context=tv_context(event, f"/api/ver/{token}/tv", logo))


@public_router.get("/api/ver/{token}/tv")
def public_tv(token: str, request: Request, db: Session = Depends(get_db)):
    event, err = _api_event(token, request, db)
    return err or JSONResponse(tv_screen.snapshot(db, event), headers=NO_STORE)


@public_router.get("/api/ver/{token}/logo")
def public_logo(token: str, request: Request, db: Session = Depends(get_db)):
    """El logo propio del evento para la vista pública (el de Golden y «sin logo» no pasan por aquí)."""
    from app.storage import get_storage
    event, err = _api_event(token, request, db)
    if err is not None:
        return err
    if event.logo_mode != "custom" or not event.logo_path or not get_storage().exists(event.logo_path):
        return _json_gone()
    return get_storage().response(event.logo_path, headers={"Cache-Control": "private, max-age=300", "X-Robots-Tag": "noindex"})


@public_router.get("/ver/f/{token}")
def form_page(token: str, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "page", PAGE_MAX):
        return _gone(429)
    link = stats_links.resolve(db, token, "form")
    form = db.get(WebForm, link.form_id) if link and link.form_id else None
    event = _event_of(db, link) if link else None
    if link is None or form is None or event is None or form.event_id != event.id:
        return _gone()
    _touch(db, link)
    from app.main import templates
    return templates.TemplateResponse(request=request, name="form_stats.html", headers=NO_STORE, context={
        "api_url": f"/api/ver/{token}/form-stats", "form_name": form.name, "event_name": event.name, "staff_name": "", "back_url": "", "back_label": "", "client_view": True,
        "public_view": {"until": to_local(link.expires_at).strftime("%d/%m/%Y %H:%M")}})


def _api_event(token: str, request: Request, db: Session):
    if _limited(request, "api", API_MAX):
        return None, _json_gone(429)
    link = stats_links.resolve(db, token, "event")
    event = _event_of(db, link) if link else None
    return (event, None) if event is not None else (None, _json_gone())


@public_router.get("/api/ver/{token}/stats/variables")
def public_variables(token: str, request: Request, db: Session = Depends(get_db)):
    event, err = _api_event(token, request, db)
    return err or JSONResponse(stats_router.variables_for(db, event), headers=NO_STORE)


@public_router.get("/api/ver/{token}/stats/data")
def public_data(token: str, variable: str, request: Request, db: Session = Depends(get_db)):
    event, err = _api_event(token, request, db)
    if err:
        return err
    try:
        return JSONResponse(stats_router.data_for(db, event, variable), headers=NO_STORE)
    except HTTPException as e:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code, headers=NO_STORE)


@public_router.get("/api/ver/{token}/analytics/registro")
def public_analytics(token: str, request: Request, db: Session = Depends(get_db)):
    event, err = _api_event(token, request, db)
    if err:
        return err
    dash = analytics_router.registro_dashboard(db, event)
    dash["charts"] = [c for c in dash.get("charts", []) if c.get("id") != "by_operator"]      # los nombres del personal no salen por el enlace
    return JSONResponse(dash, headers=NO_STORE)


@public_router.get("/api/ver/{token}/form-stats")
def public_form_stats(token: str, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "api", API_MAX):
        return _json_gone(429)
    link = stats_links.resolve(db, token, "form")
    form = db.get(WebForm, link.form_id) if link and link.form_id else None
    if link is None or form is None or form.event_id != link.event_id:
        return _json_gone()
    return JSONResponse(form_stats.build(db, form, False), headers=NO_STORE)
