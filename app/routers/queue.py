"""Turnos y filas (Fase 8, pieza 2). Personal: configuración, asignar, llamar, TV. Público (sin login): /turno/{evento}, la persona ve su turno.
Lo que se sondea (página pública y TV) sale de la memoria (app/queue_svc.snapshot); solo las acciones del personal tocan la base."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app import event_archive, queue_svc, queue_turns as qt, security
from app.auth import get_event_for_staff, require_event_in_progress, require_role_excluding
from app.database import get_db
from app.login_control import poll_allowed
from app.models import Event, StaffUser

router = APIRouter()
public_router = APIRouter()        # sin prefijo /api: /turno/...

CONFIG_ROLE = require_role_excluding("coordinador", ("comercial",))
OPERATE_ROLE = require_role_excluding("digitador", ("comercial",))
NO_STORE = {"Cache-Control": "no-store"}
LOOKUPS_PER_MIN = 12


def _err(e: qt.QueueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------------------------------------------------------------------ personal
@router.get("/events/{event_id}/queue/config")
def get_queue_config(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    cfg = queue_svc.get_config(event)
    return {"enabled": bool(event.queue_enabled), "config": cfg, "modes": list(qt.MODES), "public_path": f"/turno/{event.id}"}


@router.put("/events/{event_id}/queue/config")
def put_queue_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    from app import event_lease
    event_lease.assert_editable(event)
    try:
        cfg = queue_svc.set_config(db, event, bool(data.get("enabled")), data.get("config") or {})
    except qt.QueueError as e:
        raise _err(e)
    db.commit()
    return {"enabled": bool(event.queue_enabled), "config": cfg}


@router.post("/events/{event_id}/queue/assign")
def assign_turns(event_id: int, data: dict = None, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Crea los turnos que faltan según el modo configurado (arrival/form/alpha). `rebuild=true` borra antes los que siguen esperando."""
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    if not event.queue_enabled:
        raise HTTPException(status_code=400, detail="Activa «Turnos y filas» en Parámetros")
    mode = queue_svc.get_config(event)["mode"]
    if mode == "manual":
        raise HTTPException(status_code=400, detail="El orden manual se carga con el Excel")
    removed = queue_svc.reset_turns(db, event) if (data or {}).get("rebuild") else 0
    res = queue_svc.assign_batch(db, event, mode)
    db.commit()
    return {**res, "removed": removed}


