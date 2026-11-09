"""Turnos y filas (Fase 8): lo que toca la base. La lógica pura está en app/queue_turns.py.

Rendimiento: la gente abre la página de su turno y la pantalla de TV sondea cada pocos segundos. Por eso el estado completo del evento se calcula UNA vez cada `SNAPSHOT_TTL`
segundos por proceso y se reparte desde la memoria (nadie consulta la base por su cuenta). Cualquier cambio en este proceso lo invalida al instante; en otros procesos vence en segundos."""
import io
import json
import secrets
import threading
import time
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import minors, queue_turns as qt, testperson
from app.models import AccessLog, Event, EventAttendee, FormSubmission, QueueCall, QueueTurn, User
from app.timeutil import utcnow

SNAPSHOT_TTL = 3.0
_cache: dict = {}
_lock = threading.Lock()
ATTEMPTS = 6


# ------------------------------------------------------------------------------------------------------------------------ configuración
def get_config(event: Event) -> dict:
    try:
        raw = json.loads(event.queue_config_json) if event.queue_config_json else {}
    except ValueError:
        raw = {}
    try:
        return qt.clean_config(raw)
    except qt.QueueError:
        return qt.clean_config({})


def set_config(db: Session, event: Event, enabled: bool, raw: dict) -> dict:
    cfg = qt.clean_config(raw)
    in_use = db.query(QueueTurn.id).filter(QueueTurn.event_id == event.id).first() is not None
    if in_use:
        old = get_config(event)
        if {l["letter"] for l in old["lanes"]} - {l["letter"] for l in cfg["lanes"]}:
            used = {r[0] for r in db.query(QueueTurn.lane).filter(QueueTurn.event_id == event.id).distinct()}
            gone = used - {l["letter"] for l in cfg["lanes"]}
            if gone:
                raise qt.QueueError("Ya hay turnos en la fila " + ", ".join(sorted(gone)) + ": no se puede quitar. Reinicia los turnos primero.")
    event.queue_enabled = bool(enabled)
    event.queue_config_json = json.dumps(cfg, ensure_ascii=False)
    invalidate(event.id)
    return cfg


# ------------------------------------------------------------------------------------------------------------------------ estado en memoria
def invalidate(event_id: int) -> None:
    with _lock:
        _cache.pop(event_id, None)


def _name_for(user: Optional[User]) -> str:
    if user is None or not user.first_name or minors.is_minor(user.birth_date) or user.is_biometric_enabled is False:
        return ""                                                    # menores (o sin dato fiable): nunca su nombre
    return " ".join(str(user.first_name).split()[:1]).title()


def _build(db: Session, event: Event) -> dict:
    cfg = get_config(event)
    rows = db.query(QueueTurn).filter(QueueTurn.event_id == event.id).all()
    names = {}
    if cfg["show_name"] and rows:
        for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_([r.user_id for r in rows])).all():
            names[u.id] = _name_for(u)
    turns = [{"token": r.token, "user_id": r.user_id, "lane": r.lane, "number": r.number, "rank": r.rank, "status": r.status, "desk": r.desk or "", "called_seq": r.called_seq,
              "name": names.get(r.user_id, "")} for r in rows]
    calls = db.query(QueueCall).filter(QueueCall.event_id == event.id).order_by(QueueCall.id.desc()).limit(8).all()
    recent = [{"id": c.id, "label": qt.label(c.lane, c.number), "lane": c.lane, "desk": c.desk or "", "at": c.called_at.isoformat() + "Z"} for c in calls]
    snap = qt.build_snapshot(cfg["lanes"], turns, recent, cfg["show_name"])
    snap["enabled"] = bool(event.queue_enabled)
    snap["event_name"] = event.name
    snap["mode"] = cfg["mode"]
    snap["total"] = len(turns)
    return snap


def snapshot(db: Session, event: Event, ttl: float = SNAPSHOT_TTL) -> dict:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(event.id)
        if hit and now - hit[0] < ttl:
            return hit[1]
    snap = _build(db, event)
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[event.id] = (now, snap)
    return snap


# ------------------------------------------------------------------------------------------------------------------------ asignar turnos
def _attendee_ids(db: Session, event: Event) -> set:
    return testperson.drop_test({r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id).all()})


def _existing_ids(db: Session, event: Event) -> set:
    return {r[0] for r in db.query(QueueTurn.user_id).filter(QueueTurn.event_id == event.id).all()}


