"""Inventario con catálogo (Fase 5): lo que toca la base. La lógica pura y la regla de cuadre están en app/inventory.py."""
import os
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import inventory
from app.models import Event, EventInventoryItem, InventoryProduct


def gate_enabled() -> bool:
    """El cuadre bloquea pasar un evento a «En proceso». Se apaga con INVENTORY_BALANCE_GATE=0 (por si algo falla en un evento, sin desplegar nada)."""
    return os.getenv("INVENTORY_BALANCE_GATE", "1").strip().lower() not in ("0", "false", "no", "off")


def event_lines(db: Session, event_id: int) -> List[EventInventoryItem]:
    return (db.query(EventInventoryItem).join(InventoryProduct, InventoryProduct.id == EventInventoryItem.product_id)
            .filter(EventInventoryItem.event_id == event_id).order_by(InventoryProduct.position, InventoryProduct.id).all())


def to_rows(lines: List[EventInventoryItem]) -> List[inventory.Row]:
    return [inventory.Row(name=l.product.name, assigned=l.qty_assigned or 0, out=l.qty_out or 0, returned=l.qty_returned or 0, consumed=l.qty_consumed or 0,
                          category_id=l.product.category_id if l.product.category and l.product.category.archived_at is None else None, product_id=l.product_id) for l in lines]


def balance_for(db: Session, event: Event, stage: str = None) -> inventory.BalanceReport:
    return inventory.check_balance(to_rows(event_lines(db, event.id)), stage or inventory.stage_for_status(event.status))


def assert_can_enter_in_progress(db: Session, event: Event) -> None:
    """Puerta del cambio de estado a «En proceso»: 400 con el motivo si el inventario del evento no cuadra. Un evento sin líneas de inventario pasa."""
    if not gate_enabled():
        return
    rep = inventory.can_enter_in_progress(to_rows(event_lines(db, event.id)))
    if not rep.ok:
        raise HTTPException(status_code=400, detail=inventory.blocking_message(rep))
