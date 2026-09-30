"""Servicios de los Formularios Web (Sprint 5) que sí tocan la base: estado vigente, resolución de personas para el
pre-llenado, carga de inscripciones a la base del evento y rutas de archivos. La lógica pura vive en `app/formlib.py`."""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from app.timeutil import utcnow
from typing import Optional, Tuple

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session

from app import formlib, jobs
from app.models import AccessLog, Event, EventAttendee, FormDiscountCode, FormEvent, FormInvite, FormPayment, FormPerson, FormSubmission, User, WebForm
from app.storage import form_file_key, get_storage
from app.timeutil import to_local
from app.ttlcache import TTLCache

log = logging.getLogger("golden.forms")

# Estado público de un formulario (lo que ven miles de personas al abrir el enlace): se calcula una vez cada pocos segundos, no una vez por visita.
# Vale solo dentro del proceso; cualquier cosa que importe (cupo, duplicados, precio) se vuelve a comprobar al enviar. Ver docs/14_FASE0_RESULTADOS.md.
PUBLIC_CACHE_SECONDS = float(os.getenv("FORM_PUBLIC_CACHE_SECONDS", "5"))
public_cache = TTLCache(PUBLIC_CACHE_SECONDS)


def invalidate_public_cache() -> None:
    public_cache.clear()
    _held_cache.clear()

# columnas de un Excel de pre-llenado (en minúscula) -> clave del campo del evento
COLUMN_TO_KEY = {
    "id": "id", "cedula": "id", "cédula": "id", "identificacion": "id", "identificación": "id", "documento": "id",
    "nombres": "first_name", "nombre": "first_name", "apellidos": "last_name", "apellido": "last_name",
    "cargo": "role", "entidad": "entity", "empresa": "entity", "telefono": "phone", "teléfono": "phone", "tel. celular": "phone",
    "correo": "email", "e-mail corporativo": "email", "email": "email", "tipo de asistente": "opt_1", "tipo_asistente": "opt_1",
}


def get_design(form: WebForm) -> dict:
    return json.loads(form.design_json)


def get_settings(form: WebForm) -> dict:
    return {**formlib.DEFAULT_SETTINGS, **(json.loads(form.settings_json) if form.settings_json else {})}


def get_schedule(form: WebForm) -> list:
    return json.loads(form.schedule_json) if form.schedule_json else []


def now_local() -> datetime:
    return to_local(utcnow()).replace(tzinfo=None)


def status_of(form: WebForm, at: Optional[datetime] = None) -> str:
    return formlib.effective_status(form.manual_status, form.use_schedule, get_schedule(form), at or now_local())


PENDING = "awaiting_payment"          # FormSubmission.status mientras se espera la confirmación de Wompi
PENDING_HOLD = timedelta(minutes=30)  # una inscripción esperando pago aparta su cupo este tiempo
PENDING_PURGE = timedelta(hours=24)   # y se borra pasado este (antes podría llegar una aprobación tardía)


def real_submissions(db: Session, form: WebForm):
    """Inscripciones REALES confirmadas (sin pruebas y sin las que esperan un pago)."""
    return db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == False, FormSubmission.status == "confirmed")  # noqa: E712


CODE_MESSAGES = {"invalid": "Ese código no es válido", "exhausted": "Ese código ya se agotó", "not_applicable": "Ese código no aplica con lo que respondiste"}


def normalize_code(raw) -> str:
    return re.sub(r"\s+", "", str(raw or "")).upper()[:40]


def code_uses(db: Session, code: FormDiscountCode) -> int:
    """Usos de un código: inscripciones reales confirmadas + las que están pagando ahora (mismo criterio que el cupo)."""
    return db.query(FormSubmission).filter(
        FormSubmission.discount_code_id == code.id, FormSubmission.is_test == False,  # noqa: E712
        or_(FormSubmission.status == "confirmed", and_(FormSubmission.status == PENDING, FormSubmission.created_at > utcnow() - PENDING_HOLD))).count()


