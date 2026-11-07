import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import audit_actions
from app.models import Event, StaffUser, Tenant
from app.auth import require_role
from app.timeutil import utcnow
from app.tenant_scope import assert_same_tenant, staff_tenant_enforced

router = APIRouter()


class TenantIn(BaseModel):
    name: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "cliente"


def _generate_client_code(db: Session) -> str:
    code = secrets.token_hex(4).upper()
    while db.query(Tenant).filter(Tenant.client_code == code).first():
        code = secrets.token_hex(4).upper()
    return code


def _serialize(t: Tenant) -> dict:
    return {
        "id": t.id, "client_code": t.client_code, "name": t.name,
        "contact_name": t.contact_name, "contact_phone": t.contact_phone, "contact_email": t.contact_email,
        "archived": t.archived_at is not None, "archived_at": t.archived_at.isoformat() if t.archived_at else None,
    }


@router.get("/tenants")
def list_tenants(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Por defecto SOLO los activos (los archivados no salen en ninguna lista ni selector). `include_archived=true` es de admin+ (pantalla «Ver archivados»)."""
    query = db.query(Tenant)
    if staff_tenant_enforced(staff):          # P5: limitado a su cliente, solo ve el suyo
        query = query.filter(Tenant.id == staff.tenant_id)
    if include_archived:
        if staff.role not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="Solo un administrador puede ver los clientes archivados")
    else:
        query = query.filter(Tenant.archived_at.is_(None))
    return [_serialize(t) for t in query.order_by(Tenant.name).all()]


@router.post("/tenants")
def create_tenant(
    data: TenantIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("comercial"))
):
    """Sprint 2.4, 2026-09-16 (pedido explícito): crear clientes pasó a ser comercial+ — antes
    era coordinador+, ahora coordinador ya NO puede (solo comercial/admin/super_admin). Editar un
    cliente ya existente (update_tenant, abajo) sigue en coordinador+, sin cambios."""
    base_id = _slugify(data.name)
    tenant_id = base_id
    suffix = 1
    while db.query(Tenant).filter(Tenant.id == tenant_id).first():
        suffix += 1
        tenant_id = f"{base_id}_{suffix}"

    tenant = Tenant(
        id=tenant_id, client_code=_generate_client_code(db), name=data.name,
        contact_name=data.contact_name, contact_phone=data.contact_phone, contact_email=data.contact_email,
    )
    db.add(tenant)
    db.commit()
    return _serialize(tenant)


@router.patch("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str, data: TenantUpdate, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("comercial")),          # Fase 3 (7-nov-2026, decisión de Juan David): crea y edita comercial+
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    assert_same_tenant(staff, tenant.id, "Cliente no encontrado")          # P5: no edita otro cliente
    if tenant.archived_at is not None:
        raise HTTPException(status_code=400, detail="El cliente está archivado: restáuralo para editarlo")
    changes = data.dict(exclude_unset=True)
    if "name" in changes and not str(changes["name"] or "").strip():
        raise HTTPException(status_code=400, detail="El cliente necesita un nombre")
    for field, value in changes.items():
        setattr(tenant, field, value.strip() if isinstance(value, str) else value)
    audit_actions.record(db, staff, "edit", "tenant", tenant.id, tenant.name, "campos: " + ", ".join(sorted(changes)))          # solo QUÉ campos, nunca los valores (contactos)
    db.commit()
    return _serialize(tenant)


def _tenant_or_404(db: Session, staff: StaffUser, tenant_id: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    assert_same_tenant(staff, tenant.id, "Cliente no encontrado")
    return tenant


@router.post("/tenants/{tenant_id}/archive")
def archive_tenant(tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Archivar = ocultar de las listas y de los selectores. No borra nada: sus eventos y bases siguen intactos y un administrador lo restaura. No se archiva con un evento «En Proceso»."""
    tenant = _tenant_or_404(db, staff, tenant_id)
    if tenant.archived_at is not None:
        raise HTTPException(status_code=400, detail="El cliente ya está archivado")
    if db.query(Event).filter(Event.tenant_id == tenant.id, Event.status == "en_proceso").first():
        raise HTTPException(status_code=400, detail="No se puede archivar: el cliente tiene un evento en proceso")
    tenant.archived_at = utcnow()
    tenant.archived_by_id = staff.id
    audit_actions.record(db, staff, "archive", "tenant", tenant.id, tenant.name)
    db.commit()
    return _serialize(tenant)


@router.post("/tenants/{tenant_id}/restore")
def restore_tenant(tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    tenant = _tenant_or_404(db, staff, tenant_id)
    if tenant.archived_at is None:
        raise HTTPException(status_code=400, detail="El cliente no está archivado")
    tenant.archived_at = None
    tenant.archived_by_id = None
    audit_actions.record(db, staff, "restore", "tenant", tenant.id, tenant.name)
    db.commit()
    return _serialize(tenant)


@router.delete("/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))
):
    """Borrado DEFINITIVO: solo super_admin, solo de un cliente ya archivado y sin eventos, y queda registrado. Lo normal es archivar."""
    tenant = _tenant_or_404(db, staff, tenant_id)
    if tenant.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva al cliente; el borrado definitivo solo aplica a clientes archivados")
    if db.query(Event).filter(Event.tenant_id == tenant_id).first():
        raise HTTPException(status_code=400, detail="No se puede borrar: el cliente tiene eventos asociados")
    audit_actions.record(db, staff, "delete", "tenant", tenant.id, tenant.name)
    db.delete(tenant)
    db.commit()
    return {"message": "Cliente eliminado"}
