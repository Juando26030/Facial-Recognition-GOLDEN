"""Fase 1B · reimpresión con permisos: rutas (docs/1B_reimpresion_permisos.md). La lógica y la auditoría viven en app/reprint.py.

  Digitador:    POST …/reprint-requests (pedir) · GET …/reprint-requests/mine (cómo va) · POST …/reprint-requests/use (gastar el permiso en la impresión local/USB; la compartida lo gasta el servidor en print-jobs)
  Coordinador:  GET /reprint-requests/inbox (sondeo de su pantalla; marca «vista») · POST /reprint-requests/{id}/decision · GET …/events/{id}/reprint-requests (historial con auditoría)
  Admin+:       PUT …/events/{id}/reprint-mode
  Público:      GET/POST /reimpresion/{token} (enlace de correo de un solo uso: el GET solo muestra, la decisión es un POST)"""
import logging
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import reprint, security
from app.auth import assert_event_tenant, effective_roles, get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import Event, EventAttendee, ReprintAudit, ReprintLink, ReprintRequest, StaffUser
from app.timeutil import utcnow
from app.ttlcache import SlidingLimiter

log = logging.getLogger("golden.reprint")
router = APIRouter()
public_router = APIRouter()
_limiter = SlidingLimiter()                                     # en memoria (por proceso), como las páginas públicas de formularios: frena a quien prueba enlaces
LINK_GET_MAX, LINK_POST_MAX, LINK_WINDOW_S = 40, 12, 600

OPERATOR = require_role_excluding("digitador", ("comercial",))
DECIDER = require_role_excluding("coordinador", ("comercial",))
ADMIN = require_role("admin")


def _row(db: Session, r: ReprintRequest, event: Event = None) -> dict:
    requester = db.get(StaffUser, r.requested_by_staff_id) if r.requested_by_staff_id else None
    event = event or db.get(Event, r.event_id)
    return {"id": r.id, "event_id": r.event_id, "event_name": event.name if event else "", "user_id": r.user_id, "person": reprint.person_name(db, r.tenant_id, r.user_id),
            "requested_by": reprint.staff_name(requester), "requested_at": reprint.iso(r.requested_at), "requested_hhmm": reprint.hhmm(r.requested_at), "expires_at": reprint.iso(r.expires_at), "status": r.status}


