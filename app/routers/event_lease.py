"""Arrendamiento de un evento por un servidor local (Fase 6): ponerlo en local, marcar lo subido y devolverlo a internet. Ver app/event_lease.py y docs/FASE_6_SERVIDOR_LOCAL.md.
Quién: cualquiera de la empresa (coordinador, comercial, admin, super_admin, almacén, contabilidad; rol principal o sumado) sobre CUALQUIER evento de su empresa; digitadores y clientes no."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import event_lease
from app.auth import assert_event_tenant, require_role_or_any
from app.database import get_db
from app.models import AuditAction, Event, StaffUser

router = APIRouter()
_who = require_role_or_any("coordinador", event_lease.LEASE_ROLES)


def _event(db: Session, event_id: int, staff: StaffUser, lock: bool = False) -> Event:
    q = db.query(Event).filter(Event.id == event_id)
    event = (q.with_for_update() if lock else q).first()          # F5-9 A-06: tomar/soltar con la fila bloqueada (FOR UPDATE sirve con el pooler de Neon)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    return event


def _audit(db: Session, staff: StaffUser, action: str, event: Event, detail: str) -> None:
    db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action=action, entity="event", entity_id=str(event.id), entity_name=event.name, detail=detail[:500]))


@router.get("/events/{event_id}/lease")
def get_lease(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    return event_lease.serialize(_event(db, event_id, staff))


@router.post("/events/{event_id}/lease")
def take_lease(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Pone el evento en un servidor local: desde ya la nube lo muestra en solo lectura. El paquete del evento lo baja el servidor local (exportar + importar en un paso)."""
    event = _event(db, event_id, staff, lock=True)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo antes de llevarlo a un servidor local")
    name = event_lease.clean_node_name((data or {}).get("node_name"))
    event_lease.take(event, name, staff.id)
    _audit(db, staff, "lease_local", event, f"Pasó a servidor local «{name}»")
    db.commit()
    return event_lease.serialize(event)


@router.post("/events/{event_id}/lease/uploaded")
def lease_uploaded(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """El servidor local avisa que subió lo suyo (cada ~30 min): solo actualiza «última subida»."""
    event = _event(db, event_id, staff)
    event_lease.mark_uploaded(event)
    db.commit()
    return event_lease.serialize(event)


@router.post("/events/{event_id}/lease/release")
def release_lease(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """«Pasar a internet»: el evento vuelve a editarse en la nube. El servidor local sube lo pendiente ANTES de llamar aquí (sincronizar con la nube)."""
    event = _event(db, event_id, staff, lock=True)
    if not event_lease.is_leased(event):
        return event_lease.serialize(event)
    node = event.local_node_name
    event_lease.release(event)
    _audit(db, staff, "lease_release", event, f"Volvió a internet desde el servidor local «{node}»")
    db.commit()
    return event_lease.serialize(event)
