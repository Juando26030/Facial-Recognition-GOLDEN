"""CRM → inventario (19-nov-2026): productos del CRM de cada evento y alertas cuando el CRM cambia (lógica en app/crm_inventory.py).
Ver: mismos roles que el inventario del evento. Cambiar (agregar un producto del CRM, actualizar a lo del CRM o descartar la alerta): quien puede editar el plan de inventario del evento."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_actions, crm_inventory
from app.tenant_scope import staff_tenant_enforced
from app.crm.errors import CrmError
from app.database import get_db
from app.models import CrmProduct, EventInventoryAlert, StaffUser
from app.routers import inventory as inv_router

router = APIRouter(tags=["crm-inventory"])


def _guard(db: Session, event_id: int, staff: StaffUser, *, edit: bool):
    if staff_tenant_enforced(staff):          # 23-nov (E2): el catálogo CRM es solo de Golden; una cuenta de otra empresa no lo ve ni lo cambia
        raise HTTPException(status_code=404, detail="No encontrado")
    event = inv_router._event(db, event_id, staff, lock=edit)
    if edit:
        if event.archived_at is not None:
            raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo para cambiar su inventario")
        if not inv_router.can_edit_plan(staff):
            raise HTTPException(status_code=403, detail="Tu rol solo puede ver el inventario")
    return event


def _run(db: Session, fn):
    try:
        out = fn()
        db.commit()
        return out
    except CrmError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/events/{event_id}/crm-inventory")
def get_crm_inventory(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(inv_router.VIEWER)):
    event = _guard(db, event_id, staff, edit=False)
    data = crm_inventory.panel(db, event)
    db.commit()          # detectar una alerta nueva deja una fila (idempotente)
    data["can_edit"] = inv_router.can_edit_plan(staff) and event.archived_at is None
    return data


@router.get("/events/{event_id}/crm-inventory/options")
def crm_product_options(event_id: int, q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(inv_router.VIEWER)):
    """Productos activos del CRM para agregar a mano (con cuántos elementos implican): máximo 50, por nombre."""
    _guard(db, event_id, staff, edit=False)
    from app.crm import normalize
    query = db.query(CrmProduct).filter(CrmProduct.active.is_(True))
    if q.strip():
        query = query.filter(CrmProduct.name_norm.like(f"%{normalize(q)}%"))
    rows = query.order_by(CrmProduct.name_norm, CrmProduct.id).limit(50).all()
    per = crm_inventory.per_unit_map(db, [p.id for p in rows])
    return {"items": [{"id": p.id, "name": p.name, "sku": p.sku, "implies": len(per.get(p.id, []))} for p in rows]}


@router.put("/events/{event_id}/crm-inventory/products/{crm_product_id}")
def put_manual_product(event_id: int, crm_product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(inv_router.VIEWER)):
    """Agrega a mano un producto del CRM al evento (`qty`; 0 lo quita). Se expande a los elementos que implica."""
    event = _guard(db, event_id, staff, edit=True)
    try:
        qty = int(data.get("qty"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Envía la cantidad como número entero")

    def work():
        crm_inventory.set_manual(db, event, crm_product_id, qty, staff)
        audit_actions.record(db, staff, "update", "event_inventory", event.id, event.name, f"producto del CRM {crm_product_id} = {qty} (manual)")
        return {"ok": True}
    return _run(db, work)


def _alert(db: Session, event_id: int, alert_id: int) -> EventInventoryAlert:
    a = db.get(EventInventoryAlert, alert_id)
    if a is None or a.event_id != event_id:
        raise HTTPException(status_code=404, detail="La alerta no existe")
    if a.status != "open":
        raise HTTPException(status_code=409, detail="Esta alerta ya se resolvió")
    return a


@router.post("/events/{event_id}/crm-inventory/alerts/{alert_id}/apply")
def apply_alert(event_id: int, alert_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(inv_router.VIEWER)):
    event = _guard(db, event_id, staff, edit=True)
    a = _alert(db, event_id, alert_id)

    def work():
        crm_inventory.apply_alert(db, event, a, staff)
        audit_actions.record(db, staff, "update", "event_inventory", event.id, event.name, "actualizado a lo del CRM")
        return {"ok": True}
    return _run(db, work)


@router.post("/events/{event_id}/crm-inventory/alerts/{alert_id}/dismiss")
def dismiss_alert(event_id: int, alert_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(inv_router.VIEWER)):
    event = _guard(db, event_id, staff, edit=True)
    a = _alert(db, event_id, alert_id)

    def work():
        crm_inventory.dismiss_alert(db, a, staff)
        audit_actions.record(db, staff, "update", "event_inventory", event.id, event.name, "alerta del CRM descartada")
        return {"ok": True}
    return _run(db, work)
