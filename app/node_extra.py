"""Lo que el servidor local hace en la puerta y ANTES no llegaba a la nube (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md §3b):

  edits       ediciones de datos de la persona (`person_change_log`: un campo por fila)
  areas       movimientos de entrada/salida de áreas (`area_movements`; el área viaja por su NOMBRE: los ids cambian entre la nube y el servidor)
  deliveries  entregas de inventario (`inventory_deliveries`; el ítem viaja por su nombre y el de su categoría madre)
  turns       turnos (`queue_turns`) y su estado (llamado / atendido / saltado)
  calls       llamados de turnos (`queue_calls`)
y los EFECTOS de `person_changes` que antes solo se guardaban como historial: «No registrado» (deshacer registro: borra los registros de la persona hechos HASTA ese momento) y la fecha
de nacimiento.

Las mismas funciones `apply_*` sirven en los dos sentidos: la NUBE las usa al recibir lo que sube un servidor (`from_peer=None`) y el SERVIDOR LOCAL al bajar lo de los otros servidores de un
evento compartido (`from_peer=True`, app/peer_changes.py). Todas son idempotentes por llave natural: repetir un lote no duplica nada. No hacen commit.
Reglas de conflicto: en ediciones gana el cambio MÁS RECIENTE de cada campo (si ya hay uno más nuevo, el viejo queda solo en el historial); un turno ya existente para la persona no se pisa;
un turno cuyo número (fila + número) ya tiene OTRA persona se omite (en eventos compartidos, cada entrada debe usar sus propias filas). Nada de datos personales en logs.
"""
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (AccessLog, AreaMovement, Event, EventArea, InventoryDelivery, InventoryItem, PersonChangeLog, QueueCall, QueueTurn, User)

USER_FIELDS = ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1")
EXTRA_RE = re.compile(r"^opcional_\d+$")
TURN_STATUS = ("waiting", "called", "done", "skipped")
SECTIONS = ("edits", "areas", "deliveries", "turns", "calls", "turn_status")


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _when(value) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo is None else d.astimezone(timezone.utc).replace(tzinfo=None)


def _s(v, n: int) -> Optional[str]:
    return str(v)[:n] if v not in (None, "") else None


class _Users:
    """Cache de «¿existe esta persona en este evento/empresa?» para no consultar fila por fila."""
    def __init__(self, db: Session, tenant: str):
        self.db, self.tenant, self.seen = db, tenant, {}

    def get(self, uid: str) -> Optional[User]:
        if uid not in self.seen:
            self.seen[uid] = self.db.query(User).filter(User.id == uid, User.tenant_id == self.tenant).first()
        return self.seen[uid]


# ------------------------------------------------------------------------------------------------ serializar (lo que se envía)
def edit_row(r: PersonChangeLog) -> dict:
    return {"cedula": r.user_id, "field": r.field_key, "old": r.old_value, "new": r.new_value, "at": _iso(r.changed_at), "source": r.source}


def area_row(r: AreaMovement, area_names: dict) -> Optional[dict]:
    name = area_names.get(r.area_id)
    return {"cedula": r.user_id, "area": name, "direction": r.direction, "method": r.method, "at": _iso(r.timestamp)} if name else None


def delivery_row(r: InventoryDelivery, items: dict) -> Optional[dict]:
    it = items.get(r.item_id)
    return {"cedula": r.user_id, "item": it[0], "parent": it[1], "batch": r.batch_id, "qty": r.qty, "at": _iso(r.delivered_at)} if it else None


def turn_row(r: QueueTurn) -> dict:
    return {"cedula": r.user_id, "lane": r.lane, "number": r.number, "rank": r.rank, "status": r.status, "desk": r.desk, "called_at": _iso(r.called_at),
            "done_at": _iso(r.done_at), "source": r.source, "created_at": _iso(r.created_at)}


def call_row(r: QueueCall) -> dict:
    return {"lane": r.lane, "number": r.number, "desk": r.desk, "at": _iso(r.called_at)}


def area_names(db: Session, event_id: int) -> dict:
    return {a.id: a.name for a in db.query(EventArea).filter(EventArea.event_id == event_id)}


def item_names(db: Session, event_id: int) -> dict:
    rows = db.query(InventoryItem).filter(InventoryItem.event_id == event_id).all()
    by_id = {r.id: r for r in rows}
    return {r.id: (r.name, by_id[r.parent_id].name if r.parent_id in by_id else None) for r in rows}