def price_context(db: Session, form: WebForm, pay: dict, link, code):
    """Lo que la persona trae para el precio: la clave del enlace por el que entró (`?d=`) y el código que escribió.
    Devuelve (ctx para `compute_amount`, fila del código o None, problema: None|invalid|exhausted)."""
    ctx = {"links": {str(link)[:40]} if link else set(), "codes": set()}
    norm = normalize_code(code)
    if not norm:
        return ctx, None, None
    row = db.query(FormDiscountCode).filter_by(form_id=form.id, code=norm).first()
    if not row or not any(d.get("id") == row.discount_id and d.get("how") == "code" for d in pay.get("discounts", [])):
        return ctx, None, "invalid"
    if code_uses(db, row) >= row.max_uses:
        return ctx, None, "exhausted"
    ctx["codes"].add(row.discount_id)
    return ctx, row, None


def quota_rules(form: WebForm) -> list:
    """Reglas de cupo vigentes: solo cuentan las condiciones sobre campos que existen y guardan respuestas (una sobre un campo borrado no debe
    bloquear —ni liberar— a nadie por accidente)."""
    design = get_design(form)
    ok = {fid for fid, f in design["fields"].items() if f["type"] in formlib.INPUT_TYPES}
    out = []
    for r in get_settings(form)["quotas"].get("rules", []):
        conds = [c for c in r["conds"] if c["field"] in ok]
        if conds and len(conds) == len(r["conds"]):
            out.append({**r, "conds": conds})
    return out


def quota_match(rule: dict, values: dict) -> bool:
    met = [formlib.condition_met(c, values) for c in rule["conds"]]
    return any(met) if rule["match"] == "any" else all(met)


def rule_sig(rule: dict) -> str:
    """Firma estable de un cupo: cambia si cambian sus condiciones, así una inscripción vieja no cuenta para un cupo que ya es otro."""
    digest = hashlib.sha1(json.dumps({"m": rule["match"], "c": rule["conds"]}, sort_keys=True).encode()).hexdigest()[:10]
    return f"{rule['id']}~{digest}"


def quota_keys_for(rules: list, values: dict) -> str:
    """`|firma|firma|` de los cupos que cumple una inscripción ('' si ninguno). Se guarda en `form_submissions.quota_keys` al insertar, para contar
    en SQL sin releer ni interpretar el JSON de todas las inscripciones (con miles, hacerlo dentro del bloqueo del cupo era lo más lento del envío)."""
    sigs = [rule_sig(r) for r in rules if quota_match(r, values)]
    return f"|{'|'.join(sigs)}|" if sigs else ""


def invalidate_quota_keys(db: Session, form: WebForm) -> None:
    """Las reglas de cupo cambiaron: las llaves guardadas ya no valen; se recalculan solas la próxima vez que se cuente."""
    db.query(FormSubmission).filter(FormSubmission.form_id == form.id).update({"quota_keys": None}, synchronize_session=False)


def rebuild_quota_keys(db: Session, form: WebForm, rules: list) -> None:
    """Recalcula las llaves de las inscripciones que no las tienen (inscripciones anteriores a esta versión, o reglas editadas)."""
    for sub in db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.quota_keys == None):  # noqa: E711
        sub.quota_keys = quota_keys_for(rules, json.loads(sub.data_json))
    db.flush()


def quota_counts(db: Session, form: WebForm, rules: list) -> dict:
    """{id de la regla: inscripciones que la cumplen}: confirmadas reales + las que están pagando ahora (30 min), sin pruebas. Una sola consulta."""
    if not rules:
        return {}
    if db.query(FormSubmission.id).filter(FormSubmission.form_id == form.id, FormSubmission.quota_keys == None).first():  # noqa: E711
        rebuild_quota_keys(db, form, rules)
    hold = utcnow() - PENDING_HOLD
    cols = [func.count(FormSubmission.id).filter(func.strpos(FormSubmission.quota_keys, f"|{rule_sig(r)}|") > 0) for r in rules]
    row = db.query(*cols).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == False,  # noqa: E712
                                 or_(FormSubmission.status == "confirmed", and_(FormSubmission.status == PENDING, FormSubmission.created_at > hold))).one()
    return {r["id"]: row[i] for i, r in enumerate(rules)}


