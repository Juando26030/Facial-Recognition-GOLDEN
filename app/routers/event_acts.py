"""Acta de novedades del evento (Fase 10, tabla event_acts, 0126). Lógica pura en app/event_acts.py.

  GET    /api/events/{id}/acts                 lista (coordinador+ y el cliente del evento)
  POST   /api/events/{id}/acts                 crea (título, formato text|list, texto)               coordinador / admin / super_admin
  GET    /api/events/{id}/acts/{aid}           detalle
  PUT    /api/events/{id}/acts/{aid}           cambia el texto; con firmas puestas exige {"confirm_reset": true} (las quita); firmada = no se cambia
  DELETE /api/events/{id}/acts/{aid}           borra un acta SIN firmas
  POST   /api/events/{id}/acts/{aid}/sign      {"signature": "data:image/png;base64,…"}: firma quien llama — el cliente la suya, el coordinador la suya
  GET    /api/events/{id}/acts/{aid}/signature/{coordinator|client}   imagen PNG
  GET    /api/events/{id}/acts/{aid}/print     documento imprimible (HTML); ?download=1 lo descarga
Nada de datos personales en logs: la auditoría guarda ids y nunca el texto del acta."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import audit_actions, event_acts, event_archive
from app.auth import effective_roles, get_event_for_staff, get_current_staff
from app.database import get_db
from app.models import Event, EventAct, StaffUser
from app.storage import get_storage
from app.timeutil import utcnow

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
WRITERS = {"coordinador", "admin", "super_admin"}          # la comercial «pura» ve el acta pero no la escribe ni la firma por el cliente (decisión: es del equipo de campo)


def _can_write(staff: StaffUser) -> bool:
    return bool(effective_roles(staff) & WRITERS)


def _viewer(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    """Coordinador+ (incluida la comercial) y el cliente del evento; el digitador no."""
    roles = effective_roles(staff)
    if staff.role == "digitador" or not (roles & (WRITERS | {"comercial", "cliente"})):
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
    return staff


def _writer(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if not _can_write(staff):
        raise HTTPException(status_code=403, detail="Solo el coordinador o un administrador escribe el acta")
    return staff


def _act(db: Session, event: Event, act_id: int, lock: bool = False) -> EventAct:
    q = db.query(EventAct).filter(EventAct.id == act_id, EventAct.event_id == event.id)
    act = (q.with_for_update() if lock else q).first()
    if act is None:
        raise HTTPException(status_code=404, detail="Acta no encontrada")
    return act


def _iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def _out(act: EventAct, full: bool = True) -> dict:
    out = {"id": act.id, "title": act.title, "format": act.format, "status": event_acts.status_of(act), "status_label": event_acts.STATUS_LABEL[event_acts.status_of(act)],
           "coordinator_signed": bool(act.coordinator_sig_key), "coordinator_name": act.coordinator_name, "coordinator_signed_at": _iso(act.coordinator_signed_at),
           "client_signed": bool(act.client_sig_key), "client_name": act.client_name, "client_signed_at": _iso(act.client_signed_at),
           "created_at": _iso(act.created_at), "updated_at": _iso(act.updated_at)}
    if full:
        out["body"] = act.body
    return out


def _event(event_id: int, db: Session, staff: StaffUser) -> Event:
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return event


def _delete_signatures(act: EventAct) -> None:
    for attr in ("coordinator_sig_key", "client_sig_key"):
        key = getattr(act, attr)
        if key:
            get_storage().delete(key)
        setattr(act, attr, None)
    act.coordinator_name = act.client_name = None
    act.coordinator_signed_by_id = act.client_signed_by_id = None
    act.coordinator_signed_at = act.client_signed_at = None
    act.content_hash = None


@router.get("/events/{event_id}/acts")
def list_acts(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_viewer)):
    event = _event(event_id, db, staff)
    rows = db.query(EventAct).filter(EventAct.event_id == event.id).order_by(EventAct.created_at.desc(), EventAct.id.desc()).all()
    return JSONResponse({"acts": [_out(a, full=False) for a in rows], "can_write": _can_write(staff), "is_client": staff.role == "cliente"}, headers=NO_STORE)


@router.post("/events/{event_id}/acts")
def create_act(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_writer)):
    event = _event(event_id, db, staff)
    try:
        f = event_acts.clean_fields(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    now = utcnow()
    act = EventAct(event_id=event.id, created_by_id=staff.id, created_at=now, updated_at=now, **f)
    db.add(act)
    db.flush()
    audit_actions.record(db, staff, "create", "event_act", act.id, None, f"evento {event.id}")
    db.commit()
    return JSONResponse(_out(act), headers=NO_STORE)


@router.get("/events/{event_id}/acts/{act_id}")
def get_act(event_id: int, act_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_viewer)):
    event = _event(event_id, db, staff)
    return JSONResponse(_out(_act(db, event, act_id)), headers=NO_STORE)


@router.put("/events/{event_id}/acts/{act_id}")
def update_act(event_id: int, act_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_writer)):
    event = _event(event_id, db, staff)
    act = _act(db, event, act_id, lock=True)
    status = event_acts.status_of(act)
    if status == "firmada":
        raise HTTPException(status_code=409, detail="El acta ya tiene las dos firmas y no se puede cambiar. Crea otra acta si hace falta.")
    try:
        f = event_acts.clean_fields(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    changed = (f["title"], f["format"], f["body"]) != (act.title, act.format, act.body)
    if changed and status == "firma_pendiente":
        if not data.get("confirm_reset"):
            raise HTTPException(status_code=409, detail="El acta ya tiene una firma. Si cambias el texto, esa firma se quita y hay que firmar de nuevo.")
        _delete_signatures(act)
    act.title, act.format, act.body = f["title"], f["format"], f["body"]
    act.updated_at = utcnow()
    audit_actions.record(db, staff, "update", "event_act", act.id, None, f"evento {event.id}")
    db.commit()
    return JSONResponse(_out(act), headers=NO_STORE)


@router.delete("/events/{event_id}/acts/{act_id}")
def delete_act(event_id: int, act_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_writer)):
    event = _event(event_id, db, staff)
    act = _act(db, event, act_id, lock=True)
    if event_acts.status_of(act) != "borrador":
        raise HTTPException(status_code=409, detail="Un acta con firmas no se borra")
    db.delete(act)
    audit_actions.record(db, staff, "delete", "event_act", act_id, None, f"evento {event.id}")
    db.commit()
    return {"message": "Acta borrada"}


@router.post("/events/{event_id}/acts/{act_id}/sign")
def sign_act(event_id: int, act_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_viewer)):
    """Firma quien llama, nunca otra persona: el rol «cliente» pone la firma del cliente; el coordinador / admin / super_admin, la del coordinador."""
    event = _event(event_id, db, staff)
    side = "client" if staff.role == "cliente" else ("coordinator" if _can_write(staff) else None)
    if side is None:
        raise HTTPException(status_code=403, detail="Tu rol no firma el acta")
    try:
        blob = event_acts.decode_signature(data.get("signature"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    act = _act(db, event, act_id, lock=True)
    if getattr(act, f"{side}_sig_key"):
        raise HTTPException(status_code=409, detail="Esta parte ya firmó el acta")
    key = event_acts.sig_key(event.tenant_id, event.id, act.id, side, uuid.uuid4().hex)
    get_storage().put(key, blob)
    setattr(act, f"{side}_sig_key", key)
    setattr(act, f"{side}_name", (staff.full_name or staff.username)[:160])
    setattr(act, f"{side}_signed_by_id", staff.id)
    setattr(act, f"{side}_signed_at", utcnow())
    act.content_hash = event_acts.content_hash(act.title, act.format, act.body)
    act.updated_at = utcnow()
    audit_actions.record(db, staff, "sign", "event_act", act.id, None, f"evento {event.id}, firma {side}")
    db.commit()
    return JSONResponse(_out(act), headers=NO_STORE)


@router.get("/events/{event_id}/acts/{act_id}/signature/{side}")
def get_signature(event_id: int, act_id: int, side: str, db: Session = Depends(get_db), staff: StaffUser = Depends(_viewer)):
    if side not in ("coordinator", "client"):
        raise HTTPException(status_code=404, detail="Sin firma")
    event = _event(event_id, db, staff)
    key = getattr(_act(db, event, act_id), f"{side}_sig_key")
    if not key or not get_storage().exists(key):
        raise HTTPException(status_code=404, detail="Sin firma")
    return get_storage().response(key, media_type="image/png", headers=NO_STORE)


@router.get("/events/{event_id}/acts/{act_id}/print")
def print_act(event_id: int, act_id: int, download: int = 0, db: Session = Depends(get_db), staff: StaffUser = Depends(_viewer)):
    event = _event(event_id, db, staff)
    act = _act(db, event, act_id)

    def read(attr):
        key = getattr(act, attr)
        return get_storage().get(key) if key and get_storage().exists(key) else None
    html_doc = event_acts.render_html(event, act, read("coordinator_sig_key"), read("client_sig_key"), company=event.tenant.name if event.tenant else "")
    headers = dict(NO_STORE)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="acta_{act.id}.html"'
    return HTMLResponse(html_doc, headers=headers)
