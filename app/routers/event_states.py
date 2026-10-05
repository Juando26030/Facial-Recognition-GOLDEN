"""Estados de evento configurables (docs/18 §4): el administrador crea los que quiera y le adjunta reglas a cada uno (qué se habilita mientras un evento está en ese estado).
Lectura para cualquier usuario del sistema con sesión (los menús de estado la necesitan); crear, editar y borrar: administrador o más."""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import event_rules
from app.auth import get_current_staff, require_role
from app.database import get_db
from app.models import Event, EventState, StaffUser

router = APIRouter()


class StateIn(BaseModel):
    name: str
    base_status: str
    color: Optional[str] = None
    position: Optional[int] = None
    is_active: bool = True
    rules: Optional[Dict[str, bool]] = None


class StatePatch(BaseModel):
    name: Optional[str] = None
    base_status: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None
    rules: Optional[Dict[str, bool]] = None


def serialize_state(s: EventState, events_using: int = 0) -> dict:
    full = event_rules.DEFAULTS_BY_BASE.get(s.base_status, {}) | {k: v for k, v in s.get_rules().items() if k in event_rules.RULES}
    return {"id": s.id, "name": s.name, "base_status": s.base_status, "color": s.color, "position": s.position, "is_active": s.is_active, "rules": full, "events_using": events_using}


def _check(name: Optional[str], base: Optional[str]) -> None:
    if name is not None and not name.strip():
        raise HTTPException(status_code=400, detail="El estado necesita un nombre")
    if base is not None and base not in event_rules.BASE_STATUSES:
        raise HTTPException(status_code=400, detail=f"El estado base debe ser uno de: {', '.join(event_rules.BASE_STATUSES)}")


@router.get("/event-states")
def list_states(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    counts = dict(db.query(Event.state_id, func.count(Event.id)).group_by(Event.state_id).all())
    states = db.query(EventState).order_by(EventState.position, EventState.id).all()
    return {"states": [serialize_state(s, counts.get(s.id, 0)) for s in states],
            "rules": [{"key": k, "label": label, "help": hint} for k, (label, hint) in event_rules.RULES.items()],
            "base_statuses": list(event_rules.BASE_STATUSES)}


@router.post("/event-states")
def create_state(data: StateIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    _check(data.name, data.base_status)
    name = data.name.strip()
    if db.query(EventState).filter(func.lower(EventState.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un estado llamado «{name}»")
    position = data.position if data.position is not None else (db.query(func.coalesce(func.max(EventState.position), -1)).scalar() + 1)
    import json
    state = EventState(name=name, base_status=data.base_status, color=data.color, position=position, is_active=data.is_active, rules_json=json.dumps(event_rules.clean_rules(data.rules)))
    db.add(state)
    db.commit()
    return serialize_state(state)


@router.patch("/event-states/{state_id}")
def update_state(state_id: int, data: StatePatch, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    state = db.get(EventState, state_id)
    if not state:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    _check(data.name, data.base_status)
    fields = data.dict(exclude_unset=True)
    if "name" in fields:
        name = fields["name"].strip()
        if db.query(EventState).filter(func.lower(EventState.name) == name.lower(), EventState.id != state_id).first():
            raise HTTPException(status_code=400, detail=f"Ya existe un estado llamado «{name}»")
        state.name = name
    using = db.query(Event).filter(Event.state_id == state_id)
    if "base_status" in fields and fields["base_status"] != state.base_status:
        if using.count():
            raise HTTPException(status_code=400, detail="Hay eventos en este estado: no se puede cambiar su estado base (muévalos antes a otro estado)")
        state.base_status = fields["base_status"]
    if "is_active" in fields and not fields["is_active"] and using.count():
        raise HTTPException(status_code=400, detail="Hay eventos en este estado: muévalos a otro antes de desactivarlo")
    for key in ("color", "position", "is_active"):
        if key in fields and fields[key] is not None:
            setattr(state, key, fields[key])
    if "rules" in fields:
        import json
        state.rules_json = json.dumps(event_rules.clean_rules(fields["rules"]))
    db.commit()
    return serialize_state(state, using.count())


@router.delete("/event-states/{state_id}")
def delete_state(state_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    state = db.get(EventState, state_id)
    if not state:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    if db.query(Event).filter(Event.state_id == state_id).count():
        raise HTTPException(status_code=400, detail="Hay eventos en este estado: muévalos a otro antes de borrarlo")
    others = db.query(EventState).filter(EventState.base_status == state.base_status, EventState.id != state_id, EventState.is_active == True).count()  # noqa: E712
    if not others:
        raise HTTPException(status_code=400, detail=f"Es el único estado activo con estado base «{state.base_status}»: el sistema lo necesita (cree otro antes)")
    db.delete(state)
    db.commit()
    return {"deleted": state_id}