def quota_status(db: Session, form: WebForm) -> list:
    rules = quota_rules(form)
    counts = quota_counts(db, form, rules)
    return [{"id": r["id"], "used": counts[r["id"]], "left": max(0, r["limit"] - counts[r["id"]])} for r in rules]


def quota_public(db: Session, form: WebForm) -> dict:
    """Para el formulario público: `left` {campo: {opción: cupos que quedan}} de los cupos simples (una sola condición «es igual a» → se deshabilita la
    opción) y `full` las reglas llenas (el navegador avisa si lo que la persona lleva escrito cae en una de ellas)."""
    rules = quota_rules(form)
    if not rules:
        return {"left": {}, "full": []}
    counts = quota_counts(db, form, rules)
    left: dict = {}
    full = []
    for r in rules:
        remaining = max(0, r["limit"] - counts[r["id"]])
        if len(r["conds"]) == 1 and r["conds"][0]["op"] == "equals" and isinstance(r["conds"][0]["value"], str):
            c = r["conds"][0]
            left.setdefault(c["field"], {})[c["value"]] = min(remaining, left.get(c["field"], {}).get(c["value"], remaining))
        if remaining == 0:
            full.append({"label": r["label"], "match": r["match"], "conds": r["conds"]})
    return {"left": left, "full": full}


def held_count(db: Session, form: WebForm) -> int:
    """Cupo ocupado: inscripciones reales confirmadas + las que están pagando ahora (esperan a Wompi hasta 30 min). UNA sola consulta (antes eran dos)."""
    from sqlalchemy import select
    confirmed = select(func.count()).select_from(FormSubmission).where(
        FormSubmission.form_id == form.id, FormSubmission.is_test == False, FormSubmission.status == "confirmed").scalar_subquery()  # noqa: E712
    holding = select(func.count()).select_from(FormPayment).where(
        FormPayment.form_id == form.id, FormPayment.status == "pending", FormPayment.is_test == False,  # noqa: E712
        FormPayment.submission_id != None, FormPayment.created_at > utcnow() - PENDING_HOLD).scalar_subquery()  # noqa: E711
    return int(db.execute(select(confirmed + holding)).scalar() or 0)


_held_cache = TTLCache(float(os.getenv("FORM_HELD_CACHE_SECONDS", "2")))


def invalidate_held() -> None:
    """Se libera (o cambia) un cupo: la caché del «lleno» de ESTE proceso se olvida al instante (otros procesos, hasta ~2 s)."""
    _held_cache.clear()


def bump_held(form: WebForm) -> None:
    """Este proceso acaba de apartar un cupo (confirmado o esperando pago): si la caché del conteo existe, sube en 1, así la vía rápida ve el «lleno» sin esperar
    a que venza (en otros procesos, hasta ~2 s; el bloqueo de la base siempre manda)."""
    cur = _held_cache.get(form.id)
    if form.capacity is not None and cur is not None:
        _held_cache.set(form.id, cur + 1)


def held_count_cached(db: Session, form: WebForm) -> int:
    """`held_count` con caché de unos segundos y una sola recarga a la vez. SOLO para la vía rápida de «cupo lleno» (rechazar sin pedir el bloqueo): un dato viejo puede
    rechazar unos segundos de más si se liberó un cupo, pero NUNCA deja pasar de más: quien pasa se vuelve a comprobar con el bloqueo dentro de `form_reserve_slot`."""
    return _held_cache.get_or_compute(form.id, lambda: held_count(db, form))


def mark_full(form: WebForm) -> None:
    """La base acaba de decir «lleno» bajo bloqueo: los siguientes envíos se rechazan sin pedir el bloqueo durante unos segundos."""
    if form.capacity is not None:
        _held_cache.set(form.id, form.capacity)


