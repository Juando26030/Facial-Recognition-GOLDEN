"""Estados de evento configurables (docs/18 §4): el administrador crea los que quiera y le adjunta reglas a cada uno (qué se habilita mientras un evento está en ese estado).
Lectura para cualquier usuario del sistema con sesión (los menús de estado la necesitan); crear, editar, archivar y restaurar: administrador o más; borrado definitivo: solo super_admin (Fase 3)."""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_actions, event_rules
from app.auth import effective_roles, get_current_staff, require_role
from app.database import get_db
from app.models import Event, EventState, StaffUser
from app.timeutil import utcnow

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
    return {"id": s.id, "name": s.name, "base_status": s.base_status, "color": s.color, "position": s.position, "is_active": s.is_active, "rules": full, "events_using": events_using, "archived": s.archived_at is not None, "billing": event_rules.is_billing_state(s)}


def _check(name: Optional[str], base: Optional[str]) -> None:
    if name is not None and not name.strip():
        raise HTTPException(status_code=400, detail="El estado necesita un nombre")
    if base is not None and base not in event_rules.BASE_STATUSES:
        raise HTTPException(status_code=400, detail=f"El estado base debe ser uno de: {', '.join(event_rules.BASE_STATUSES)}")


@router.get("/event-states")
def list_states(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """Por defecto SOLO los no archivados (los menús de estado no ofrecen los archivados). `include_archived=true` (con los archivados) es de admin+."""
    counts = dict(db.query(Event.state_id, func.count(Event.id)).group_by(Event.state_id).all())
    query = db.query(EventState)
    if include_archived:
        if staff.role not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="Solo un administrador puede ver los estados archivados")
    else:
        query = query.filter(EventState.archived_at.is_(None))
    states = query.order_by(EventState.position, EventState.id).all()
    return {"states": [serialize_state(s, counts.get(s.id, 0)) for s in states],
            "rules": [{"key": k, "label": label, "help": hint} for k, (label, hint) in event_rules.RULES.items()],
            "base_statuses": list(event_rules.BASE_STATUSES),
            "can_set_billed": bool({"comercial", "admin", "super_admin"} & effective_roles(staff))}          # Fase 5: quién puede poner o quitar un estado de facturación («Facturado»)


def _check_billing(rules: Optional[dict], base: str) -> None:
    """F5-9 C6: un estado de facturación (regla `client_delivery`) solo puede tener estado base «finalizado». Sin esto un administrador podía encender la regla en «En proceso»
    y habilitar la entrega al cliente de eventos en curso, sin base final ni quién/cuándo facturó."""
    if event_rules.clean_rules(rules).get("client_delivery") and base != "finalizado":
        raise HTTPException(status_code=400, detail="La regla de facturación (entrega al cliente) solo puede ir en un estado con base «Finalizado»")


@router.post("/event-states")
def create_state(data: StateIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    _check(data.name, data.base_status)
    name = data.name.strip()
    if db.query(EventState).filter(func.lower(EventState.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un estado llamado «{name}»")
    _check_billing(data.rules, data.base_status)
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
    if state.archived_at is not None:
        raise HTTPException(status_code=400, detail="El estado está archivado: restáuralo para editarlo")
    _check(data.name, data.base_status)
    fields = data.dict(exclude_unset=True)
    if "name" in fields:
        name = fields["name"].strip()
        if db.query(EventState).filter(func.lower(EventState.name) == name.lower(), EventState.id != state_id).first():
            raise HTTPException(status_code=400, detail=f"Ya existe un estado llamado «{name}»")
        state.name = name
    using = db.query(Event).filter(Event.state_id == state_id)
    if "base_status" in fields and fields["base_status"] != state.base_status:
        _check_billing(fields.get("rules", state.get_rules()), fields["base_status"])
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
        new_rules = event_rules.clean_rules(fields["rules"])
        _check_billing(new_rules, state.base_status)
        was, now = event_rules.is_billing_state(state), bool(new_rules.get("client_delivery", False))
        if was != now:
            # F5-9 C6: encender o apagar la facturación de un estado con eventos los «factura» o «desfactura» a todos de golpe, sin pasar por la puerta de comercial/admin ni dejar
            # quién y cuándo en cada evento. Hay que moverlos antes (eso sí queda registrado por evento).
            if using.count():
                raise HTTPException(status_code=400, detail="Hay eventos en este estado: muévalos a otro antes de encender o apagar la regla de facturación")
            audit_actions.record(db, staff, "billing_rule_on" if now else "billing_rule_off", "event_state", state.id, state.name, "regla de facturación (entrega al cliente)")
        state.rules_json = json.dumps(new_rules)
    db.commit()
    return serialize_state(state, using.count())


def _state_or_404(db: Session, state_id: int) -> EventState:
    state = db.get(EventState, state_id)
    if not state:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    return state


@router.post("/event-states/{state_id}/archive")
def archive_state(state_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Archivar = dejar de ofrecer el estado (queda inactivo y fuera de los menús). Mismas reglas que desactivarlo: ningún evento puede estar en él y debe quedar otro estado activo con el
    mismo estado base (el sistema lo necesita). No borra nada; un administrador lo restaura."""
    state = _state_or_404(db, state_id)
    if state.archived_at is not None:
        raise HTTPException(status_code=400, detail="El estado ya está archivado")
    if db.query(Event).filter(Event.state_id == state_id).count():
        raise HTTPException(status_code=400, detail="Hay eventos en este estado: muévalos a otro antes de archivarlo")
    if state.is_active:
        others = db.query(EventState).filter(EventState.base_status == state.base_status, EventState.id != state_id, EventState.is_active == True, EventState.archived_at.is_(None)).count()  # noqa: E712
        if not others:
            raise HTTPException(status_code=400, detail=f"Es el único estado activo con estado base «{state.base_status}»: el sistema lo necesita (cree otro antes)")
    state.is_active = False
    state.archived_at = utcnow()
    state.archived_by_id = staff.id
    audit_actions.record(db, staff, "archive", "event_state", state.id, state.name)
    db.commit()
    return serialize_state(state)


@router.post("/event-states/{state_id}/restore")
def restore_state(state_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Restaurar lo deja ACTIVO otra vez."""
    state = _state_or_404(db, state_id)
    if state.archived_at is None:
        raise HTTPException(status_code=400, detail="El estado no está archivado")
    state.archived_at = None
    state.archived_by_id = None
    state.is_active = True
    audit_actions.record(db, staff, "restore", "event_state", state.id, state.name)
    db.commit()
    return serialize_state(state)


@router.delete("/event-states/{state_id}")
def delete_state(state_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Borrado DEFINITIVO (Fase 3): solo super_admin, solo de un estado ya ARCHIVADO y que ningún evento use; queda en `audit_actions`. Lo normal es archivar."""
    state = _state_or_404(db, state_id)
    if state.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el estado; el borrado definitivo solo aplica a estados archivados")
    if db.query(Event).filter(Event.state_id == state_id).count():
        raise HTTPException(status_code=400, detail="Hay eventos en este estado: muévalos a otro antes de borrarlo")
    audit_actions.record(db, staff, "delete", "event_state", state.id, state.name)
    db.delete(state)
    db.commit()
    return {"deleted": state_id}
