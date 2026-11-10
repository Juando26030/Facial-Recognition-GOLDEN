"""Permanencia en zonas (Fase 10): lo que toca la base. La lógica pura está en app/area_dwell.py. La persona de prueba (PRUEBA) nunca cuenta."""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import area_dwell, testperson
from app.models import AreaMovement, Event, EventArea, User
from app.timeutil import local_to_utc, utcnow


def threshold(event: Event) -> int:
    return event.dwell_threshold_pct or area_dwell.DEFAULT_THRESHOLD_PCT


def window_local(event: Event):
    return area_dwell.event_window_local(event.start_date, event.end_date, event.event_time_start, event.event_time_end)


def reference(event: Event) -> Optional[int]:
    """El 100 % en minutos: lo que definió el coordinador o, si no, la duración del evento."""
    return area_dwell.reference_for(event.dwell_reference_minutes, window_local(event))


def config_json(event: Event) -> dict:
    win = window_local(event)
    return {
        "dwell_enabled": bool(event.areas_dwell_enabled), "prize_enabled": bool(event.dwell_prize_enabled),
        "reference_minutes": event.dwell_reference_minutes, "threshold_pct": threshold(event),
        "event_minutes": area_dwell.window_minutes(win), "effective_reference_minutes": reference(event),
        "areas_autoscan": bool(event.areas_autoscan), "inventory_autoscan": bool(event.inventory_autoscan),
    }


def _cap(event: Event):
    win = window_local(event)
    end_utc = local_to_utc(win[1]) if win else None
    return area_dwell.cap_for(end_utc, utcnow())


def compute(db: Session, event: Event, *, area_id: Optional[int] = None, user_ids: Optional[List[str]] = None) -> Dict[str, area_dwell.Dwell]:
    q = db.query(AreaMovement).filter(AreaMovement.event_id == event.id, func.upper(AreaMovement.user_id) != testperson.TEST_ID)
    if area_id is not None:
        q = q.filter(AreaMovement.area_id == area_id)
    if user_ids is not None:
        q = q.filter(AreaMovement.user_id.in_(user_ids or [""]))
    moves = [area_dwell.Move(m.user_id, m.area_id, m.direction, m.timestamp) for m in q.order_by(AreaMovement.timestamp, AreaMovement.id)]
    return area_dwell.compute(moves, _cap(event))


def rows(db: Session, event: Event, *, area_id: Optional[int] = None, pct: Optional[int] = None) -> List[dict]:
    """Una fila por persona con movimientos: cédula, nombre, entidad, tiempo, porcentaje y si cumple. Más tiempo primero."""
    ref, thr = reference(event), (pct or threshold(event))
    dwell = compute(db, event, area_id=area_id)
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(list(dwell) or [""])).all()}
    out = []
    for uid, d in dwell.items():
        u = users.get(uid)
        out.append({
            "id": uid, "name": f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "", "entity": (u.entity or "") if u else "",
            "seconds": d.seconds, "minutes": round(d.seconds / 60, 1), "label": area_dwell.format_minutes(d.seconds), "entries": d.entries,
            "percent": area_dwell.percent(d.seconds, ref), "meets": area_dwell.meets(d.seconds, ref, thr), "open": d.open,
        })
    out.sort(key=lambda r: (-r["seconds"], r["id"]))
    return out


def qualifies(db: Session, event: Event, user_id: str) -> bool:
    """¿Esta persona ya llegó al porcentaje del evento? (puerta de las entregas con «solo a quien cumple la estadía»)."""
    if testperson.is_test(user_id):
        return True          # la persona de prueba ensaya el flujo; nunca cuenta en estadísticas
    d = compute(db, event, user_ids=[user_id]).get(user_id)
    return bool(d) and area_dwell.meets(d.seconds, reference(event), threshold(event))


def prize_active(event: Event) -> bool:
    return bool(event.areas_dwell_enabled and event.dwell_prize_enabled)


def areas_of(db: Session, event: Event) -> List[dict]:
    return [{"id": a.id, "name": a.name} for a in db.query(EventArea).filter(EventArea.event_id == event.id, EventArea.archived_at.is_(None)).order_by(EventArea.id)]
