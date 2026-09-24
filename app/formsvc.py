"""Servicios de los Formularios Web (Sprint 5) que sí tocan la base: estado vigente, resolución de personas para el
pre-llenado, carga de inscripciones a la base del evento y rutas de archivos. La lógica pura vive en `app/formlib.py`."""
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app import formlib
from app.models import AccessLog, Event, EventAttendee, FormEvent, FormInvite, FormPayment, FormPerson, FormSubmission, User, WebForm
from app.timeutil import to_local

# columnas de un Excel de pre-llenado (en minúscula) -> clave del campo del evento
COLUMN_TO_KEY = {
    "id": "id", "cedula": "id", "cédula": "id", "identificacion": "id", "identificación": "id", "documento": "id",
    "nombres": "first_name", "nombre": "first_name", "apellidos": "last_name", "apellido": "last_name",
    "cargo": "role", "entidad": "entity", "empresa": "entity", "telefono": "phone", "teléfono": "phone", "tel. celular": "phone",
    "correo": "email", "e-mail corporativo": "email", "email": "email", "tipo de asistente": "opt_1", "tipo_asistente": "opt_1",
}


def form_files_dir(tenant_id: str, form_id: int) -> str:
    path = os.path.join("data", tenant_id, "form_files", str(form_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_design(form: WebForm) -> dict:
    return json.loads(form.design_json)


def get_settings(form: WebForm) -> dict:
    return {**formlib.DEFAULT_SETTINGS, **(json.loads(form.settings_json) if form.settings_json else {})}


def get_schedule(form: WebForm) -> list:
    return json.loads(form.schedule_json) if form.schedule_json else []


def now_local() -> datetime:
    return to_local(datetime.utcnow()).replace(tzinfo=None)


def status_of(form: WebForm, at: Optional[datetime] = None) -> str:
    return formlib.effective_status(form.manual_status, form.use_schedule, get_schedule(form), at or now_local())


PENDING = "awaiting_payment"          # FormSubmission.status mientras se espera la confirmación de Wompi
PENDING_HOLD = timedelta(minutes=30)  # una inscripción esperando pago aparta su cupo este tiempo
PENDING_PURGE = timedelta(hours=24)   # y se borra pasado este (antes podría llegar una aprobación tardía)


def real_submissions(db: Session, form: WebForm):
    """Inscripciones REALES confirmadas (sin pruebas y sin las que esperan un pago)."""
    return db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == False, FormSubmission.status == "confirmed")  # noqa: E712


def held_count(db: Session, form: WebForm) -> int:
    """Cupo ocupado: inscripciones reales confirmadas + las que están pagando ahora (esperan a Wompi hasta 30 min)."""
    holding = db.query(FormPayment).filter(FormPayment.form_id == form.id, FormPayment.status == "pending", FormPayment.is_test == False,  # noqa: E712
                                           FormPayment.submission_id != None, FormPayment.created_at > datetime.utcnow() - PENDING_HOLD).count()  # noqa: E711
    return real_submissions(db, form).count() + holding


def is_full(db: Session, form: WebForm) -> bool:
    return form.capacity is not None and held_count(db, form) >= form.capacity


def discard_submission(db: Session, form: WebForm, sub: FormSubmission) -> None:
    """Borra una inscripción (y sus archivos) que nunca llegó a confirmarse. Los pagos que la referenciaban quedan
    como registro financiero, sin inscripción."""
    event = db.query(Event).filter(Event.id == form.event_id).first()
    for v in json.loads(sub.data_json).values():
        if isinstance(v, dict) and v.get("stored") and event:
            try:
                os.remove(os.path.join(form_files_dir(event.tenant_id, form.id), os.path.basename(v["stored"])))
            except OSError:
                pass
    db.query(FormPayment).filter(FormPayment.submission_id == sub.id).update({"submission_id": None}, synchronize_session=False)
    db.delete(sub)


def purge_stale_pending(db: Session, form: WebForm) -> None:
    """Quita las inscripciones en espera de pago de más de 24 h (abandonadas). Se llama de forma perezosa al enviar."""
    for sub in db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == PENDING,
                                               FormSubmission.created_at < datetime.utcnow() - PENDING_PURGE):
        discard_submission(db, form, sub)


def finalize_submission(db: Session, form: WebForm, sub: FormSubmission) -> None:
    """Todo lo que ocurre cuando una inscripción queda CONFIRMADA (sin pago: al enviar; con pago: al aprobarse):
    marca de envío para la analítica, invitación usada y —si el formulario lo pide— carga a la base del evento."""
    sub.status = "confirmed"
    db.add(FormEvent(form_id=form.id, sid=sub.sid or os.urandom(4).hex(), kind="submit", source=sub.source, is_test=sub.is_test))
    if sub.invite_id:
        inv = db.query(FormInvite).filter_by(id=sub.invite_id).first()
        if inv:
            inv.used_at = datetime.utcnow()
    db.commit()
    if get_settings(form)["feed"] == "realtime" and not sub.is_test:
        from app.routers.api import _upsert_attendee
        feed_submission(db, form, sub, _upsert_attendee)
        db.commit()


def public_state(db: Session, form: WebForm) -> str:
    """Lo que ve el público: activo | pruebas | cerrado | cupo_lleno | finalizado. `cupo_lleno` se ve igual que
    `cerrado` (misma plantilla) pero se distingue para los reportes."""
    st = status_of(form)
    if st == "activo" and is_full(db, form):
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
    sub.fed = True
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
    form.fed_at = datetime.utcnow()
    db.commit()
    return {"fed": done, "problems": problems}