@router.post("/events/{event_id}/queue/upload")
def upload_manual(event_id: int, file: UploadFile = File(...), rebuild: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    if not event.queue_enabled:
        raise HTTPException(status_code=400, detail="Activa «Turnos y filas» en Parámetros")
    cfg = queue_svc.get_config(event)
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El Excel es demasiado grande (máximo 10 MB)")
    try:
        parsed = queue_svc.read_manual_excel(data, file.filename or "turnos.xlsx", cfg["lanes"])
    except qt.QueueError as e:
        raise _err(e)
    removed = queue_svc.reset_turns(db, event) if rebuild else 0
    res = queue_svc.assign_batch(db, event, "manual", parsed)
    db.commit()
    return {**res, "removed": removed, "errors": parsed["errors"][:30], "errors_total": len(parsed["errors"]), "duplicates": int(parsed["duplicates"])}


@router.get("/events/{event_id}/queue/template")
def manual_template(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    body = queue_svc.manual_template(queue_svc.get_config(event)["lanes"])
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="plantilla_turnos.xlsx"'})


@router.get("/events/{event_id}/queue")
def queue_state(event_id: int, lane: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)          # la lista trae nombres de personas: con la base archivada solo la ve un super_admin
    snap = queue_svc.snapshot(db, event)
    return JSONResponse({**qt.tv_view(snap), "enabled": snap["enabled"], "mode": snap["mode"], "total": snap["total"],
                         "listing": queue_svc.queue_listing(db, event, lane.strip().upper() or None)}, headers=NO_STORE)


@router.get("/events/{event_id}/queue/tv")
def queue_tv_state(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    snap = queue_svc.snapshot(db, event)
    return JSONResponse({**qt.tv_view(snap), "enabled": snap["enabled"], "event_name": snap["event_name"]}, headers=NO_STORE)


def _operate(event_id: int, db: Session, staff: StaffUser) -> Event:
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    if not event.queue_enabled:
        raise HTTPException(status_code=400, detail="«Turnos y filas» está apagado")
    return event


@router.post("/events/{event_id}/queue/call")
def call_next(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = _operate(event_id, db, staff)
    try:
        t = queue_svc.call_next(db, event, staff.id, data.get("lane"), data.get("desk"))
    except qt.QueueError as e:
        raise _err(e)
    db.commit()
    return {"called": qt.label(t.lane, t.number) if t else None, "id": t.id if t else None}


@router.post("/events/{event_id}/queue/repeat")
def repeat_call(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = _operate(event_id, db, staff)
    try:
        t = queue_svc.repeat_call(db, event, staff.id, data.get("lane"))
    except qt.QueueError as e:
        raise _err(e)
    db.commit()
    return {"called": qt.label(t.lane, t.number) if t else None}


@router.post("/events/{event_id}/queue/turns/{turn_id}/{action}")
def turn_action(event_id: int, turn_id: int, action: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = _operate(event_id, db, staff)
    fn = {"skip": queue_svc.skip_turn, "requeue": queue_svc.requeue_turn, "done": queue_svc.finish_turn}.get(action)
    if fn is None:
        raise HTTPException(status_code=404, detail="Acción desconocida")
    try:
        t = fn(db, event, turn_id)
    except qt.QueueError as e:
        raise _err(e)
    db.commit()
    return {"label": qt.label(t.lane, t.number), "status": t.status}


# ------------------------------------------------------------------------------------------------------------------------ público (sin login)
def _public_event(db: Session, event_id: int) -> Event:
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event or not event.queue_enabled or event.archived_at is not None or event.data_archived_at is not None:
        raise HTTPException(status_code=404, detail="Turnos no disponibles")
    return event


def _page(request: Request, name: str, ctx: dict, status: int = 200):
    from app.main import templates  # import tardío
    return templates.TemplateResponse(request=request, name=name, context=ctx, status_code=status, headers=NO_STORE)


@public_router.get("/turno/{event_id}", response_class=HTMLResponse)
def turn_entry(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = _public_event(db, event_id)
    return _page(request, "turno_public.html", {"event_id": event.id, "event_name": event.name, "token": ""})


@public_router.post("/turno/{event_id}/buscar")
def turn_lookup(event_id: int, data: dict, request: Request, db: Session = Depends(get_db)):
    """La persona escribe su cédula (o la trae el QR de la escarapela) y recibe el enlace de SU turno. Limitado por IP; no confirma si la cédula existe."""
    if not poll_allowed(f"turno:{security.client_ip(request)}", LOOKUPS_PER_MIN):
        raise HTTPException(status_code=429, detail="Demasiados intentos, espera un momento")
    event = _public_event(db, event_id)
    cedula = qt.clean_cedula(data.get("cedula"))
    turn = queue_svc.assign_one(db, event, cedula) if cedula else None
    if turn is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Aún no tienes turno. Si ya te registraste, pregunta en la mesa de ayuda.")
    db.commit()
    return JSONResponse({"token": turn.token}, headers=NO_STORE)


@public_router.get("/turno/{event_id}/{token}", response_class=HTMLResponse)
def turn_page(event_id: int, token: str, request: Request, db: Session = Depends(get_db)):
    event = _public_event(db, event_id)
    return _page(request, "turno_public.html", {"event_id": event.id, "event_name": event.name, "token": token})


@public_router.get("/turno/{event_id}/{token}/state")
def turn_state(event_id: int, token: str, request: Request, db: Session = Depends(get_db)):
    if not poll_allowed(f"turnost:{security.client_ip(request)}", 120):
        raise HTTPException(status_code=429, detail="Demasiadas consultas")
    snap = queue_svc.cached_public(event_id)              # F5-9 B: cientos de celulares sondeando cada ~6 s no consultan la base (ni el evento): salen de la memoria
    if snap is None:
        snap = queue_svc.snapshot(db, _public_event(db, event_id))
    if not snap.get("public_ok"):
        raise HTTPException(status_code=404, detail="Turnos no disponibles")
    view = qt.public_view(snap, token)
    if view is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    return JSONResponse(view, headers=NO_STORE)