def has_confirmed_sid(db: Session, form: WebForm, sid: Optional[str], person_id: Optional[str]) -> bool:
    """¿Ya hay una inscripción confirmada con esta clave de envío (y esta persona)? Misma condición que el reintento de `form_reserve_slot`, sin bloqueo:
    un reintento con la MISMA `sid` debe responder «replayed» aunque el formulario ya esté lleno."""
    if not sid:
        return False
    q = db.query(FormSubmission.id).filter(FormSubmission.form_id == form.id, FormSubmission.sid == sid, FormSubmission.is_test == False,  # noqa: E712
                                           FormSubmission.status == "confirmed")
    if person_id is not None:
        q = q.filter(FormSubmission.person_id == person_id)
    return q.first() is not None


def precheck(db: Session, form: WebForm, sid: Optional[str], person_id: Optional[str], is_test: bool) -> Tuple[bool, bool]:
    """(reintento, duplicado) con UNA lectura SIN bloqueo, ANTES de pedir el `FOR UPDATE` del formulario. Mismas condiciones que `form_reserve_slot` (migración 0049): reintento =
    ya hay una inscripción confirmada con esta `sid` (y esta persona, si viene); duplicado = ya hay una confirmada real con esta cédula (las pruebas nunca cuentan). Es solo un
    adelanto para no hacer fila por algo que ya se sabe: la reserva bajo bloqueo sigue siendo la autoridad y repite todas sus comprobaciones."""
    from sqlalchemy import false, select
    fs = FormSubmission
    retry_q = false()
    if sid:
        conds = [fs.form_id == form.id, fs.sid == sid, fs.is_test == is_test, fs.status == "confirmed"]
        if person_id is not None:
            conds.append(fs.person_id == person_id)
        retry_q = select(fs.id).where(*conds).exists()
    dup_q = false()
    if person_id is not None and not is_test:
        dup_q = select(fs.id).where(fs.form_id == form.id, fs.is_test == False, fs.status == "confirmed", fs.person_id == person_id).exists()  # noqa: E712
    if not sid and (person_id is None or is_test):
        return False, False
    row = db.execute(select(retry_q, dup_q)).one()
    return bool(row[0]), bool(row[1])


def is_full(db: Session, form: WebForm, held: Optional[int] = None) -> bool:
    if form.capacity is None:
        return False
    return (held if held is not None else held_count(db, form)) >= form.capacity


# `set_config(..., true)` = SET LOCAL (solo esta transacción; vale con el pooler de Neon en modo transacción). Contrapresión: si el bloqueo de la fila del formulario no se
# consigue en FORM_LOCK_TIMEOUT_MS (3 s) la base lanza `lock_not_available` (55P03) y el envío responde 503 + Retry-After en vez de retener hilo y conexión hasta que Firebase
# corte a los 60 s. Las dos sentencias viajan en UNA ida y vuelta.
FORM_LOCK_TIMEOUT_MS = int(os.getenv("FORM_LOCK_TIMEOUT_MS", "3000"))
_RESERVE_SQL = text("SELECT set_config('lock_timeout', :lock_timeout, true); SELECT form_reserve_slot(:form_id, :person_id, :sid, :is_test, :hold_from, CAST(:matched AS jsonb))")


def reserve_slot(db: Session, form: WebForm, person_id: Optional[str], sid: Optional[str], is_test: bool, rules: list, values: dict) -> dict:
    """Reintento, cupos por variable, cupo total y duplicado en UNA ida y vuelta (función `form_reserve_slot`, migración 0049). Deja la fila del
    formulario bloqueada hasta el commit de quien llama: el INSERT de la inscripción va después, en la misma transacción.
    Devuelve {"ok": True} o {"ok": False, "reason": "retry"|"quota"|"capacity"|"duplicate"|"not_found", "label"?}."""
    params = {"lock_timeout": f"{FORM_LOCK_TIMEOUT_MS}ms", "form_id": form.id, "person_id": person_id, "sid": sid, "is_test": is_test, "hold_from": utcnow() - PENDING_HOLD,
              "matched": json.dumps([{"sig": rule_sig(r), "limit": r["limit"], "label": r["label"]} for r in rules if quota_match(r, values)])}
    res = db.execute(_RESERVE_SQL, params).scalar()
    if res.get("reason") == "rebuild":          # reglas recién editadas: la fila ya está bloqueada, se recalculan las llaves y se repite
        rebuild_quota_keys(db, form, rules)
        res = db.execute(_RESERVE_SQL, params).scalar()
    return res


