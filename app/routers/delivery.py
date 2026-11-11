"""Entrega al cliente de un evento Facturado (Fase 5, B). Lógica en app/delivery.py; preguntas en app/survey_def.py.

Personal (comercial, admin, super_admin):
  GET  /api/events/{id}/delivery              estado: ¿se puede entregar?, enlace, ¿hay base final?, ¿ya contestaron la encuesta?, a quién iría el correo
  POST /api/events/{id}/delivery/link         asegura el enlace (lo crea si no hay); {"regenerate": true} revoca el anterior y crea otro
  POST /api/events/{id}/delivery/send-email   {"confirm": true}: encola el correo al contacto registrado del cliente (la casilla de la pantalla viene DESMARCADA)
Público (sin sesión; servicio `publico`): todo bajo /entrega/<token>
  GET  /entrega/{token}            página: saludo, evento, encuesta; después de enviarla, el botón «Descargar base de datos»
  POST /entrega/{token}/encuesta   envía la encuesta (una por evento)
  GET  /entrega/{token}/base       descarga la base final (solo con la encuesta enviada)"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import delivery, jobs, publicurl, security, survey_def
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import Event, StaffUser, Tenant
from app.storage import get_storage
from app.ttlcache import SlidingLimiter

log = logging.getLogger("golden.delivery")
router = APIRouter()               # /api/... (personal)
public_router = APIRouter()        # /entrega/... (con el enlace)
STAFF = require_role("comercial")
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
_limiter = SlidingLimiter()
PAGE_MAX, SUBMIT_MAX, DOWNLOAD_MAX, WINDOW_S = 60, 10, 20, 600


# ------------------------------------------------------------------------------------------------ Personal
def _state(db: Session, event: Event, request: Request) -> dict:
    billed = delivery.is_billed(event)
    link = delivery.active_link(db, event.id) if billed else None
    contact = delivery.client_contact(db, event)
    fdb = delivery.final_db(event)
    return {"eligible": billed, "link": delivery.url_for_link(link, str(request.base_url)) if link is not None else None, "link_created_at": (link.created_at.isoformat(timespec="seconds") + "Z") if link else None,
            "last_opened_at": (link.last_opened_at.isoformat(timespec="seconds") + "Z") if link and link.last_opened_at else None,
            "has_final_db": fdb is not None, "final_db_name": fdb[1] if fdb else "", "survey_done": delivery.survey_done(db, event.id),
            "recipient": contact["email"] if contact else None, "recipient_source": contact["source"] if contact else None,
            "mail_recent": bool(link is not None and delivery.mail_sent_recently(db, link.id)), "public_url_ready": bool(publicurl.base(str(request.base_url)))}


@router.get("/events/{event_id}/delivery")
def get_delivery(event_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    return JSONResponse(_state(db, event, request), headers=NO_STORE)


def _require_billed(event: Event) -> None:
    if not delivery.is_billed(event):
        raise HTTPException(status_code=409, detail="La entrega al cliente solo está disponible cuando el evento está Facturado.")


@router.post("/events/{event_id}/delivery/link")
def post_link(event_id: int, request: Request, data: dict = None, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    _require_billed(event)
    if not publicurl.base(str(request.base_url)):
        raise HTTPException(status_code=400, detail="Falta PUBLIC_BASE_URL: no se puede armar el enlace de entrega.")
    delivery.ensure_link(db, event, staff, regenerate=bool((data or {}).get("regenerate")))
    db.commit()
    return JSONResponse(_state(db, event, request), headers=NO_STORE)


@router.post("/events/{event_id}/delivery/send-email")
def post_send_email(event_id: int, request: Request, data: dict = None, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Solo con `confirm: true` (la casilla «Enviar al correo del cliente» de la pantalla, desmarcada por defecto). Un correo por enlace y hora."""
    event = get_event_for_staff(event_id, db, staff)
    _require_billed(event)
    if (data or {}).get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Marque «Enviar al correo del cliente» para confirmar el envío.")
    base = publicurl.base(str(request.base_url))
    if not base:
        raise HTTPException(status_code=400, detail="Falta PUBLIC_BASE_URL: no se puede armar el enlace de entrega.")
    if delivery.final_db(event) is None:
        raise HTTPException(status_code=409, detail="Todavía no se ha subido la base de datos final del evento: el cliente no tendría qué descargar.")
    contact = delivery.client_contact(db, event)
    if contact is None:
        raise HTTPException(status_code=409, detail="El cliente de este evento no tiene un correo de contacto registrado. Agréguelo en Clientes o copie el enlace y envíelo a mano.")
    link = delivery.ensure_link(db, event, staff)
    if delivery.mail_sent_recently(db, link.id):
        raise HTTPException(status_code=429, detail="El correo ya se envió hace menos de una hora. Si no llegó, revise el spam o espere un momento.")
    delivery.enqueue_mail(db, event, link, base, staff)
    db.commit()
    jobs.kick()
    return JSONResponse({"ok": True, "queued": True, "recipient": contact["email"]}, headers=NO_STORE)


