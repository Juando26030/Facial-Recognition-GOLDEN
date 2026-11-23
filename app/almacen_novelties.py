"""Almacén — Pieza 3: novedades (daños o problemas de un elemento) y bloqueo hasta que almacén lo deje «disponible» (rama almacen/p3-novedades).

Módulo PURO (sin FastAPI; la base solo se toca en `open_qty_by_product`, con las importaciones dentro de la función): decide si una novedad es válida y en qué queda cada equipo.
Lo usan app/routers/almacen_novedades.py, app/routers/almacen.py (entrada «con novedad») y la disponibilidad de app/routers/inventory.py y app/inventory_alerts.py.

Reglas (decisiones de Juan David, 17-nov-2026, y las que tomé al programarlas; ver docs/ALMACEN.md):
  · Una novedad lleva un TEXTO (qué pasó) y, opcional, una FOTO del daño. Queda abierta hasta que alguien de almacén la resuelve con una nota de lo que se hizo.
  · Equipo con serial: pasa a «En novedad» y NO se puede sacar a un evento hasta que se resuelva (entonces vuelve a «disponible»). Una sola novedad abierta por equipo.
    Si se reporta mientras el equipo sigue en un evento, conserva «en_evento» y, al devolverlo, queda «En novedad» en vez de «disponible».
  · Por modelo o por cantidad: la novedad lleva una cantidad (las piezas dañadas) y esas piezas no cuentan como disponibles: disponible = existencias − novedades abiertas.
    Sacar de un producto con novedades abiertas NO se bloquea (se avisa), igual que lo que falta asignar.
  · Un consumible no lleva novedades (se gasta y almacén lo repone y lo cuenta a mano).
  · Nada se borra: resolver deja quién, cuándo y qué se hizo.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from app.almacen import AlmacenError
from app.inventory import MAX_QTY

MAX_TEXT = 500
REPORTABLE_UNIT_STATUSES = ("disponible", "en_evento")


class NoveltyError(AlmacenError):
    """Novedad no válida (mensaje en español para el usuario)."""


@dataclass
class NoveltyPlan:
    qty: int
    unit_status: Optional[str]          # estado nuevo del equipo (None = no cambia)


def clean_text(value, label: str) -> str:
    t = " ".join(str(value or "").split())
    if len(t) < 3:
        raise NoveltyError(f"{label}: escribe al menos 3 letras.")
    if len(t) > MAX_TEXT:
        raise NoveltyError(f"{label}: máximo {MAX_TEXT} caracteres.")
    return t


def clean_qty(value) -> int:
    try:
        q = int(str(value).strip()) if value not in (None, "") else 1
    except ValueError:
        raise NoveltyError("La cantidad debe ser un número entero.")
    if q < 1 or q > MAX_QTY:
        raise NoveltyError(f"La cantidad debe estar entre 1 y {MAX_QTY}.")
    return q


def available(stock: Optional[int], open_qty: int) -> Optional[int]:
    """Existencias que de verdad se pueden asignar: existencias − piezas en novedad. None si el producto no lleva existencias."""
    return None if stock is None else max(int(stock) - int(open_qty or 0), 0)


def plan_open(*, tracking: str, consumable: bool, unit_status: Optional[str], qty=1, open_qty: int = 0, stock: Optional[int] = None, product_name: str = "") -> NoveltyPlan:
    """Reportar una novedad. Lanza NoveltyError si no procede; devuelve la cantidad y el estado en que queda el equipo."""
    name = f"«{product_name}»" if product_name else "Este elemento"
    if consumable:
        raise NoveltyError(f"{name} es un consumible: no lleva novedades (se gasta y almacén lo repone).")
    if tracking == "serial":
        if unit_status == "novedad":
            raise NoveltyError("Ese equipo ya tiene una novedad abierta: resuélvela antes de reportar otra.")
        if unit_status not in REPORTABLE_UNIT_STATUSES:
            raise NoveltyError("Ese equipo no se puede reportar en este momento.")
        return NoveltyPlan(qty=1, unit_status="novedad" if unit_status == "disponible" else None)
    q = clean_qty(qty)
    if stock is not None and open_qty + q > stock:
        raise NoveltyError(f"{name}: hay {stock} en existencias y ya hay {open_qty} en novedad; no se pueden reportar {q} más.")
    return NoveltyPlan(qty=q, unit_status=None)


def entry_novelty_qty(*, tracking: str, entry_qty: int, qty=None) -> int:
    """Novedad al devolver: un equipo con serial es de a uno; por modelo/cantidad, de lo que vuelve cuántas piezas traen daño (1 por defecto, máximo lo devuelto)."""
    if tracking == "serial":
        return 1
    q = clean_qty(qty)
    if q > entry_qty:
        raise NoveltyError(f"Devuelves {entry_qty}: no pueden venir {q} con novedad.")
    return q


def plan_resolve(*, resolved: bool, unit_status: Optional[str]) -> Optional[str]:
    """Resolver (dejar «disponible»). Devuelve el estado nuevo del equipo (None = no cambia; un equipo que sigue en un evento conserva «en_evento»)."""
    if resolved:
        raise NoveltyError("Esa novedad ya estaba resuelta.")
    return "disponible" if unit_status == "novedad" else None


def open_qty_by_product(db, product_ids: Optional[Iterable[int]] = None) -> Dict[int, int]:
    """Piezas en novedad abierta por producto (para la disponibilidad). Solo cuenta si Almacén está activo: sin el interruptor no hay novedades que restar."""
    from sqlalchemy import func

    from app import almacen
    from app.models import InventoryNovelty
    if not almacen.almacen_enabled():
        return {}
    q = db.query(InventoryNovelty.product_id, func.coalesce(func.sum(InventoryNovelty.qty), 0)).filter(InventoryNovelty.resolved_at.is_(None))
    ids = list(product_ids) if product_ids is not None else None
    if ids is not None:
        if not ids:
            return {}
        q = q.filter(InventoryNovelty.product_id.in_(ids))
    return {pid: int(n) for pid, n in q.group_by(InventoryNovelty.product_id).all()}