def discard_submission(db: Session, form: WebForm, sub: FormSubmission) -> None:
    """Borra una inscripción (y sus archivos) que nunca llegó a confirmarse. Los pagos que la referenciaban quedan
    como registro financiero, sin inscripción."""
    event = db.query(Event).filter(Event.id == form.event_id).first()
    for v in json.loads(sub.data_json).values():
        if isinstance(v, dict) and v.get("stored") and event:
            get_storage().delete(form_file_key(event.tenant_id, form.id, v["stored"]))
    db.query(FormPayment).filter(FormPayment.submission_id == sub.id).update({"submission_id": None}, synchronize_session=False)
    db.delete(sub)
    invalidate_held()


def purge_stale_pending(db: Session, form: WebForm) -> None:
    """Quita las inscripciones en espera de pago de más de 24 h (abandonadas). Se llama de forma perezosa al enviar."""
    for sub in db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == PENDING,
                                               FormSubmission.created_at < utcnow() - PENDING_PURGE):
        discard_submission(db, form, sub)


def confirm_submission(db: Session, form: WebForm, sub: FormSubmission, record_event: bool = True) -> bool:
    """La parte BARATA de confirmar una inscripción (sin confirmar la transacción: la confirma quien llama, junto con lo demás): estado, marca de envío
    para la analítica, invitación usada y —si el formulario carga en tiempo real— el trabajo en segundo plano que la pasa a la base del evento y envía
    la escarapela (correo, base de datos, etc.: nada de eso ocurre dentro de la petición ni dentro del bloqueo del cupo).
    Devuelve True si encoló un trabajo (quien llama solo necesita despertar al worker en ese caso)."""
    enqueued = False
    sub.status = "confirmed"
    if record_event:          # el envío del formulario público lo registra después del commit (`forms_public._record_submit_event`), fuera del bloqueo del cupo
        db.add(FormEvent(form_id=form.id, sid=sub.sid or os.urandom(4).hex(), kind="submit", source=sub.source, is_test=sub.is_test))
    if sub.invite_id:
        inv = db.query(FormInvite).filter_by(id=sub.invite_id).first()
        if inv:
            inv.used_at = utcnow()
    if get_settings(form)["feed"] == "realtime" and not sub.is_test:
        db.flush()
        jobs.enqueue(db, "form_feed", {"submission_id": sub.id}, dedupe_key=str(sub.id))
        enqueued = True
    return enqueued


def finalize_submission(db: Session, form: WebForm, sub: FormSubmission) -> None:
    """Todo lo que ocurre cuando una inscripción queda CONFIRMADA cuando no hay nada más que hacer en la misma transacción (el pago aprobado
    de Wompi lo usa): confirma, guarda y despierta al worker."""
    confirm_submission(db, form, sub)
    db.commit()
    jobs.kick()


def run_feed_job(submission_id: int) -> None:
    """Manejador del trabajo `form_feed`: pasa UNA inscripción a la base del evento y envía la escarapela virtual. Idempotente (`sub.fed`)."""
    from app.database import SessionLocal
    from app.routers.api import _upsert_attendee
    db = SessionLocal()
    try:
        sub = db.get(FormSubmission, submission_id)
        if not sub or sub.fed or sub.status != "confirmed" or sub.is_test:
            return
        form = db.get(WebForm, sub.form_id)
        err = feed_submission(db, form, sub, _upsert_attendee)
        if err:
            log.warning("inscripción %s no se cargó a la base: %s", submission_id, err)
        db.commit()
    finally:
        db.close()


