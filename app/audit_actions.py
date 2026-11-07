"""Registro de acciones administrativas (Fase 3): archivar, restaurar, borrar. Se llama DENTRO de la misma transacción que la acción (sin commit propio): si la acción falla, el registro
tampoco queda. Solo guarda ids y el nombre de la entidad (empresa cliente, evento…), nunca datos personales."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditAction, StaffUser
from app.timeutil import utcnow


def record(db: Session, staff: Optional[StaffUser], action: str, entity: str, entity_id, entity_name: Optional[str] = None, detail: Optional[str] = None) -> AuditAction:
    row = AuditAction(
        at=utcnow(), actor_id=getattr(staff, "id", None), actor_role=getattr(staff, "role", None), action=action, entity=entity,
        entity_id=str(entity_id)[:64], entity_name=(entity_name or None) and str(entity_name)[:200], detail=(detail or None) and str(detail)[:500],
    )
    db.add(row)
    return row