def _last_numbers(db: Session, event_id: int) -> dict:
    return {lane: n for lane, n in db.query(QueueTurn.lane, func.max(QueueTurn.number)).filter(QueueTurn.event_id == event_id).group_by(QueueTurn.lane).all()}


def _people(db: Session, event: Event, mode: str, cfg: dict) -> list:
    ids = _attendee_ids(db, event) - _existing_ids(db, event)
    if not ids:
        return []
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids)).all()}
    arrived, registered = {}, {}
    if mode == "arrival":
        for uid, ts in db.query(AccessLog.user_id, func.min(AccessLog.timestamp)).filter(AccessLog.event_id == event.id, AccessLog.user_id.in_(ids)).group_by(AccessLog.user_id).all():
            arrived[uid] = ts.isoformat()
    if mode == "form":
        for pid, ts in db.query(FormSubmission.person_id, func.min(FormSubmission.created_at)).filter(
                FormSubmission.event_id == event.id, FormSubmission.is_test.is_(False), FormSubmission.status == "confirmed", FormSubmission.person_id.in_(ids)).group_by(FormSubmission.person_id).all():
            registered[pid] = ts.isoformat()
    out = []
    for uid in ids:
        u = users.get(uid)
        p = {"user_id": uid, "first_name": getattr(u, "first_name", "") or "", "last_name": getattr(u, "last_name", "") or "",
             "arrived_at": arrived.get(uid), "registered_at": registered.get(uid)}
        if mode == "arrival" and cfg["require_registered"] and uid not in arrived:
            continue                                                  # por llegada: solo quien ya fue acreditado
        if mode == "form" and uid not in registered:
            continue                                                  # por formulario: solo quien se inscribió
        out.append(p)
    return out


def _new_token() -> str:
    return secrets.token_urlsafe(18)


def assign_batch(db: Session, event: Event, mode: Optional[str] = None, manual: Optional[dict] = None) -> dict:
    """Crea los turnos que faltan (nunca toca los que ya existen ni cambia un número). `manual` = resultado de parse_manual_rows."""
    cfg = get_config(event)
    mode = mode or cfg["mode"]
    start = _last_numbers(db, event.id)
    explicit = None
    unknown = 0
    if manual is not None:
        attend = _attendee_ids(db, event) - _existing_ids(db, event)
        keep = [p for p in manual["people"] if p["user_id"] in attend]
        unknown = len(manual["people"]) - len(keep)
        ordered = [{"user_id": p["user_id"]} for p in keep]
        explicit = {p["user_id"]: p["lane"] for p in keep if p["lane"]}
        source = "manual"
    else:
        ordered = qt.order_people(mode, _people(db, event, mode, cfg))
        source = mode
    assigned = qt.assign_numbers(ordered, cfg["lanes"], start, explicit)
    for a in assigned:
        db.add(QueueTurn(event_id=event.id, user_id=a["user_id"], lane=a["lane"], number=a["number"], rank=a["rank"], token=_new_token(), source=source))
    db.flush()
    invalidate(event.id)
    return {"created": len(assigned), "unknown": unknown}


def assign_one(db: Session, event: Event, user_id: str) -> Optional[QueueTurn]:
    """Turno de UNA persona (la que escanea el QR). Si ya tiene, lo devuelve. Modo por llegada: lo crea ahora (exige estar en la base del evento y, si la configuración lo pide, haber sido
    acreditada). Otros modos: solo devuelve el que ya se le asignó. None si no corresponde."""
    cfg = get_config(event)
    user_id = qt.clean_cedula(user_id)
    if not user_id or testperson.is_test(user_id):
        return None
    turn = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.user_id == user_id).first()
    if turn or cfg["mode"] != "arrival":
        return turn
    if user_id not in _attendee_ids(db, event):
        return None
    if cfg["require_registered"] and db.query(AccessLog.id).filter(AccessLog.event_id == event.id, AccessLog.user_id == user_id).first() is None:
        return None
    for _ in range(ATTEMPTS):
        waiting = {lane: n for lane, n in db.query(QueueTurn.lane, func.count(QueueTurn.id)).filter(QueueTurn.event_id == event.id, QueueTurn.status == "waiting").group_by(QueueTurn.lane).all()}
        lane = qt.pick_lane(cfg["lanes"], waiting)
        number = (db.query(func.max(QueueTurn.number)).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane).scalar() or 0) + 1
        turn = QueueTurn(event_id=event.id, user_id=user_id, lane=lane, number=number, rank=number, token=_new_token(), source="arrival")
        try:
            with db.begin_nested():
                db.add(turn)
                db.flush()
            invalidate(event.id)
            return turn
        except IntegrityError:
            existing = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.user_id == user_id).first()
            if existing:
                return existing                                       # otra petición ya se lo dio
    return None


