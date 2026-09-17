import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, StaffUser, Tenant
from app.auth import require_role

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
    }


@router.get("/tenants")
async def list_tenants(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    return [_serialize(t) for t in db.query(Tenant).order_by(Tenant.name).all()]


@router.post("/tenants")
async def create_tenant(
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
async def update_tenant(
    tenant_id: str, data: TenantUpdate, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    for field, value in data.dict(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.commit()
    return _serialize(tenant)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if db.query(Event).filter(Event.tenant_id == tenant_id).first():
        raise HTTPException(status_code=400, detail="No se puede borrar: el cliente tiene eventos asociados")
    db.delete(tenant)
    db.commit()
    return {"message": "Cliente eliminado"}