# ------------------------------------------------------------------------------------------------ Público
def _limited(request: Request, kind: str, max_hits: int) -> bool:
    ip = security.limit_ip(request)
    return ip is not None and not _limiter.hit((kind, ip), max_hits, WINDOW_S)


def _gone_page(request: Request, message: str = delivery.MSG_UNAVAILABLE, status: int = 404) -> HTMLResponse:
    from app.main import templates      # import tardio: main.py importa este módulo
    return templates.TemplateResponse(request=request, name="entrega.html", status_code=status, headers=NO_STORE,
                                      context={"unavailable": message, "event_name": "", "company": "", "event_date": "", "survey": None, "state": None})


def _json(detail: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"detail": detail, **extra}, status_code=status, headers=NO_STORE)


def _load(db: Session, token: str):
    link = delivery.resolve(db, token)
    event = db.get(Event, link.event_id) if link else None
    return (link, event) if link is not None and event is not None else (None, None)


@public_router.get("/entrega/{token}")
def page(token: str, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "page", PAGE_MAX):
        return _gone_page(request, "Demasiados intentos. Espere unos minutos y vuelva a abrir el enlace.", 429)
    link, event = _load(db, token)
    if link is None:
        return _gone_page(request)
    state = delivery.check_state(db, link, event)
    if not state["ok"]:
        return _gone_page(request, state["message"], 404)
    delivery.touch(db, link)
    tenant = db.get(Tenant, event.tenant_id)
    from app.main import templates
    return templates.TemplateResponse(request=request, name="entrega.html", headers=NO_STORE, context={
        "unavailable": "", "event_name": event.name, "company": tenant.name if tenant is not None else "",
        "event_date": event.start_date.strftime("%d/%m/%Y") if event.start_date else "", "survey": survey_def.public_definition(), "state": state,
        "download_url": f"/entrega/{token}/base", "submit_url": f"/entrega/{token}/encuesta"})


@public_router.post("/entrega/{token}/encuesta")
def submit(token: str, data: dict, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "submit", SUBMIT_MAX):
        return _json("Demasiados intentos. Espere unos minutos.", 429)
    link, event = _load(db, token)
    if link is None:
        return _json(delivery.MSG_UNAVAILABLE, 404)
    state = delivery.check_state(db, link, event)
    if not state["ok"]:
        return _json(state["message"], 404)
    try:
        resp = delivery.submit_survey(db, link, event, data, security.limit_ip(request))
    except survey_def.SurveyError as exc:
        return _json(str(exc), 400)
    except delivery.AlreadySubmitted:
        return _json(delivery.MSG_ALREADY, 409, survey_done=True, can_download=delivery.final_db(event) is not None)       # no se reemplaza: la primera respuesta es la válida
    log.info("encuesta de entrega recibida (evento %s)", event.id)
    if getattr(resp, "next_event_queued", False):
        jobs.kick()                                            # aviso «próximo evento» a la comercial
    return JSONResponse({"ok": True, "survey_done": True, "can_download": delivery.final_db(event) is not None, "has_db": delivery.final_db(event) is not None}, headers=NO_STORE)


@public_router.get("/entrega/{token}/base")
def download(token: str, request: Request, db: Session = Depends(get_db)):
    if _limited(request, "download", DOWNLOAD_MAX):
        return _json("Demasiados intentos. Espere unos minutos.", 429)
    link, event = _load(db, token)
    if link is None:
        return _json(delivery.MSG_UNAVAILABLE, 404)
    state = delivery.check_state(db, link, event)
    if not state["ok"]:
        return _json(state["message"], 404)
    if not state["survey_done"]:
        return _json(delivery.MSG_NEEDS_SURVEY, 403)
    fdb = delivery.final_db(event)
    storage = get_storage()
    if fdb is None or not storage.exists(fdb[0]):
        return _json(delivery.MSG_NO_DB, 404)
    if delivery.downloads_last_hour(db, link.id) >= delivery.DOWNLOADS_PER_HOUR:
        return _json(delivery.MSG_DOWNLOAD_LIMIT, 429)
    delivery.record_download(db, link, event)
    db.commit()
    key, name = fdb
    return storage.response(key, filename=name, headers=NO_STORE)