# ------------------------------------------------------------------------------------------------ Parámetros (admin+)
@router.put("/events/{event_id}/reprint-mode")
def set_mode(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Reimpresión del evento: habilitada (por defecto) o deshabilitada. SOLO admin o super_admin."""
    event = get_event_for_staff(event_id, db, staff)
    if not reprint.can_decide(event, staff):
        raise HTTPException(status_code=404, detail="Evento no encontrado")      # otro cliente (tenant)
    value = data.get("disabled")
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="«disabled» debe ser verdadero o falso")
    changed = bool(event.reprint_disabled) != value
    event.reprint_disabled = value
    db.commit()
    if changed:
        log.info("reimpresión: evento %s %s", event.id, "DESHABILITADA" if value else "habilitada")
    return {"disabled": value}


@router.get("/events/{event_id}/reprint-requests")
def history(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DECIDER)):
    """Historial de solicitudes de ESTE evento con su cadena de auditoría. Solo quien decide en él (su coordinador o admin+)."""
    event = get_event_for_staff(event_id, db, staff)
    if not reprint.can_decide(event, staff):
        raise HTTPException(status_code=403, detail="Solo el coordinador de este evento o un administrador ve este historial.")
    reprint.expire_due(db, event.id)
    db.commit()
    out = []
    for r in db.query(ReprintRequest).filter(ReprintRequest.event_id == event.id).order_by(ReprintRequest.id.desc()).limit(50).all():
        steps = [{"kind": a.kind, "at": reprint.iso(a.at), "by": reprint.staff_name(db.get(StaffUser, a.staff_id)) if a.staff_id else None, "channel": a.channel}
                 for a in db.query(ReprintAudit).filter_by(request_id=r.id).order_by(ReprintAudit.id)]
        out.append({**_row(db, r, event), "audit": steps})
    return {"disabled": bool(event.reprint_disabled), "requests": out}


# ------------------------------------------------------------------------------------------------ Digitador
def _attendee(db: Session, event: Event, user_id: str) -> EventAttendee:
    att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=str(user_id).strip()).first()
    if att is None:
        raise HTTPException(status_code=404, detail="La persona no está inscrita en este evento.")
    return att


@router.post("/events/{event_id}/reprint-requests")
def create(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Pide permiso para reimprimir. Solo si la reimpresión está deshabilitada, la persona ya se imprimió y quien pide no decide en este evento. Quien no pertenece al evento recibe el 403/404 de siempre."""
    event = get_event_for_staff(event_id, db, staff)
    uid = _attendee(db, event, data.get("user_id")).user_id
    if not reprint.is_locked_for(event, staff):
        raise HTTPException(status_code=409, detail="En este evento puedes reimprimir sin permiso.")
    if not reprint.already_printed(db, event, uid):
        raise HTTPException(status_code=409, detail="A esta persona todavía no se le imprimió la escarapela: no necesitas permiso.")
    req, created = reprint.create_request(db, event, staff, uid)
    db.commit()
    if created:
        reprint.kick_notify(req)
        log.info("reimpresión: solicitud %s creada (evento %s)", req.id, event.id)
    return {**reprint.view(req), "created": created}


@router.get("/events/{event_id}/reprint-requests/mine")
def mine(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Cómo va mi solicitud para esta persona (pendiente / aprobada / negada / vencida) — lo consulta la pantalla del digitador mientras espera."""
    event = get_event_for_staff(event_id, db, staff)
    out = reprint.state_for(db, event, staff, str(user_id).strip())
    db.commit()
    return out


@router.post("/events/{event_id}/reprint-requests/use")
def use(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Gasta el permiso aprobado ANTES de imprimir en el propio equipo (USB o ventana de Chrome). La impresión compartida lo gasta el servidor en print-jobs. 403 si no hay permiso vigente."""
    event = get_event_for_staff(event_id, db, staff)
    uid = str(data.get("user_id") or "").strip()
    reprint.gate(db, event, staff, uid, "local")
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ Coordinador
@router.get("/reprint-requests/inbox")
def inbox(db: Session = Depends(get_db), staff: StaffUser = Depends(DECIDER)):
    """Solicitudes pendientes que le tocan a esta persona: las de los eventos que coordina; las de eventos sin coordinador, solo a admin+. Consultarlas marca «vista en pantalla» (así el respaldo por correo sabe que hay sesión activa)."""
    now = utcnow()
    admin = bool(reprint.ADMIN_ROLES & effective_roles(staff))
    q = db.query(ReprintRequest).filter(ReprintRequest.status == "pending", ReprintRequest.expires_at > now)
    scope = [Event.coordinator_staff_id == staff.id] + ([Event.coordinator_staff_id.is_(None)] if admin else [])
    q = q.filter(ReprintRequest.event_id.in_(select(Event.id).where(or_(*scope))))
    if staff.tenant_id is not None:
        q = q.filter(ReprintRequest.tenant_id == staff.tenant_id)             # solo su cliente (tenant)
    rows = q.order_by(ReprintRequest.id).limit(20).all()
    fresh = [r.id for r in rows if r.screen_seen_at is None]
    for rid in fresh:
        if db.execute(update(ReprintRequest).where(ReprintRequest.id == rid, ReprintRequest.screen_seen_at.is_(None)).values(screen_seen_at=now)).rowcount:
            reprint.audit(db, rid, "screen", staff.id, "screen")
    if fresh:
        db.commit()
    out = [_row(db, r) for r in rows]
    watch = bool(out) or reprint.watching(db, staff)
    return {"requests": out, "watch": watch, "poll_ms": 10000 if out else 30000}      # sin eventos con reimpresión deshabilitada la pantalla deja de sondear; 30 s sin pendientes, 10 s con alguna


@router.post("/reprint-requests/{request_id}/decision")
def decision(request_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(DECIDER)):
    req = db.get(ReprintRequest, request_id)
    event = db.get(Event, req.event_id) if req is not None else None
    assert_event_tenant(event, staff) if event is not None else None
    if req is None or event is None or not reprint.can_decide(event, staff):
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")           # 404 también al coordinador de otro evento: no se confirma que existe
    choice = data.get("decision")
    if choice not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="La decisión debe ser «approve» o «deny».")
    if not reprint.decide(db, req.id, staff.id, choice == "approve", "screen"):
        db.commit()
        raise HTTPException(status_code=409, detail="Esta solicitud ya fue respondida o venció.")
    db.commit()
    return {"status": "approved" if choice == "approve" else "denied"}


# ------------------------------------------------------------------------------------------------ Enlace de correo (público)
_CSS = ("body{margin:0;font-family:Arial,sans-serif;font-size:16px;line-height:1.5;background:#f4f5f9;color:#1b1d2a}main{max-width:520px;margin:6vh auto 0;padding:24px 20px;background:#fff;border-radius:16px;box-shadow:0 6px 24px rgba(10,14,46,.08)}"
        "h1{font-size:1.3rem;margin:0 0 12px;color:#0a0e2e}dl{margin:16px 0}dt{font-size:.9rem;color:#4a4d5c}dd{margin:0 0 10px;font-weight:700}"
        "button{min-height:48px;min-width:48px;padding:10px 22px;border-radius:10px;border:2px solid #0a0e2e;font-size:1rem;font-weight:700;cursor:pointer;margin:6px 8px 6px 0}"
        ".ok{background:#0a0e2e;color:#fff}.no{background:#fff;color:#0a0e2e}")


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (f"<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><meta name=\"robots\" content=\"noindex\">"
            f"<title>{title}</title><style>{_CSS}</style></head><body><main>{body}</main></body></html>")
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})


