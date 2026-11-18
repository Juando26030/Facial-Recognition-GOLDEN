"""Avisos del inventario de un evento (Fase 5, decisión de Juan David del 9-nov-2026). NUNCA bloquean: solo avisan para que se actúe (alquilar o buscar otras opciones).

  1. Anticipación: con el evento en la misma ciudad de la bodega (`INVENTORY_HOME_CITY`, por defecto Bogotá) el inventario debe reservarse con al menos 1 día de anticipación a su inicio; en otra ciudad,
     con al menos 7 días (1 semana: da tiempo al envío).
  2. Disponibilidad: si el producto tiene existencias (`qty_total`) y lo asignado a este evento más lo asignado a otros eventos que se cruzan en fechas (no finalizados ni archivados) las supera,
     «no hay material disponible de Golden»: hay que alquilar o buscar otra opción.
Los avisos llegan a Almacén, a la comercial y al coordinador del evento: en la campana de la aplicación y por correo (app/notifications.py). Con la misma situación no se repiten (clave de aviso).
Parte pura: `lead_warning`, `shortage`, `same_city`.
"""
import os
import unicodedata
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app import almacen_novelties, notifications
from app.auth import sees_event_tenant, staff_with_role
from app.models import Event, EventInventoryItem, InventoryProduct, StaffUser
from app.timeutil import utcnow

SAME_CITY_DAYS = 1
OTHER_CITY_DAYS = 7
DEFAULT_HOME_CITY = "Bogotá"


def _norm(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def home_city() -> str:
    return os.getenv("INVENTORY_HOME_CITY", DEFAULT_HOME_CITY)


def same_city(event_city, home: Optional[str] = None) -> bool:
    """¿El evento es en la ciudad de la bodega? Sin ciudad en el evento se asume que sí (no se molesta con un aviso de envío que no se puede saber)."""
    if not _norm(event_city):
        return True
    return _norm(event_city) == _norm(home if home is not None else home_city())


def lead_warning(start: Optional[date], today: date, is_same_city: bool) -> Optional[str]:
    """Mensaje si el inventario se reservó con menos anticipación de la debida; None si está a tiempo (o el evento no tiene fecha de inicio)."""
    if start is None:
        return None
    need = SAME_CITY_DAYS if is_same_city else OTHER_CITY_DAYS
    left = (start - today).days
    if left >= need:
        return None
    when = "ya empezó o empieza hoy" if left <= 0 else ("empieza mañana" if left == 1 else f"empieza en {left} días")
    if is_same_city:
        return f"El inventario debe reservarse con al menos 1 día de anticipación y el evento {when}. Hay que apartar el material de inmediato."
    return f"El evento es en otra ciudad: el inventario debe reservarse con al menos 1 semana de anticipación (tiempo de envío) y el evento {when}. Hay que coordinar el envío de inmediato."


def shortage(total: Optional[int], mine: int, others: int) -> int:
    """Unidades que faltan según las existencias de Golden (0 si no hay control de existencias o alcanza)."""
    if total is None:
        return 0
    return max(int(mine) + int(others) - int(total), 0)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    if a_start is None or b_start is None:
        return False
    return b_start <= (a_end or a_start) and (b_end or b_start) >= a_start


def warnings_for_event(db: Session, event: Event, today: Optional[date] = None) -> list:
    """[{kind: 'lead'|'stock', product_id, missing?, message}] con la situación ACTUAL del inventario asignado al evento. No escribe nada."""
    if event.archived_at is not None or event.status == "finalizado":
        return []
    lines = db.query(EventInventoryItem).filter(EventInventoryItem.event_id == event.id, EventInventoryItem.qty_assigned > 0).all()
    if not lines:
        return []
    out = []
    msg = lead_warning(event.start_date, today or utcnow().date(), same_city(event.city))
    if msg:
        out.append({"kind": "lead", "product_id": None, "missing": 0, "message": msg})
    controlled = [(l, db.get(InventoryProduct, l.product_id)) for l in lines]
    controlled = [(l, p) for l, p in controlled if p is not None and p.qty_total is not None]
    if controlled:
        others = db.query(Event).filter(Event.id != event.id, Event.archived_at.is_(None), Event.status != "finalizado", Event.start_date.isnot(None)).all()
        clash_ids = [o.id for o in others if _overlaps(event.start_date, event.end_date, o.start_date, o.end_date)]
        in_nov = almacen_novelties.open_qty_by_product(db, [p.id for _, p in controlled])          # Almacén (Pieza 3): lo que está en novedad no cuenta como disponible
        for line, prod in controlled:
            used = 0
            if clash_ids:
                used = sum(r.qty_assigned for r in db.query(EventInventoryItem).filter(EventInventoryItem.product_id == prod.id, EventInventoryItem.event_id.in_(clash_ids)).all())
            bad = in_nov.get(prod.id, 0)
            missing = shortage(almacen_novelties.available(prod.qty_total, bad), line.qty_assigned, used)
            if missing:
                out.append({"kind": "stock", "product_id": prod.id, "missing": missing,
                            "message": f"No hay material de Golden disponible de «{prod.name}»: faltan {missing} {prod.unit} (existencias {prod.qty_total}" + (f", {bad} en novedad" if bad else "") + f", ya asignadas a otros eventos en esas fechas {used}). Hay que alquilar o buscar otras opciones."})
    return out


def recipients(db: Session, event: Event, actor: Optional[StaffUser]) -> list:
    """Cuentas que reciben el aviso: todas las de almacén más la comercial y el coordinador del evento (activas, sin repetir y sin quien hizo el cambio)."""
    ids = [s.id for s in staff_with_role(db, "almacen")] + [event.commercial_staff_id, event.coordinator_staff_id]
    out = []
    for sid in ids:
        if not sid or sid in out or (actor is not None and sid == actor.id):
            continue
        s = db.get(StaffUser, sid)
        if s is not None and s.is_active and s.archived_at is None and sees_event_tenant(s, event):          # F5-9 D (D2): nada de avisos de eventos de otro cliente
            out.append(sid)
    return out


def notify_event(db: Session, event: Event, actor: Optional[StaffUser], warnings: list) -> int:
    """Crea las notificaciones (campana + correo) de estos avisos; no confirma. Quien llama confirma y despierta la cola (`jobs.kick()`). Devuelve cuántas se crearon."""
    created = 0
    to = recipients(db, event, actor)
    for w in warnings:
        key = f"inv:{event.id}:{w['kind']}:{w.get('product_id') or 0}:{w.get('missing') or 0}:{event.start_date or ''}"
        title = "Inventario: " + ("reserva con poca anticipación" if w["kind"] == "lead" else "no alcanza el material") + f" — {event.name}"
        created += notifications.notify(db, to, kind="inventory_" + w["kind"], title=title, body=w["message"], url="/inventario", event_id=event.id, dedupe_key=key)
    return created
