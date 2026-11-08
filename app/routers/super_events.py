"""Superevento (reunión 2026-09-21, ítem 19): agrupa eventos independientes de un mismo cliente bajo
un "padre". Cada hijo se maneja totalmente separado (parámetros, registro, reportes) — lo único que
cruza es el aviso de que una persona ya asistió a un evento hermano."""
from datetime import datetime
from app.timeutil import utcnow

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_actions
from app.auth import get_event_for_staff, require_role
from app.tenant_scope import assert_same_tenant
from app import event_archive
from app.database import get_db
from app.models import AccessLog, Event, StaffUser, SuperEvent, User

router = APIRouter()


def _serialize(s: SuperEvent) -> dict:
    return {
        "id": s.id, "name": s.name, "tenant_id": s.tenant_id, "events": len(s.events),
        "archived": s.archived_at is not None, "archived_at": s.archived_at.isoformat() if s.archived_at else None,
    }


@router.get("/super-events")
def list_super_events(
    tenant_id: str, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Por defecto SOLO los activos (los archivados no salen en listas ni selectores). `include_archived=true` (coordinador+, como toda la ruta) alimenta «Ver archivados»."""
    assert_same_tenant(staff, tenant_id, "Cliente no encontrado")          # P5: solo los supereventos de su cliente
    query = db.query(SuperEvent).filter(SuperEvent.tenant_id == tenant_id)
    if not include_archived:
        query = query.filter(SuperEvent.archived_at.is_(None))
    return [_serialize(s) for s in query.order_by(SuperEvent.name).all()]


@router.post("/super-events")
def create_super_event(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    name = str(data.get("name") or "").strip()
    tenant_id = str(data.get("tenant_id") or "").strip()
    if not name or not tenant_id:
        raise HTTPException(status_code=400, detail="El superevento necesita un nombre y un cliente")
    assert_same_tenant(staff, tenant_id, "Cliente no encontrado")
    if db.query(SuperEvent).filter(SuperEvent.tenant_id == tenant_id, SuperEvent.name == name).first():
        raise HTTPException(status_code=400, detail="Ya existe un superevento con ese nombre para este cliente")
    sup = SuperEvent(tenant_id=tenant_id, name=name, created_by_id=staff.id, created_at=utcnow())
    db.add(sup)
    db.commit()
    return _serialize(sup)


def _super_or_404(db: Session, staff: StaffUser, super_id: int) -> SuperEvent:
    sup = db.query(SuperEvent).filter(SuperEvent.id == super_id).first()
    if not sup:
        raise HTTPException(status_code=404, detail="Superevento no encontrado")
    assert_same_tenant(staff, sup.tenant_id, "Superevento no encontrado")          # P5: no toca el de otro cliente
    return sup


@router.patch("/super-events/{super_id}")
def update_super_event(super_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Editar el nombre (lo único que se pide al crear, además del cliente, que NO se puede cambiar). Un superevento archivado no se edita."""
    sup = _super_or_404(db, staff, super_id)
    if sup.archived_at is not None:
        raise HTTPException(status_code=400, detail="El superevento está archivado: restáuralo para editarlo")
    if "tenant_id" in data and str(data.get("tenant_id") or "").strip() != sup.tenant_id:
        raise HTTPException(status_code=400, detail="No se puede cambiar el cliente de un superevento")
    changed = []
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="El superevento necesita un nombre")
        if name != sup.name:
            if db.query(SuperEvent).filter(SuperEvent.tenant_id == sup.tenant_id, SuperEvent.name == name, SuperEvent.id != sup.id).first():
                raise HTTPException(status_code=400, detail="Ya existe un superevento con ese nombre para este cliente")
            sup.name = name
            changed.append("name")
    if changed:
        audit_actions.record(db, staff, "edit", "super_event", sup.id, sup.name, "campos: " + ", ".join(changed))
        db.commit()
    return _serialize(sup)


@router.post("/super-events/{super_id}/archive")
def archive_super_event(super_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Archivar = sacarlo de listas y selectores. NO toca sus eventos (siguen con su `super_event_id`) y la asistencia hermana (`sibling_attendance`) sigue contando entre ellos."""
    sup = _super_or_404(db, staff, super_id)
    if sup.archived_at is not None:
        raise HTTPException(status_code=400, detail="El superevento ya está archivado")
    sup.archived_at = utcnow()
    sup.archived_by_id = staff.id
    audit_actions.record(db, staff, "archive", "super_event", sup.id, sup.name)
    db.commit()
    return _serialize(sup)


@router.post("/super-events/{super_id}/restore")
def restore_super_event(super_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    sup = _super_or_404(db, staff, super_id)
    if sup.archived_at is None:
        raise HTTPException(status_code=400, detail="El superevento no está archivado")
    sup.archived_at = None
    sup.archived_by_id = None
    audit_actions.record(db, staff, "restore", "super_event", sup.id, sup.name)
    db.commit()
    return _serialize(sup)


@router.delete("/super-events/{super_id}")
def delete_super_event(super_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Borrado DEFINITIVO: solo super_admin, solo de uno archivado y sin eventos asociados; queda registrado."""
    sup = _super_or_404(db, staff, super_id)
    if sup.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el superevento; el borrado definitivo solo aplica a los archivados")
    if db.query(Event).filter(Event.super_event_id == sup.id).first():
        raise HTTPException(status_code=400, detail="No se puede borrar: el superevento tiene eventos asociados")
    audit_actions.record(db, staff, "delete", "super_event", sup.id, sup.name)
    db.delete(sup)
    db.commit()
    return {"message": "Superevento eliminado"}


def sibling_attendance(db: Session, event: Event, user_id: str) -> list:
    """Eventos HERMANOS (mismo superevento, distinto evento) a los que esta persona ya asistió —
    o sea, con al menos una acreditación real (no las ediciones de perfil, 'Actualizado')."""
    if not event.super_event_id:
        return []
    siblings = db.query(Event).filter(Event.super_event_id == event.super_event_id, Event.id != event.id).all()
    attended = []
    for sib in siblings:
        real = db.query(AccessLog).filter(
            AccessLog.event_id == sib.id, AccessLog.user_id == user_id, AccessLog.record_type != "Actualizado"
        ).first()
        if real:
            attended.append({"event_id": sib.id, "event_name": sib.name, "event_code": sib.event_code})
    return attended


@router.get("/users/{user_id}/sibling-check")
def sibling_check(
    user_id: str, event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """¿Esta persona ya asistió a un evento hermano de este (mismo superevento)? Si sí, devuelve sus
    datos guardados para poder solo vincularla a este evento en vez de capturarlos de nuevo."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    attended = sibling_attendance(db, event, user_id)
    if not attended:
        return {"siblings": []}
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    return {
        "siblings": attended,
        "super_event_name": event.super_event.name if event.super_event else "",
        "user": {"id": user.id, "first_name": user.first_name, "last_name": user.last_name} if user else None,
    }