def reset_turns(db: Session, event: Event) -> int:
    """Rehace los turnos: borra los que siguen esperando o saltados. Los llamados y atendidos se conservan (ya ocurrieron)."""
    ids = [r[0] for r in db.query(QueueTurn.id).filter(QueueTurn.event_id == event.id, QueueTurn.status.in_(("waiting", "skipped"))).all()]
    if ids:
        db.query(QueueCall).filter(QueueCall.turn_id.in_(ids)).delete(synchronize_session=False)
        db.query(QueueTurn).filter(QueueTurn.id.in_(ids)).delete(synchronize_session=False)
    invalidate(event.id)
    return len(ids)


def delete_event_data(db: Session, event_id: int) -> None:
    db.query(QueueCall).filter(QueueCall.event_id == event_id).delete(synchronize_session=False)
    db.query(QueueTurn).filter(QueueTurn.event_id == event_id).delete(synchronize_session=False)
    invalidate(event_id)


# ------------------------------------------------------------------------------------------------------------------------ operar la fila
def _next_seq(db: Session, event_id: int) -> int:
    return (db.query(func.max(QueueTurn.called_seq)).filter(QueueTurn.event_id == event_id).scalar() or 0) + 1


def _lane_ok(cfg: dict, lane: str) -> str:
    lane = str(lane or "").strip().upper()
    if lane not in {l["letter"] for l in cfg["lanes"]}:
        raise qt.QueueError("Esa fila no existe")
    return lane


def _clean_desk(desk) -> str:
    return " ".join(str(desk or "").split())[:40]


def call_next(db: Session, event: Event, staff_id: int, lane: str, desk: str = "") -> Optional[QueueTurn]:
    """Llama al siguiente de la fila. Cierra (atendido) el que ESTE puesto/persona llamó antes en esa fila. None si no hay nadie esperando."""
    lane = _lane_ok(get_config(event), lane)
    desk = _clean_desk(desk)
    turn = (db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane, QueueTurn.status == "waiting")
            .order_by(QueueTurn.rank, QueueTurn.id).with_for_update(skip_locked=True).first())
    if turn is None:
        return None
    now = utcnow()
    for prev in db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane, QueueTurn.status == "called", QueueTurn.called_by_id == staff_id).all():
        prev.status, prev.done_at = "done", now
    turn.status, turn.desk, turn.called_by_id, turn.called_at, turn.called_seq = "called", desk or None, staff_id, now, _next_seq(db, event.id)
    db.add(QueueCall(event_id=event.id, turn_id=turn.id, lane=turn.lane, number=turn.number, desk=desk or None, called_by_id=staff_id, called_at=now))
    db.flush()
    invalidate(event.id)
    return turn


def _turn(db: Session, event: Event, turn_id: int) -> QueueTurn:
    t = db.query(QueueTurn).filter(QueueTurn.id == turn_id, QueueTurn.event_id == event.id).first()
    if t is None:
        raise qt.QueueError("Ese turno no existe")
    return t


def repeat_call(db: Session, event: Event, staff_id: int, lane: str) -> Optional[QueueTurn]:
    """Vuelve a anunciar el último llamado de la fila (la pantalla suena otra vez)."""
    lane = _lane_ok(get_config(event), lane)
    t = (db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.lane == lane, QueueTurn.status == "called").order_by(QueueTurn.called_seq.desc()).first())
    if t is None:
        return None
    now = utcnow()
    t.called_seq, t.called_at = _next_seq(db, event.id), now
    db.add(QueueCall(event_id=event.id, turn_id=t.id, lane=t.lane, number=t.number, desk=t.desk, called_by_id=staff_id, called_at=now))
    db.flush()
    invalidate(event.id)
    return t