# ------------------------------------------------------------------------------------------------ aplicar (lo que se recibe)
def apply_edits(db: Session, event: Event, items: list, from_peer=None) -> int:
    """Ediciones de datos: gana la más reciente de cada campo. Siempre queda el historial."""
    users, n = _Users(db, event.tenant_id), 0
    for r in items or []:
        uid, field, at = str((r or {}).get("cedula") or ""), str((r or {}).get("field") or "")[:64], _when((r or {}).get("at"))
        if not uid or at is None or not (field in USER_FIELDS or EXTRA_RE.match(field)):
            continue
        user = users.get(uid)
        if user is None:
            continue
        new = _s(r.get("new"), 500)
        if db.query(PersonChangeLog.id).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.user_id == uid, PersonChangeLog.field_key == field,
                                               PersonChangeLog.changed_at == at, PersonChangeLog.new_value == new).first():
            continue                                         # ya estaba
        newer = db.query(PersonChangeLog.id).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.user_id == uid, PersonChangeLog.field_key == field,
                                                    PersonChangeLog.changed_at > at).first()
        if not newer:                                        # último gana: solo se aplica si no hay un cambio más nuevo de ese campo
            if field in USER_FIELDS:
                setattr(user, field, new)
            else:
                extras = user.get_extras()
                if new:
                    extras[field] = new
                else:
                    extras.pop(field, None)
                user.set_extras(extras)
        db.add(PersonChangeLog(tenant_id=event.tenant_id, event_id=event.id, user_id=uid, field_key=field, old_value=_s(r.get("old"), 500), new_value=new,
                               source=(_s(r.get("source"), 16) or "outbox"), changed_at=at, from_peer=from_peer))
        n += 1
    db.flush()
    return n


def apply_areas(db: Session, event: Event, items: list, from_peer=None) -> int:
    by_name = {}
    for a in db.query(EventArea).filter(EventArea.event_id == event.id).order_by(EventArea.archived_at.isnot(None), EventArea.id):
        by_name.setdefault(a.name.strip().lower(), a.id)     # si hay dos con el mismo nombre, gana la activa
    users, n = _Users(db, event.tenant_id), 0
    for r in items or []:
        uid, at = str((r or {}).get("cedula") or ""), _when((r or {}).get("at"))
        area_id = by_name.get(str(r.get("area") or "").strip().lower())
        direction = "out" if r.get("direction") == "out" else "in"
        if not uid or at is None or area_id is None or users.get(uid) is None:
            continue
        if db.query(AreaMovement.id).filter(AreaMovement.event_id == event.id, AreaMovement.area_id == area_id, AreaMovement.user_id == uid,
                                            AreaMovement.direction == direction, AreaMovement.timestamp == at).first():
            continue
        db.add(AreaMovement(event_id=event.id, area_id=area_id, user_id=uid, tenant_id=event.tenant_id, direction=direction, method=_s(r.get("method"), 20), timestamp=at,
                            from_peer=from_peer))
        n += 1
    return n


def apply_deliveries(db: Session, event: Event, items: list, from_peer=None) -> int:
    names = item_names(db, event.id)
    by_key = {}
    for iid, (name, parent) in names.items():
        by_key.setdefault(((name or "").strip().lower(), (parent or "").strip().lower()), iid)
    users, n = _Users(db, event.tenant_id), 0
    for r in items or []:
        uid, at = str((r or {}).get("cedula") or ""), _when((r or {}).get("at"))
        iid = by_key.get((str(r.get("item") or "").strip().lower(), str(r.get("parent") or "").strip().lower()))
        batch = _s(r.get("batch"), 64) or f"sync-{at.isoformat() if at else ''}"
        if not uid or at is None or iid is None or users.get(uid) is None:
            continue
        if db.query(InventoryDelivery.id).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.item_id == iid, InventoryDelivery.user_id == uid,
                                                 InventoryDelivery.batch_id == batch, InventoryDelivery.delivered_at == at).first():
            continue
        try:
            qty = max(1, int(r.get("qty") or 1))
        except (TypeError, ValueError):
            qty = 1
        db.add(InventoryDelivery(event_id=event.id, item_id=iid, batch_id=batch, user_id=uid, tenant_id=event.tenant_id, qty=qty, delivered_at=at, from_peer=from_peer))
        n += 1
    return n


def _status_rank(s: str) -> int:
    return TURN_STATUS.index(s) if s in TURN_STATUS else 0