def public_state(db: Session, form: WebForm, held: Optional[int] = None) -> str:
    """Lo que ve el público: activo | pruebas | cerrado | cupo_lleno | finalizado. `cupo_lleno` se ve igual que
    `cerrado` (misma plantilla) pero se distingue para los reportes."""
    st = status_of(form)
    if st == "activo" and is_full(db, form, held):
        return "cupo_lleno"
    return st


# ------------------------------------------------------------------ personas (pre-llenado)
def _person_from_user(u: User, attendee: Optional[EventAttendee]) -> dict:
    data = {"id": u.id, "first_name": u.first_name or "", "last_name": u.last_name or "", "role": u.role or "", "entity": u.entity or "",
            "phone": u.phone or "", "email": u.email or "", "opt_1": u.opt_1 or ""}
    data.update({k: v for k, v in u.get_extras().items()})
    return data


def source_event_id(form: WebForm) -> Optional[int]:
    src = get_settings(form)["prefill"]["source"]
    if src == "event":
        return form.event_id
    m = re.fullmatch(r"event:(\d+)", src)
    return int(m.group(1)) if m else None


def find_person(db: Session, form: WebForm, person_id: str) -> Optional[dict]:
    """Datos de `person_id` según la fuente elegida al crear el formulario (base del evento, la de otro evento del
    mismo cliente, o una base subida solo para este formulario). None si no está."""
    person_id = (person_id or "").strip()
    if not person_id:
        return None
    src = get_settings(form)["prefill"]["source"]
    if src == "upload":
        row = db.query(FormPerson).filter_by(form_id=form.id, person_id=person_id).first()
        return json.loads(row.data_json) if row else None
    event_id = source_event_id(form)
    event = db.query(Event).filter(Event.id == event_id).first() if event_id else None
    own = db.query(Event).filter(Event.id == form.event_id).first()
    if not event or event.tenant_id != own.tenant_id:
        return None
    user = db.query(User).filter(User.id == person_id, User.tenant_id == event.tenant_id).first()
    if not user:
        return None
    in_event = db.query(EventAttendee).filter_by(event_id=event.id, user_id=person_id).first() or \
        db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.user_id == person_id, AccessLog.record_type != "Actualizado").first()
    return _person_from_user(user, None) if in_event else None


def source_people(db: Session, form: WebForm) -> list:
    """Todas las personas de la fuente (para generar invitaciones): lista de dicts con `id` y sus datos."""
    src = get_settings(form)["prefill"]["source"]
    if src == "upload":
        return [json.loads(r.data_json) for r in db.query(FormPerson).filter_by(form_id=form.id)]
    event_id = source_event_id(form)
    own = db.query(Event).filter(Event.id == form.event_id).first()
    event = db.query(Event).filter(Event.id == event_id).first() if event_id else None
    if not event or event.tenant_id != own.tenant_id:
        return []
    ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id)}
    ids |= {l.user_id for l in db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado")}
    return [_person_from_user(u, None) for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids)).order_by(User.last_name)] if ids else []


def prefill_values(design: dict, person: dict) -> dict:
    """{field_id: valor} de los campos vinculados a la base (por `key`) que la persona ya tiene."""
    out = {}
    for fid, f in design["fields"].items():
        key = f.get("key")
        if key and person.get(key) not in (None, ""):
            out[fid] = person[key]
    return out


# ------------------------------------------------------------------ carga a la base del evento
def key_values(design: dict, data: dict) -> dict:
    """{clave del evento: valor} de una inscripción (solo los campos vinculados a la base)."""
    out = {}
    for fid, f in design["fields"].items():
        key = f.get("key")
        if key and fid in data and data[fid] not in (None, "", []):
            out[key] = data[fid] if not isinstance(data[fid], list) else ", ".join(data[fid])
    return out


def badge_email_field(design: dict) -> Optional[str]:
    """El campo de correo al que se asocia la escarapela virtual: el vinculado al «Correo» del evento, o el primer campo de tipo correo."""
    fields = design["fields"]
    for fid, f in fields.items():
        if f["type"] == "email" and f.get("key") == "email":
            return fid
    return next((fid for fid, f in fields.items() if f["type"] == "email"), None)