def _dead() -> HTMLResponse:
    """El mismo mensaje para un enlace desconocido, usado, vencido o ya respondido: no se confirma nada a quien lo adivina."""
    return _page("Enlace no disponible", "<h1>Este enlace ya no está disponible</h1><p>Ya se usó, venció o la solicitud ya fue respondida. Si hace falta, pide una nueva desde el Registro.</p>", 410)


def _limited(request: Request, kind: str, max_hits: int) -> bool:
    ip = security.limit_ip(request)
    return ip is not None and not _limiter.hit((kind, ip), max_hits, LINK_WINDOW_S)


def _too_many() -> HTMLResponse:
    return _page("Demasiados intentos", "<h1>Demasiados intentos seguidos</h1><p>Espera unos minutos e intenta de nuevo.</p>", 429)


def _live_link(db: Session, token: str):
    link = db.query(ReprintLink).filter(ReprintLink.token_hash == reprint.hash_token(token)).first()
    if link is None or link.used_at is not None:
        return None, None
    req = db.get(ReprintRequest, link.request_id)
    if req is None or req.status != "pending" or req.expires_at <= utcnow():
        return None, None
    return link, req


@public_router.get("/reimpresion/{token}")
def link_page(token: str, request: Request, db: Session = Depends(get_db)):
    """SOLO muestra la solicitud y los dos botones. Nunca aprueba ni niega: los escáneres de correo abren los enlaces."""
    if _limited(request, "get", LINK_GET_MAX):
        return _too_many()
    link, req = _live_link(db, token)
    if link is None:
        return _dead()
    row = _row(db, req)
    e = escape
    body = (f"<h1>Permiso para reimprimir una escarapela</h1>"
            f"<dl><dt>Evento</dt><dd>{e(row['event_name'])}</dd><dt>Lo pide</dt><dd>{e(row['requested_by'])}</dd><dt>Escarapela de</dt><dd>{e(row['person'])}</dd>"
            f"<dt>Hora del pedido</dt><dd>{e(row['requested_hhmm'])}</dd></dl>"
            f"<p>Si apruebas, se podrá reimprimir <b>una sola vez</b> y el permiso vence en {reprint.approval_minutes()} minutos.</p>"
            f"<form method=\"post\" action=\"/reimpresion/{e(token)}\"><button class=\"ok\" type=\"submit\" name=\"decision\" value=\"approve\">Aprobar</button>"
            f"<button class=\"no\" type=\"submit\" name=\"decision\" value=\"deny\">Negar</button></form>")
    return _page("Permiso de reimpresión", body)


@public_router.post("/reimpresion/{token}")
def link_decide(token: str, request: Request, decision: str = Form(""), db: Session = Depends(get_db)):
    """La decisión (POST; el Origin lo revisa el middleware CSRF). El enlace se gasta primero con un UPDATE atómico: dos clics o dos dispositivos no deciden dos veces."""
    if _limited(request, "post", LINK_POST_MAX):
        return _too_many()
    if decision not in ("approve", "deny"):
        return _dead()
    link, req = _live_link(db, token)
    if link is None:
        return _dead()
    won = db.execute(update(ReprintLink).where(ReprintLink.id == link.id, ReprintLink.used_at.is_(None)).values(used_at=utcnow())).rowcount
    if not won:
        db.rollback()
        return _dead()
    ok = reprint.decide(db, req.id, link.staff_id, decision == "approve", "email")
    db.commit()
    if not ok:
        return _dead()
    if decision == "approve":
        return _page("Permiso aprobado", f"<h1>Permiso aprobado</h1><p>Se podrá reimprimir una sola vez y vence en {reprint.approval_minutes()} minutos. Ya puedes cerrar esta página.</p>")
    return _page("Permiso negado", "<h1>Permiso negado</h1><p>No se reimprimirá la escarapela. Ya puedes cerrar esta página.</p>")