def apply_turns(db: Session, event: Event, items: list, from_peer=None) -> dict:
    """Turnos nuevos (uno por persona y evento). Devuelve {"saved", "conflicts"}: conflicto = esa fila+número ya es de OTRA persona."""
    users, saved, conflicts = _Users(db, event.tenant_id), 0, 0
    for r in items or []:
        uid, lane = str((r or {}).get("cedula") or ""), str((r or {}).get("lane") or "")[:1]
        try:
            number, rank = int(r.get("number")), int(r.get("rank") or r.get("number"))
        except (TypeError, ValueError):
            continue
        if not uid or not lane or users.get(uid) is None:
            continue
        mine = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.user_id == uid).first()
        if mine is not None:
            _apply_status(mine, r)                          # ya tenía turno: solo avanza su estado
            continue
        if db.query(QueueTurn.id).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane, QueueTurn.number == number).first():
            conflicts += 1
            continue
        status = r.get("status") if r.get("status") in TURN_STATUS else "waiting"
        db.add(QueueTurn(event_id=event.id, user_id=uid, lane=lane, number=number, rank=rank, token=secrets.token_urlsafe(16), status=status, desk=_s(r.get("desk"), 40),
                         called_at=_when(r.get("called_at")), done_at=_when(r.get("done_at")), source=(_s(r.get("source"), 10) or "arrival"),
                         created_at=_when(r.get("created_at")) or datetime.utcnow(), from_peer=from_peer))
        db.flush()
        saved += 1
    return {"saved": saved, "conflicts": conflicts}


def _apply_status(turn: QueueTurn, r: dict) -> bool:
    """El estado de un turno solo avanza (esperando → llamado → atendido/saltado) o se actualiza con un llamado más nuevo."""
    status = r.get("status") if r.get("status") in TURN_STATUS else None
    called, done = _when(r.get("called_at")), _when(r.get("done_at"))
    changed = False
    if called and (turn.called_at is None or called > turn.called_at):
        turn.called_at, turn.desk = called, (_s(r.get("desk"), 40) or turn.desk)
        changed = True
    if status and _status_rank(status) > _status_rank(turn.status):
        turn.status = status
        changed = True
    if done and turn.done_at is None:
        turn.done_at = done
        changed = True
    return changed


def apply_turn_status(db: Session, event: Event, items: list) -> int:
    n = 0
    for r in items or []:
        uid = str((r or {}).get("cedula") or "")
        turn = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.user_id == uid).first() if uid else None
        if turn is not None and _apply_status(turn, r):
            n += 1
    return n


def apply_calls(db: Session, event: Event, items: list, from_peer=None) -> int:
    n = 0
    for r in items or []:
        lane, at = str((r or {}).get("lane") or "")[:1], _when((r or {}).get("at"))
        try:
            number = int(r.get("number"))
        except (TypeError, ValueError):
            continue
        if not lane or at is None:
            continue
        turn = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane, QueueTurn.number == number).first()
        if turn is None:
            continue
        if db.query(QueueCall.id).filter(QueueCall.event_id == event.id, QueueCall.lane == lane, QueueCall.number == number, QueueCall.called_at == at).first():
            continue
        db.add(QueueCall(event_id=event.id, turn_id=turn.id, lane=lane, number=number, desk=_s(r.get("desk"), 40), called_at=at, from_peer=from_peer))
        _apply_status(turn, {"status": "called", "called_at": r.get("at"), "desk": r.get("desk")})
        n += 1
    return n


def apply_person_change_effect(db: Session, event: Event, kind: str, uid: Optional[str], at: Optional[datetime], new_value) -> int:
    """El EFECTO de un cambio de persona que llega de otro lado (antes solo se guardaba el historial):
    - «No registrado»: borra los registros de la persona en el evento hechos HASTA ese momento (uno posterior, de una nueva llegada, se conserva).
    - fecha de nacimiento: la pone (y con ella si la persona puede tener biometría).
    Devuelve cuántas filas cambió."""
    if not uid or at is None:
        return 0
    if kind == "registration_status" and new_value == "No registrado":
        return db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.user_id == uid, AccessLog.timestamp <= at).delete(synchronize_session=False)
    if kind == "birth_date":
        from app import minors
        user = db.query(User).filter(User.id == uid, User.tenant_id == event.tenant_id).first()
        if user is None:
            return 0
        birth = minors.parse_birth(new_value) if new_value else None
        user.birth_date = birth
        if birth is not None and minors.is_minor(birth):
            user.is_biometric_enabled = False
        return 1
    return 0


def apply_all(db: Session, event: Event, body: dict, from_peer=None) -> dict:
    body = body or {}
    turns = apply_turns(db, event, body.get("turns"), from_peer)
    return {"edits": apply_edits(db, event, body.get("edits"), from_peer), "areas": apply_areas(db, event, body.get("areas"), from_peer),
            "deliveries": apply_deliveries(db, event, body.get("deliveries"), from_peer), "turns": turns["saved"], "turn_conflicts": turns["conflicts"],
            "calls": apply_calls(db, event, body.get("calls"), from_peer), "turn_status": apply_turn_status(db, event, body.get("turn_status"))}


def count(body: dict) -> int:
    return sum(len((body or {}).get(k) or []) for k in SECTIONS)


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
