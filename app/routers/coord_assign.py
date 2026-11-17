"""Asignar coordinadores (17-nov-2026): el calendario «Asignar coordinadores» (arrastrar y soltar) llama a esta ruta.

Lo hace el director de coordinadores o un administrador (app/coordination.py). Es el mismo cambio que editar el evento y elegir el coordinador, con el mismo historial y aviso de campos clave;
editar el evento desde la lista sigue funcionando para cualquier coordinador+ con acceso a él."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions, coordination, event_history, event_lease, jobs
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser
from app.routers.events import _serialize

router = APIRouter()


class AssignIn(BaseModel):
    coordinator_staff_id: Optional[int] = None      # sin valor = quitar el coordinador del evento


@router.post("/events/{event_id}/assign-coordinator")
def assign_coordinator(event_id: int, body: AssignIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    if not coordination.can_assign_coordinators(staff):
        raise HTTPException(status_code=403, detail="Solo el director de coordinadores o un administrador asigna coordinadores")
    event = get_event_for_staff(event_id, db, staff)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo para asignarle un coordinador")
    if event.status == "finalizado":
        raise HTTPException(status_code=400, detail="El evento ya finalizó: no se le asigna coordinador")
    event_lease.assert_editable(event)          # en un servidor local el evento es de solo lectura en la nube
    new = None
    if body.coordinator_staff_id is not None:
        new = coordination.find_coordinator(db, body.coordinator_staff_id)
        if new is None:
            raise HTTPException(status_code=400, detail="El coordinador asignado no es válido")
    if event.coordinator_staff_id == (new.id if new else None):
        return _serialize(event)          # ya estaba así: nada que cambiar
    before = event_history.snapshot(db, event)
    event.coordinator_staff_id = new.id if new else None
    audit_actions.record(db, staff, "assign_coordinator" if new else "unassign_coordinator", "event", event.id, event.name, f"coordinador: {(new.full_name or new.username) if new else 'ninguno'}")
    changed = event_history.record(db, event, before, staff, "edit")
    db.commit()
    if changed:
        jobs.kick()          # despierta el aviso de campos clave, si se encoló alguno
    return _serialize(event)