def wants_digital_badge(db: Session, form: WebForm) -> bool:
    """¿Este formulario envía la escarapela virtual? Solo si la casilla está marcada Y el evento tiene activado el módulo (Parámetros)."""
    if not get_settings(form)["send_digital_badge"]:
        return False
    event = db.query(Event).filter(Event.id == form.event_id).first()
    return bool(event and event.digital_badge_enabled)


def _send_digital_badge(db: Session, form: WebForm, event: Event, sub: FormSubmission, person_id: str, upsert_attendee) -> None:
    """Asocia el correo de la inscripción a la escarapela virtual de la persona y se la envía (una sola vez). Nunca lanza: la inscripción
    ya quedó cargada y un fallo de correo no debe deshacerla; el resultado queda en el registro del envío (`digital_sent_at`)."""
    from app import digital_badge
    try:
        design = get_design(form)
        fid = badge_email_field(design)
        email = str(json.loads(sub.data_json).get(fid) or "").strip() if fid else ""
        contact = digital_badge.normalize_contact(email)
        if not contact:
            return
        upsert_attendee(db, event.id, person_id, event.tenant_id, digital_contact=contact)
        db.flush()
        att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=person_id).first()
        if att and not att.digital_sent_at:
            user = db.query(User).filter(User.id == person_id, User.tenant_id == event.tenant_id).first()
            digital_badge.send_digital_badge(db, event, att, (user.first_name if user else "") or "", "", (user.last_name if user else "") or "")
    except Exception:       # noqa: BLE001 — ver docstring
        log.error("no se pudo enviar la escarapela virtual de la inscripción %s", sub.id, exc_info=True)


def feed_submission(db: Session, form: WebForm, sub: FormSubmission, upsert_attendee) -> Optional[str]:
    """Carga UNA inscripción a la base del evento como «No registrado» (Usuario + asistente del evento). Devuelve un
    mensaje de error si no se pudo (p. ej. no trae cédula) o None. No toca AccessLog: no queda registrado."""
    design = get_design(form)
    event = db.query(Event).filter(Event.id == form.event_id).first()
    kv = key_values(design, json.loads(sub.data_json))
    person_id = str(kv.get("id") or "").strip()
    if not person_id:
        return "La inscripción no trae cédula, no se pudo cargar a la base"
    user = db.query(User).filter(User.id == person_id, User.tenant_id == event.tenant_id).first()
    if not user:
        user = User(id=person_id, tenant_id=event.tenant_id)
        db.add(user)
    for key, attr in (("first_name", "first_name"), ("last_name", "last_name"), ("role", "role"), ("entity", "entity"),
                      ("phone", "phone"), ("email", "email"), ("opt_1", "opt_1")):
        if kv.get(key):
            setattr(user, attr, str(kv[key]))
    extras = user.get_extras()
    extras.update({k: str(v) for k, v in kv.items() if k.startswith("opcional_")})
    user.set_extras(extras)
    db.flush()
    upsert_attendee(db, event.id, person_id, event.tenant_id)
    db.flush()          # autoflush=False: sin esto, el segundo upsert (correo de la escarapela) no vería la fila y la duplicaría
    sub.fed = True
    if not sub.is_test and wants_digital_badge(db, form):
        _send_digital_badge(db, form, event, sub, person_id, upsert_attendee)
    return None


def feed_pending(db: Session, form: WebForm, upsert_attendee) -> dict:
    """Carga todas las inscripciones reales que aún no están en la base."""
    done, problems = 0, []
    for sub in real_submissions(db, form).filter(FormSubmission.fed == False).order_by(FormSubmission.id):  # noqa: E712
        err = feed_submission(db, form, sub, upsert_attendee)
        if err:
            problems.append(f"Inscripción {sub.id}: {err}")
        else:
            done += 1
    form.fed_at = utcnow()
    db.commit()
    return {"fed": done, "problems": problems}


@jobs.handler("form_feed")
def _form_feed_job(payload: dict) -> None:
    run_feed_job(payload["submission_id"])
