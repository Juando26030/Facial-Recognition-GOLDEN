"""Evento COMPARTIDO entre varios servidores locales, con la nube como puente (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md).

Dos entradas lejos entre sí, cada una con su servidor local y con internet (por ejemplo Starlink): cada servidor SUBE lo suyo como siempre (app/node_sync.py) y BAJA de la nube lo que
hicieron los demás, cada ~15 s. Así, quien se registró en la entrada A aparece como «ya registrado» en la entrada B.

Lado NUBE (`current_cursor`, `changes_since`): lo que hay en el evento después de un cursor = últimos ids que el servidor ya tiene de cada tabla:
    l = access_logs.id      a = event_attendees.id      p = print_logs.id      c = person_changes.id
    e = person_change_log.id (ediciones)   m = area_movements.id   d = inventory_deliveries.id   t = queue_turns.id   q = queue_calls.id
    r = roulette_draws.id   x = exhibitor_leads.id
Lado SERVIDOR LOCAL (`apply_changes`): aplica lo bajado SIN duplicar y marca cada fila `from_peer` (la subida no la devuelve a la nube):
  - personas: si no está en el evento, se crea (y la persona, si no existía); si ya estaba, NO se pisan sus datos.
  - registros: por `client_id` (los propios vuelven con el prefijo de este servidor y se saltan); un «Nuevo» de alguien que aquí ya tiene registro no se repite.
  - impresiones y cambios: por llave natural (persona + momento + tipo), igual que la nube; «No registrado» y la fecha de nacimiento además se APLICAN.
  - ediciones, áreas, entregas de inventario, turnos y llamados: app/node_extra.py (las mismas reglas que usa la nube al recibirlos).
Conflictos: una persona registrada en las dos entradas durante un corte queda con los dos registros (como en el modo sin red de los quioscos); un alta repetida no pisa los datos (gana la
primera); en ediciones gana el cambio más reciente de cada campo. Ver docs/23.
Nada de datos personales en los logs (solo conteos).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import node_extra
from app.models import (AccessLog, AreaMovement, Event, EventAttendee, ExhibitorLead, InventoryDelivery, PersonChange, PersonChangeLog, PrintLog, QueueCall, QueueTurn, RouletteDraw,
                        User)
from app.timeutil import utcnow

log = logging.getLogger("golden.peer_changes")
PAGE = 500
KEYS = ("l", "a", "p", "c", "e", "m", "d", "t", "q", "r", "x")
PERSON_FIELDS = ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1")


# ------------------------------------------------------------------------------------------------ comunes
def clean_cursor(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in KEYS:
        try:
            out[k] = max(0, int(raw.get(k) or 0))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _when(value) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo is None else d.astimezone(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------------------------------------ NUBE
def current_cursor(db: Session, event_id: int) -> dict:
    """Los últimos ids que HOY tiene la nube de este evento: el servidor que acaba de bajar el paquete empieza desde aquí."""
    def top(model):
        return int(db.query(func.coalesce(func.max(model.id), 0)).filter(model.event_id == event_id).scalar() or 0)
    return {"l": top(AccessLog), "a": top(EventAttendee), "p": top(PrintLog), "c": top(PersonChange), "e": top(PersonChangeLog), "m": top(AreaMovement),
            "d": top(InventoryDelivery), "t": top(QueueTurn), "q": top(QueueCall), "r": top(RouletteDraw), "x": top(ExhibitorLead)}


def changes_since(db: Session, event: Event, cursor: dict) -> dict:
    cur = clean_cursor(cursor)
    out_cursor = dict(cur)
    atts = (db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.id > cur["a"]).order_by(EventAttendee.id).limit(PAGE).all())
    users = {}
    ids = list({a.user_id for a in atts})
    if ids:
        users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids))}
    persons = []
    for a in atts:
        u = users.get(a.user_id)
        out_cursor["a"] = a.id
        if u is None:
            continue
        persons.append({"cedula": u.id, **{f: getattr(u, f) for f in PERSON_FIELDS}, "extra_fields": u.get_extras(), "birth_date": u.birth_date.isoformat() if u.birth_date else None,
                        "categories": a.get_categories(), "origin": a.origin, "code": a.code, "certificate": bool(a.certificate), "created_at": _iso(a.created_at)})
    logs = []
    for r in db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.id > cur["l"]).order_by(AccessLog.id).limit(PAGE):
        out_cursor["l"] = r.id
        logs.append({"client_id": r.client_id or f"cloud-{r.id}", "cedula": r.user_id, "timestamp": _iso(r.timestamp), "record_type": r.record_type,
                     "method": r.registration_method, "doubtful": r.doubtful_reason})
    prints = []
    for r in db.query(PrintLog).filter(PrintLog.event_id == event.id, PrintLog.id > cur["p"]).order_by(PrintLog.id).limit(PAGE):
        out_cursor["p"] = r.id
        prints.append({"cedula": r.user_id, "printed_at": _iso(r.printed_at), "kind": r.kind})
    changes = []
    for r in db.query(PersonChange).filter(PersonChange.event_id == event.id, PersonChange.id > cur["c"]).order_by(PersonChange.id).limit(PAGE):
        out_cursor["c"] = r.id
        changes.append({"cedula": r.user_id, "at": _iso(r.at), "kind": r.kind, "old_value": r.old_value, "new_value": r.new_value, "detail": r.detail})
    extra, more_extra = {}, False
    areas, items, exhibitors = node_extra.area_names(db, event.id), node_extra.item_names(db, event.id), node_extra.exhibitor_map(db, event.id)
    for key, k, model, ser in (("edits", "e", PersonChangeLog, node_extra.edit_row), ("areas", "m", AreaMovement, lambda r: node_extra.area_row(r, areas)),
                               ("deliveries", "d", InventoryDelivery, lambda r: node_extra.delivery_row(r, items)), ("turns", "t", QueueTurn, node_extra.turn_row),
                               ("calls", "q", QueueCall, node_extra.call_row), ("roulette", "r", RouletteDraw, node_extra.roulette_row),
                               ("leads", "x", ExhibitorLead, lambda r: node_extra.lead_row(r, exhibitors))):
        rows = db.query(model).filter(model.event_id == event.id, model.id > cur[k]).order_by(model.id).limit(PAGE).all()
        if rows:
            out_cursor[k] = rows[-1].id
        extra[key] = [x for x in (ser(r) for r in rows) if x]
        more_extra = more_extra or len(rows) >= PAGE
    more = len(atts) >= PAGE or len(logs) >= PAGE or len(prints) >= PAGE or len(changes) >= PAGE or more_extra
    return {"cursor": out_cursor, "persons": persons, "access_logs": logs, "print_logs": prints, "person_changes": changes, **extra, "more": more}


# ------------------------------------------------------------------------------------------------ SERVIDOR LOCAL
def node_tag() -> str:
    """Prefijo propio de este servidor para los identificadores que sube en un evento compartido: dos servidores nunca generan el mismo (sus ids locales SÍ pueden coincidir).
    Sale de la identificación de la instalación (la deja el instalador); sin ella, del nombre del servidor."""
    from app import local_env
    local_env.refresh()
    raw = (os.getenv("INSTALLATION_ID") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{8,}", raw):
        return "s" + raw[:10]
    name = re.sub(r"[^a-z0-9]+", "", (os.getenv("NODE_NAME") or "").lower())[:10]
    return "s" + (name or "local")


def apply_changes(db: Session, event: Event, data: dict, tag: Optional[str] = None) -> dict:
    """Aplica en ESTE servidor lo que bajó de la nube. Idempotente: aplicar dos veces el mismo lote no cambia nada. Devuelve conteos de lo agregado. No hace commit."""
    tag = tag or node_tag()
    tenant = event.tenant_id
    added = {"persons": 0, "access_logs": 0, "print_logs": 0, "person_changes": 0}
    persons = [p for p in (data.get("persons") or []) if isinstance(p, dict) and str(p.get("cedula") or "").strip()]
    if persons:
        ids = [str(p["cedula"]).strip() for p in persons]
        have_att = {uid for (uid,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(ids))}
        have_user = {uid for (uid,) in db.query(User.id).filter(User.tenant_id == tenant, User.id.in_(ids))}
        codes = {c.lower() for (c,) in db.query(EventAttendee.code).filter(EventAttendee.event_id == event.id, EventAttendee.code.isnot(None))}
        for p in persons:
            uid = str(p["cedula"]).strip()
            if uid in have_att:
                continue                                         # ya estaba en este evento: no se pisan sus datos (gana la primera alta)
            if uid not in have_user:
                u = User(id=uid, tenant_id=tenant, **{f: (p.get(f) or None) for f in PERSON_FIELDS})
                u.set_extras({str(k): str(v) for k, v in (p.get("extra_fields") or {}).items()} if isinstance(p.get("extra_fields"), dict) else {})
                bd = p.get("birth_date")
                if bd:
                    try:
                        u.birth_date = datetime.fromisoformat(str(bd)).date()
                    except ValueError:
                        pass
                db.add(u)
                db.flush()
                have_user.add(uid)
            code = (str(p.get("code")).strip() or None) if p.get("code") else None
            if code and code.lower() in codes:
                code = None                                      # el código ya lo tiene otra persona aquí: se queda sin código (se ve en la persona) antes que romper la regla de únicos
            att = EventAttendee(event_id=event.id, user_id=uid, tenant_id=tenant, origin=(str(p.get("origin"))[:16] if p.get("origin") else None), code=code,
                                certificate=bool(p.get("certificate")), from_peer=True, created_at=utcnow())
            att.set_categories(p.get("categories") if isinstance(p.get("categories"), list) else [])
            db.add(att)
            have_att.add(uid)
            if code:
                codes.add(code.lower())
            added["persons"] += 1
        db.flush()

    logs = [r for r in (data.get("access_logs") or []) if isinstance(r, dict) and r.get("cedula") and r.get("client_id")]
    if logs:
        cids = [str(r["client_id"])[:64] for r in logs]
        known = {c for (c,) in db.query(AccessLog.client_id).filter(AccessLog.event_id == event.id, AccessLog.client_id.in_(cids))}
        uids = list({str(r["cedula"]) for r in logs})
        present = {uid for (uid,) in db.query(User.id).filter(User.tenant_id == tenant, User.id.in_(uids))}
        nuevo = {uid for (uid,) in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.record_type == "Nuevo", AccessLog.user_id.in_(uids))}
        for r in logs:
            cid, uid = str(r["client_id"])[:64], str(r["cedula"])
            if cid in known or cid.startswith(tag + "-") or uid not in present:
                continue                                         # ya está, es de este mismo servidor (vuelve de la nube) o la persona no existe aquí
            kind = str(r.get("record_type") or "Existente")[:20]
            if kind == "Nuevo" and uid in nuevo:
                continue                                         # el alta de esta persona ya está registrada aquí
            db.add(AccessLog(tenant_id=tenant, user_id=uid, record_type=kind, event_id=event.id, client_id=cid, timestamp=_when(r.get("timestamp")) or utcnow(),
                             registration_method=(str(r.get("method"))[:20] if r.get("method") else None), doubtful_reason=(str(r.get("doubtful"))[:24] if r.get("doubtful") else None),
                             from_peer=True))
            known.add(cid)
            if kind == "Nuevo":
                nuevo.add(uid)
            added["access_logs"] += 1

    for r in (data.get("print_logs") or []):
        uid, at = str((r or {}).get("cedula") or ""), _when((r or {}).get("printed_at"))
        kind = "pre" if (r or {}).get("kind") == "pre" else "normal"
        if not uid or at is None or not db.query(User.id).filter(User.id == uid, User.tenant_id == tenant).first():
            continue
        if db.query(PrintLog.id).filter(PrintLog.event_id == event.id, PrintLog.user_id == uid, PrintLog.printed_at == at, PrintLog.kind == kind).first():
            continue
        db.add(PrintLog(tenant_id=tenant, user_id=uid, event_id=event.id, printed_at=at, kind=kind, from_peer=True))
        added["print_logs"] += 1

    for r in (data.get("person_changes") or []):
        r = r or {}
        uid, at, kind = (str(r.get("cedula")) if r.get("cedula") else None), _when(r.get("at")), str(r.get("kind") or "")[:24]
        if not kind or at is None:
            continue
        q = db.query(PersonChange.id).filter(PersonChange.event_id == event.id, PersonChange.kind == kind, PersonChange.at == at, PersonChange.new_value == (r.get("new_value") or None))
        q = q.filter(PersonChange.user_id == uid) if uid else q.filter(PersonChange.user_id.is_(None))
        if q.first():
            continue
        db.add(PersonChange(tenant_id=tenant, event_id=event.id, user_id=uid, kind=kind, at=at, old_value=(r.get("old_value") or None), new_value=(r.get("new_value") or None),
                            detail=(str(r.get("detail"))[:200] if r.get("detail") else None), from_peer=True))
        node_extra.apply_person_change_effect(db, event, kind, uid, at, r.get("new_value") or None)          # deshacer registro / fecha de nacimiento: también aquí
        added["person_changes"] += 1
    db.flush()
    extra = node_extra.apply_all(db, event, data, from_peer=True)          # ediciones, áreas, inventario, turnos y llamados de los otros servidores
    added.update({k: v for k, v in extra.items() if v})
    return added


def save_cursor(event: Event, cursor: dict) -> None:
    c = clean_cursor(cursor)
    c["at"] = utcnow().isoformat()
    event.peer_cursor = json.dumps(c)


def last_pull_at(event: Event) -> Optional[str]:
    try:
        return (json.loads(event.peer_cursor or "{}") or {}).get("at")
    except ValueError:
        return None
