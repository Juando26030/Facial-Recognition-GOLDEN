"""Compromiso digital del digitador — lado del COORDINADOR (Fase 4; el lado público es el motor de formularios: `/f/<evento>/<enlace>`, ver app/pledge.py).

  GET    /api/events/{id}/pledge                  estado: ¿se exige?, enlace (si hay), si el texto exigido ya está disponible
  POST   /api/events/{id}/pledge/link             crear el formulario del evento / reabrir su enlace; {"regenerate": true} cambia el enlace (el anterior deja de existir)
  DELETE /api/events/{id}/pledge/link             revocar el enlace público (el compromiso se sigue exigiendo al ingresar)
  PUT    /api/events/{id}/pledge/enabled          {"enabled": bool}: exigir o no el compromiso en este evento
  GET    /api/events/{id}/pledge/state            por digitador del evento: firmó o no, cuándo, avisos (solo cuáles preguntas de salud respondió «Sí»; el detalle se abre aparte)
  GET    /api/events/{id}/pledge/{pid}/document   el compromiso firmado (HTML imprimible, sin datos sensibles)
  GET    /api/events/{id}/pledge/{pid}/health     el detalle sensible (descifrado): queda en audit_actions quién y cuándo, sin datos
  POST   /api/events/{id}/pledge/{pid}/allow-resign   permite que esa persona firme de nuevo (la firma anterior queda como historial)
Permisos: coordinador del evento (y de su cliente) y admin+. NUNCA la comercial pura. Nada de esto sale en listados masivos, exportaciones ni reportes."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import audit_actions, event_archive, formsvc, publicurl, pledge, pledge_texts
from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import Event, EventStaffAuthorization, EventStaffPledge, FormSubmission, StaffUser, WebForm
from app.storage import get_storage
from app.timeutil import utcnow

router = APIRouter()
MANAGER = require_role_excluding("coordinador", ("comercial",))
NO_STORE = {"Cache-Control": "no-store"}


def _out(db: Session, event: Event, request: Request) -> dict:
    form = pledge.form_for(db, event)
    link = None
    if form is not None and form.manual_status != "finalizado":
        link = f"{publicurl.base(str(request.base_url))}/f/{event.id}/{form.slug}"
    return {"enabled": bool(event.pledge_enabled), "link": link, "link_active": link is not None, "event_open": event.status != "finalizado" and event.archived_at is None,
            "text_available": pledge.text_available(), "sensitive": pledge.sensitive_enabled(), "text_approved": pledge_texts.APPROVED,
            "draft": pledge.sensitive_enabled() and not pledge_texts.APPROVED, "retention_days": formsvc.sensitive_retention_days()}


@router.get("/events/{event_id}/pledge")
def get_pledge(event_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    return JSONResponse(_out(db, event, request), headers=NO_STORE)


@router.post("/events/{event_id}/pledge/link")
def create_link(event_id: int, request: Request, data: dict = None, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    if event.status == "finalizado" or event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento ya finalizó: el compromiso no se puede publicar")
    pledge.create_or_regenerate(db, event, staff, regenerate=bool((data or {}).get("regenerate")))
    db.commit()
    return JSONResponse(_out(db, event, request), headers=NO_STORE)


@router.delete("/events/{event_id}/pledge/link")
def revoke_link(event_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    pledge.revoke(db, event, staff)
    db.commit()
    return JSONResponse(_out(db, event, request), headers=NO_STORE)


@router.put("/events/{event_id}/pledge/enabled")
def set_enabled(event_id: int, request: Request, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    event.pledge_enabled = bool(data.get("enabled"))
    audit_actions.record(db, staff, "pledge_required_on" if event.pledge_enabled else "pledge_required_off", "event", event.id, event.name)
    db.commit()
    return JSONResponse(_out(db, event, request), headers=NO_STORE)


@router.get("/events/{event_id}/pledge/state")
def pledge_state(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Una fila por digitador del evento. Solo banderas: lo sensible se abre aparte, una persona a la vez (`health`)."""
    event = get_event_for_staff(event_id, db, staff)
    required = pledge.required(event)
    staff_rows = (db.query(StaffUser.id).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
                  .filter(EventStaffAuthorization.event_id == event.id, StaffUser.role == "digitador").all())
    pledges = {p.staff_id: p for p in db.query(EventStaffPledge).filter(EventStaffPledge.event_id == event.id, EventStaffPledge.superseded_at.is_(None))}
    accounts = []
    for (sid,) in staff_rows:
        p = pledges.get(sid)
        accounts.append({"id": sid, "signed": p is not None, "blocked": bool(required and p is None), "pledge_id": p.id if p else None,
                         "signed_at": p.signed_at.isoformat() + "Z" if p else None, "attendance_confirmed": p.attendance_confirmed if p else None,
                         "understands_terms": p.understands_terms if p else None, "has_health_info": bool(p and p.has_health_info and p.health_purged_at is None),
                         "health_purged": bool(p and p.health_purged_at), "health_flags": [x for x in (p.health_flags or "").split(",") if x] if p and p.health_purged_at is None else [], "resign_allowed": bool(p and p.resign_allowed_at)})
    return JSONResponse({"required": required, "accounts": accounts}, headers=NO_STORE)


def _pledge(db: Session, event: Event, pledge_id: int) -> EventStaffPledge:
    row = db.query(EventStaffPledge).filter(EventStaffPledge.id == pledge_id, EventStaffPledge.event_id == event.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Compromiso no encontrado")
    return row


@router.get("/events/{event_id}/pledge/{pledge_id}/document")
def pledge_document(event_id: int, pledge_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    row = _pledge(db, event, pledge_id)
    if not row.doc_key or not get_storage().exists(row.doc_key):
        raise HTTPException(status_code=404, detail="El documento ya no está disponible")
    return HTMLResponse(get_storage().get(row.doc_key).decode("utf-8"), headers=NO_STORE)


@router.get("/events/{event_id}/pledge/{pledge_id}/health")
def pledge_health(event_id: int, pledge_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Detalle sensible de UNA persona. Queda en audit_actions quién lo abrió y cuándo (sin ningún dato de salud ni de la persona)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    row = _pledge(db, event, pledge_id)
    sub = db.get(FormSubmission, row.submission_id)
    raw = sub.sensitive_json if sub is not None else None
    if row.health_purged_at is not None or not raw:
        raise HTTPException(status_code=410, detail=f"Estos datos se borraron por retención ({formsvc.sensitive_retention_days()} días después de finalizado el evento)")
    design = formsvc.get_design(db.get(WebForm, sub.form_id))
    values = json.loads(raw)
    items = [{"label": design["fields"][fid]["label"], "value": values[fid]} for fid in design["fields"] if fid in values]
    data = json.loads(sub.data_json or "{}")
    phone = data.get(pledge.FID_PHONE)
    audit_actions.record(db, staff, "pledge_health_view", "event_pledge", row.id, event.name, f"evento {event.id}")
    db.commit()
    return JSONResponse({"items": items, "phone": phone}, headers=NO_STORE)


@router.post("/events/{event_id}/pledge/{pledge_id}/allow-resign")
def allow_resign(event_id: int, pledge_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    row = _pledge(db, event, pledge_id)
    if row.superseded_at is not None:
        raise HTTPException(status_code=409, detail="Ese compromiso ya fue reemplazado por uno más nuevo")
    row.resign_allowed_at = utcnow()
    audit_actions.record(db, staff, "pledge_resign_allowed", "event_pledge", row.id, event.name, f"evento {event.id}")
    db.commit()
    return {"message": "Esa persona podrá volver a firmar con el enlace del compromiso"}