def skip_turn(db: Session, event: Event, turn_id: int) -> QueueTurn:
    t = _turn(db, event, turn_id)
    if t.status not in ("waiting", "called"):
        raise qt.QueueError("Ese turno ya no se puede saltar")
    t.status = "skipped"
    db.flush()
    invalidate(event.id)
    return t


def requeue_turn(db: Session, event: Event, turn_id: int) -> QueueTurn:
    """Un saltado vuelve al FINAL de su fila (mismo turno, nuevo lugar)."""
    t = _turn(db, event, turn_id)
    if t.status not in ("skipped", "called"):
        raise qt.QueueError("Ese turno ya está en la fila")
    t.status = "waiting"
    t.rank = (db.query(func.max(QueueTurn.rank)).filter(QueueTurn.event_id == event.id, QueueTurn.lane == t.lane).scalar() or 0) + 1
    db.flush()
    invalidate(event.id)
    return t


def finish_turn(db: Session, event: Event, turn_id: int) -> QueueTurn:
    t = _turn(db, event, turn_id)
    t.status, t.done_at = "done", utcnow()
    db.flush()
    invalidate(event.id)
    return t


def queue_listing(db: Session, event: Event, lane: Optional[str] = None, limit: int = 60) -> dict:
    """Para la consola del operador: esperando (en orden), saltados y último llamado por fila. Con nombre y cédula (es del personal, no público)."""
    q = db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.status.in_(("waiting", "skipped", "called")))
    if lane:
        q = q.filter(QueueTurn.lane == lane)
    rows = q.order_by(QueueTurn.lane, QueueTurn.rank, QueueTurn.id).all()
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_({r.user_id for r in rows})).all()} if rows else {}

    def item(t: QueueTurn) -> dict:
        u = users.get(t.user_id)
        return {"id": t.id, "label": qt.label(t.lane, t.number), "lane": t.lane, "status": t.status, "desk": t.desk or "", "user_id": t.user_id,
                "name": " ".join(x for x in ((u.first_name if u else ""), (u.last_name if u else "")) if x)}
    waiting = [item(t) for t in rows if t.status == "waiting"]
    return {"waiting": waiting[:limit], "waiting_total": len(waiting), "skipped": [item(t) for t in rows if t.status == "skipped"][:limit], "called": [item(t) for t in rows if t.status == "called"]}


def find_by_person(db: Session, event: Event, user_id: str) -> Optional[QueueTurn]:
    return db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.user_id == qt.clean_cedula(user_id)).first()


# ------------------------------------------------------------------------------------------------------------------------ Excel
def read_manual_excel(data: bytes, filename: str, lanes: list) -> dict:
    """Lee el Excel del orden manual con las mismas defensas que las demás cargas (zip sin macros ni partes enormes, solo lectura, tope de filas)."""
    from app import variant_table
    from openpyxl import load_workbook
    try:
        variant_table.check_archive(data, filename)
    except variant_table.ExcelRejected as e:
        raise qt.QueueError(str(e))
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > qt.MAX_MANUAL_ROWS + 1:
                raise qt.QueueError(f"El Excel tiene demasiadas filas (máximo {qt.MAX_MANUAL_ROWS})")
            rows.append(list(row[:6]))
        wb.close()
    except qt.QueueError:
        raise
    except Exception:
        raise qt.QueueError("No se pudo leer el Excel: usa un archivo .xlsx con la plantilla")
    return qt.parse_manual_rows(rows, lanes)


def manual_template(lanes: list) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Turnos"
    ws.append(["Cédula", "Orden", "Fila"])
    for c in ws[1]:
        c.font = Font(bold=True)
    letters = [l["letter"] for l in lanes]
    for i, ced in enumerate(("1010101010", "2020202020", "3030303030"), start=1):
        ws.append([ced, i, letters[(i - 1) % len(letters)]])
    ws.column_dimensions["A"].width = 18
    ws2 = wb.create_sheet("Instrucciones")
    for line in ("Una persona por fila, en el orden en que quieres llamarla.", "Cédula: obligatoria; debe estar en la base del evento (las demás se omiten).",
                 "Orden: número; si lo dejas vacío se usa el orden del archivo.", "Fila: la letra de la fila (A, B…); si la dejas vacía se reparten parejo entre las filas.",
                 "Borra las tres filas de ejemplo antes de subir tu lista."):
        ws2.append([line])
    ws2.column_dimensions["A"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
