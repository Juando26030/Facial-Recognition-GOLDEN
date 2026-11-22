"""Lo que el servidor local hace en la puerta y ANTES no llegaba a la nube (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md §3b):

  edits       ediciones de datos de la persona (`person_change_log`: un campo por fila)
  areas       movimientos de entrada/salida de áreas (`area_movements`; el área viaja por su NOMBRE: los ids cambian entre la nube y el servidor)
  deliveries  entregas de inventario (`inventory_deliveries`; el ítem viaja por su nombre y el de su categoría madre)
  turns       turnos (`queue_turns`) y su estado (llamado / atendido / saltado)
  calls       llamados de turnos (`queue_calls`)
  roulette    sorteos de la ruleta (`roulette_draws`)
  leads       contactos escaneados por expositores (`exhibitor_leads`; el expositor viaja por su nombre y, si no existe en la nube, se crea con sus datos)
  acceptances aceptaciones/firmas de la persona (`web_acceptances`: creada y verificada)
  consents    autorizaciones de datos (`audit_consent_logs`: SOLO INSERT; la huella de la cédula se recalcula con la llave de quien la recibe)
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

from app.models import (AccessLog, AreaMovement, AuditConsentLog, Event, EventArea, EventAttendee, EventExhibitor, ExhibitorLead, InventoryDelivery, InventoryItem, PersonChangeLog, QueueCall,
                        QueueTurn, RouletteDraw, User, WebAcceptance)

USER_FIELDS = ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1")
EXTRA_RE = re.compile(r"^opcional_\d+$")
TURN_STATUS = ("waiting", "called", "done", "skipped")
SECTIONS = ("edits", "areas", "deliveries", "turns", "calls", "turn_status", "roulette", "leads", "acceptances", "consents")


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


def is_attendee(db: Session, event: Event, uid: str) -> bool:
    return db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id == uid, EventAttendee.tenant_id == event.tenant_id).first() is not None


def _reject(stats: Optional[dict], n: int = 1) -> None:
    if stats is not None:
        stats["rejected"] = stats.get("rejected", 0) + n


class _Users:
    """Cache de «¿existe esta persona en este evento/empresa?» para no consultar fila por fila.
    Con `event` (seguridad 22-nov-2026, 04 #4): además la persona debe ser ASISTENTE de ese evento (`event_attendees`). Así lo que sube un servidor local no puede editar ni «autorizar»
    a alguien de otro evento del mismo cliente. Lo que no pasa se cuenta en `stats["rejected"]` y el lote sigue."""
    def __init__(self, db: Session, tenant: str, event: Optional[Event] = None, stats: Optional[dict] = None):
        self.db, self.tenant, self.seen, self.event, self.stats = db, tenant, {}, event, stats

    def get(self, uid: str) -> Optional[User]:
        if uid not in self.seen:
            user = self.db.query(User).filter(User.id == uid, User.tenant_id == self.tenant).first()
            if user is not None and self.event is not None and not is_attendee(self.db, self.event, uid):
                user = None
            self.seen[uid] = user
        if self.seen[uid] is None and self.event is not None:
            _reject(self.stats)
        return self.seen[uid]


def _strict(event: Event, from_peer) -> Optional[Event]:
    """Solo la NUBE al recibir de un servidor (`from_peer=None`) exige «asistente del evento». Al BAJAR lo de los demás servidores (`from_peer=True`) la fuente es la nube, que ya filtró."""
    return event if from_peer is None else None


# ------------------------------------------------------------------------------------------------ serializar (lo que se envía)
def edit_row(r: PersonChangeLog) -> dict:
    return {"cedula": r.user_id, "field": r.field_key, "old": r.old_value, "new": r.new_value, "at": _iso(r.changed_at), "source": r.source}


def area_row(r: AreaMovement, area_names: dict) -> Optional[dict]:
    name = area_names.get(r.area_id)
    return {"cedula": r.user_id, "area": name, "direction": r.direction, "method": r.method, "at": _iso(r.timestamp)} if name else None


def delivery_row(r: InventoryDelivery, items: dict) -> Optional[dict]:
    it = items.get(r.item_id)
    if not it:
        return None
    out = {"cedula": r.user_id, "item": it[0], "parent": it[1], "batch": r.batch_id, "qty": r.qty, "at": _iso(r.delivered_at)}
    if r.assignment_key:          # 0161: «la base lo define»: qué asignación se entregó ('h' o 'd<uid>', estable entre servidores)
        out["akey"] = r.assignment_key
    return out


def turn_row(r: QueueTurn) -> dict:
    return {"cedula": r.user_id, "lane": r.lane, "number": r.number, "rank": r.rank, "status": r.status, "desk": r.desk, "called_at": _iso(r.called_at),
            "done_at": _iso(r.done_at), "source": r.source, "created_at": _iso(r.created_at)}


def call_row(r: QueueCall) -> dict:
    return {"lane": r.lane, "number": r.number, "desk": r.desk, "at": _iso(r.called_at)}


def roulette_row(r: RouletteDraw) -> dict:
    return {"label": r.label, "mode": r.mode, "is_random": bool(r.is_random), "candidates": r.candidates_count, "filter_json": r.filter_json, "winners_json": r.winners_json,
            "at": _iso(r.created_at)}


def lead_row(r: ExhibitorLead, exhibitors: dict) -> Optional[dict]:
    ex = exhibitors.get(r.exhibitor_id)
    if ex is None:
        return None
    return {"cedula": r.user_id, "at": _iso(r.scanned_at), "exhibitor": {"name": ex.name, "contact_name": ex.contact_name, "title": ex.title, "email": ex.email, "phone": ex.phone,
                                                                          "active": bool(ex.active)}}


def acceptance_row(r: WebAcceptance) -> dict:
    return {"cedula": r.user_id, "created_at": _iso(r.created_at), "verified_at": _iso(r.verified_at), "verified_via": r.verified_via}


def consent_row(r: AuditConsentLog) -> dict:
    ts = r.consent_timestamp_utc
    if ts is not None and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return {"id": r.id, "cedula": r.user_id, "at": _iso(ts), "version": r.consent_version, "legal_text_hash": r.legal_text_hash, "accepted": bool(r.accepted_biometric),
            "adult": bool(r.confirmed_adult), "device": r.ip_or_device_id, "reason": r.reason}


def exhibitor_map(db: Session, event_id: int) -> dict:
    return {e.id: e for e in db.query(EventExhibitor).filter(EventExhibitor.event_id == event_id)}


def area_names(db: Session, event_id: int) -> dict:
    return {a.id: a.name for a in db.query(EventArea).filter(EventArea.event_id == event_id)}


def item_names(db: Session, event_id: int) -> dict:
    rows = db.query(InventoryItem).filter(InventoryItem.event_id == event_id).all()
    by_id = {r.id: r for r in rows}
    return {r.id: (r.name, by_id[r.parent_id].name if r.parent_id in by_id else None) for r in rows}


# ------------------------------------------------------------------------------------------------ aplicar (lo que se recibe)
def apply_edits(db: Session, event: Event, items: list, from_peer=None, stats: Optional[dict] = None) -> int:
    """Ediciones de datos: gana la más reciente de cada campo. Siempre queda el historial. En la nube, solo de asistentes del evento (lo demás: `stats["rejected"]`)."""
    users, n = _Users(db, event.tenant_id, _strict(event, from_peer), stats), 0
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
        db.add(InventoryDelivery(event_id=event.id, item_id=iid, batch_id=batch, user_id=uid, tenant_id=event.tenant_id, qty=qty, delivered_at=at, from_peer=from_peer,
                                 assignment_key=_s(r.get("akey"), 40) or None))
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


def apply_person_change_effect(db: Session, event: Event, kind: str, uid: Optional[str], at: Optional[datetime], new_value, attendee_only: bool = False,
                               stats: Optional[dict] = None) -> int:
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
        if attendee_only and not is_attendee(db, event, uid):          # 04 #4: la fecha de nacimiento (y con ella la biometría) solo de quien está en ESTE evento
            _reject(stats)
            return 0
        birth = minors.parse_birth(new_value) if new_value else None
        user.birth_date = birth
        if birth is not None and minors.is_minor(birth):
            user.is_biometric_enabled = False
        return 1
    return 0


def apply_roulette(db: Session, event: Event, items: list, from_peer=None) -> int:
    n = 0
    for r in items or []:
        at, mode = _when((r or {}).get("at")), _s((r or {}).get("mode"), 40)
        if at is None or not mode or not r.get("winners_json"):
            continue
        label = _s(r.get("label"), 200)
        q = db.query(RouletteDraw.id).filter(RouletteDraw.event_id == event.id, RouletteDraw.created_at == at, RouletteDraw.mode == mode)
        q = q.filter(RouletteDraw.label == label) if label else q.filter(RouletteDraw.label.is_(None))
        if q.first():
            continue
        try:
            cands = int(r.get("candidates") or 0)
        except (TypeError, ValueError):
            cands = 0
        db.add(RouletteDraw(event_id=event.id, label=label, mode=mode, is_random=bool(r.get("is_random")), candidates_count=cands, filter_json=r.get("filter_json"),
                            winners_json=str(r.get("winners_json")), created_at=at, from_peer=from_peer))
        n += 1
    return n


def apply_leads(db: Session, event: Event, items: list, from_peer=None) -> int:
    by_name = {e.name.strip().lower(): e for e in db.query(EventExhibitor).filter(EventExhibitor.event_id == event.id)}
    users, n = _Users(db, event.tenant_id), 0
    for r in items or []:
        uid, at, ex_data = str((r or {}).get("cedula") or ""), _when((r or {}).get("at")), (r or {}).get("exhibitor") or {}
        name = str(ex_data.get("name") or "").strip()
        if not uid or at is None or not name or users.get(uid) is None:
            continue
        ex = by_name.get(name.lower())
        if ex is None:                                       # el expositor se creó en el servidor local: se crea igual aquí (con enlaces nuevos)
            ex = EventExhibitor(tenant_id=event.tenant_id, event_id=event.id, name=name[:200], contact_name=_s(ex_data.get("contact_name"), 200), title=_s(ex_data.get("title"), 200),
                                email=_s(ex_data.get("email"), 200), phone=_s(ex_data.get("phone"), 60), token=secrets.token_urlsafe(18), card_token=secrets.token_urlsafe(18),
                                active=bool(ex_data.get("active", True)))
            db.add(ex)
            db.flush()
            by_name[name.lower()] = ex
        if db.query(ExhibitorLead.id).filter(ExhibitorLead.exhibitor_id == ex.id, ExhibitorLead.tenant_id == event.tenant_id, ExhibitorLead.user_id == uid).first():
            continue
        db.add(ExhibitorLead(exhibitor_id=ex.id, event_id=event.id, tenant_id=event.tenant_id, user_id=uid, scanned_at=at, from_peer=from_peer))
        db.flush()
        n += 1
    return n


def apply_acceptances(db: Session, event: Event, items: list, from_peer=None, stats: Optional[dict] = None) -> int:
    users, n = _Users(db, event.tenant_id, _strict(event, from_peer), stats), 0
    for r in items or []:
        uid, created = str((r or {}).get("cedula") or ""), _when((r or {}).get("created_at"))
        if not uid or created is None or users.get(uid) is None:
            continue
        verified = _when(r.get("verified_at"))
        wa = db.get(WebAcceptance, (event.tenant_id, uid, event.id))
        if wa is None:
            db.add(WebAcceptance(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, created_at=created, verified_at=verified, verified_via=_s(r.get("verified_via"), 12),
                                 from_peer=from_peer))
            db.flush()
            n += 1
        elif verified and (wa.verified_at is None or verified < wa.verified_at):          # la verificación más antigua es la que vale; nunca se «des-verifica»
            wa.verified_at, wa.verified_via = verified, (_s(r.get("verified_via"), 12) or wa.verified_via)
            n += 1
    return n


def apply_consents(db: Session, event: Event, items: list, from_peer=None, stats: Optional[dict] = None) -> int:
    """Autorizaciones de datos: solo se INSERTAN (la tabla no admite cambios ni borrados). La huella de la cédula se calcula aquí, con la llave de este entorno.
    En la NUBE (04 #4): solo de asistentes del evento, y una aceptación BIOMÉTRICA que llega de un servidor local queda «sin verificar» con la MISMA marca de /aceptar
    (`web_acceptances` sin `verified_at`, la que `consent.accepted_user_ids` ya excluye del reconocimiento) hasta que el personal confirme la identidad
    (`POST /api/events/{id}/web-acceptance/{cédula}/verify`). No se marca si la persona ya tenía una aceptación vigente, ni si el mismo servidor subió su verificación
    (`acceptances` se aplica antes en `apply_all`)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app import consent, faces_version
    users, n = _Users(db, event.tenant_id, _strict(event, from_peer), stats), 0
    for r in items or []:
        cid, uid, at = _s((r or {}).get("id"), 36), str((r or {}).get("cedula") or ""), _when((r or {}).get("at"))
        reason = (r or {}).get("reason")
        if not cid or not uid or at is None or reason not in ("consent", "rejection", "revocation") or users.get(uid) is None:
            continue
        row = dict(id=cid, tenant_id=event.tenant_id, user_id=uid, cedula_hash=consent.cedula_hash(uid), event_id=event.id, consent_timestamp_utc=at.replace(tzinfo=timezone.utc),
                   consent_version=(_s(r.get("version"), 40) or "desconocida"), legal_text_hash=(_s(r.get("legal_text_hash"), 64) or ""), accepted_biometric=bool(r.get("accepted")),
                   confirmed_adult=bool(r.get("adult")), ip_or_device_id=_s(r.get("device"), 200), reason=reason, from_peer=from_peer)
        hold = (from_peer is None and reason == "consent" and row["accepted_biometric"] and not consent.has_acceptance(db, event.tenant_id, uid, event.id)
                and db.get(WebAcceptance, (event.tenant_id, uid, event.id)) is None)
        if db.execute(pg_insert(AuditConsentLog).values(**row).on_conflict_do_nothing(index_elements=["id"])).rowcount == 1:
            n += 1
            if hold:                                         # llegó de un servidor local y nadie de la nube vio a la persona: por verificar
                db.add(WebAcceptance(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, created_at=at, verified_at=None))
                db.flush()
    if n:
        faces_version.bump(db, event_ids=[event.id])          # quién puede ser reconocido cambió (igual que consent.record)
    return n


def apply_all(db: Session, event: Event, body: dict, from_peer=None) -> dict:
    """`rejected`: filas de ediciones, aceptaciones o autorizaciones que NO se aplicaron porque la persona no es asistente de este evento (solo cuenta en la nube; el lote sigue)."""
    body = body or {}
    stats = {"rejected": 0}
    turns = apply_turns(db, event, body.get("turns"), from_peer)
    return {"edits": apply_edits(db, event, body.get("edits"), from_peer, stats), "areas": apply_areas(db, event, body.get("areas"), from_peer),
            "deliveries": apply_deliveries(db, event, body.get("deliveries"), from_peer), "turns": turns["saved"], "turn_conflicts": turns["conflicts"],
            "calls": apply_calls(db, event, body.get("calls"), from_peer), "turn_status": apply_turn_status(db, event, body.get("turn_status")),
            "roulette": apply_roulette(db, event, body.get("roulette"), from_peer), "leads": apply_leads(db, event, body.get("leads"), from_peer),
            "acceptances": apply_acceptances(db, event, body.get("acceptances"), from_peer, stats), "consents": apply_consents(db, event, body.get("consents"), from_peer, stats),
            "rejected": stats["rejected"]}


def count(body: dict) -> int:
    return sum(len((body or {}).get(k) or []) for k in SECTIONS)


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
