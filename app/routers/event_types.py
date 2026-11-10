"""Tipos de evento (Fase 10, bloque C): la lista parametrizable detrás de «Categoría (tipo de evento)».

Lectura: coordinador o más (la necesitan «Nuevo evento» y «Editar evento»). Agregar, renombrar, cambiar color, archivar y restaurar: SOLO super_admin. No se borra: archivar deja de ofrecer el tipo
pero los eventos que ya lo tienen lo conservan. Cada cambio queda en `audit_actions`."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_actions
from app.auth import require_role
from app.database import get_db
from app.models import Event, EventType, StaffUser
from app.timeutil import utcnow

router = APIRouter()
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
NAME_MAX = 80


class TypeIn(BaseModel):
    name: str
    color: Optional[str] = None


class TypePatch(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None          # "" = sin color


def serialize(t: EventType, events_using: int = 0) -> dict:
    return {"id": t.id, "name": t.name, "color": t.color or "", "position": t.position, "archived": t.archived_at is not None, "events_using": events_using}


def _clean_name(raw) -> str:
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="El tipo de evento necesita un nombre")
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=400, detail=f"El nombre puede tener hasta {NAME_MAX} letras")
    return name


def _clean_color(raw) -> Optional[str]:
    if raw in (None, ""):
        return None
    if not _HEX.match(str(raw)):
        raise HTTPException(status_code=400, detail="El color debe ser como #D4AF37")
    return str(raw)


def _dup(db: Session, name: str, except_id: Optional[int] = None) -> None:
    q = db.query(EventType).filter(func.lower(EventType.name) == name.lower())
    if except_id is not None:
        q = q.filter(EventType.id != except_id)
    if q.first():
        raise HTTPException(status_code=400, detail=f"Ya existe un tipo de evento llamado «{name}»")


def _get(db: Session, type_id: int) -> EventType:
    t = db.get(EventType, type_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tipo de evento no encontrado")
    return t


@router.get("/event-types")
def list_types(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Por defecto solo los activos (lo que se ofrece al crear/editar). `include_archived=true` (con los archivados) es solo de super_admin."""
    if include_archived and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo un super administrador puede ver los tipos archivados")
    counts = dict(db.query(Event.event_type_id, func.count(Event.id)).filter(Event.event_type_id.isnot(None)).group_by(Event.event_type_id).all())
    q = db.query(EventType)
    if not include_archived:
        q = q.filter(EventType.archived_at.is_(None))
    return {"types": [serialize(t, counts.get(t.id, 0)) for t in q.order_by(EventType.position, EventType.id).all()]}


@router.post("/event-types")
def create_type(data: TypeIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    name = _clean_name(data.name)
    _dup(db, name)
    position = db.query(func.coalesce(func.max(EventType.position), -1)).scalar() + 1
    t = EventType(name=name, color=_clean_color(data.color), position=position)
    db.add(t)
    db.flush()
    audit_actions.record(db, staff, "create", "event_type", t.id, t.name)
    db.commit()
    return serialize(t)


@router.patch("/event-types/{type_id}")
def update_type(type_id: int, data: TypePatch, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    t = _get(db, type_id)
    if t.archived_at is not None:
        raise HTTPException(status_code=400, detail="El tipo está archivado: restáuralo para editarlo")
    fields = data.dict(exclude_unset=True)
    if "name" in fields:
        name = _clean_name(fields["name"])
        _dup(db, name, type_id)
        t.name = name
    if "color" in fields:
        t.color = _clean_color(fields["color"])
    audit_actions.record(db, staff, "update", "event_type", t.id, t.name)
    db.commit()
    return serialize(t, db.query(func.count(Event.id)).filter(Event.event_type_id == t.id).scalar())


@router.post("/event-types/{type_id}/archive")
def archive_type(type_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Deja de ofrecerse en «Nuevo evento»/«Editar evento». Los eventos que ya lo tienen lo conservan (y el calendario lo sigue mostrando)."""
    t = _get(db, type_id)
    if t.archived_at is not None:
        raise HTTPException(status_code=400, detail="El tipo ya está archivado")
    t.archived_at = utcnow()
    t.archived_by_id = staff.id
    audit_actions.record(db, staff, "archive", "event_type", t.id, t.name)
    db.commit()
    return serialize(t)


@router.post("/event-types/{type_id}/restore")
def restore_type(type_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    t = _get(db, type_id)
    if t.archived_at is None:
        raise HTTPException(status_code=400, detail="El tipo no está archivado")
    t.archived_at = None
    t.archived_by_id = None
    audit_actions.record(db, staff, "restore", "event_type", t.id, t.name)
    db.commit()
    return serialize(t)


def check_assignable(db: Session, type_id: Optional[int], current_id: Optional[int] = None) -> None:
    """Para crear/editar un evento: el tipo debe existir y no estar archivado (conservar el que ya tiene, aunque esté archivado, sí se permite)."""
    if type_id is None:
        return
    t = db.get(EventType, type_id)
    if not t:
        raise HTTPException(status_code=400, detail="La categoría (tipo de evento) elegida no existe")
    if t.archived_at is not None and type_id != current_id:
        raise HTTPException(status_code=400, detail="La categoría (tipo de evento) elegida está archivada")
