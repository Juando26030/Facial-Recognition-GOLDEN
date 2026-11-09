"""Historial de cambios del evento por campo y correo de aviso cuando cambia un campo «clave» (Fase 5, decisión del 8-nov-2026).

* Campo clave = el que la plantilla de evento marca como OBLIGATORIO (app/event_template.py). Todo cambio queda en `event_change_log`; solo los de campos clave avisan por correo.
* `snapshot` (lee el evento) y `diff_event` (PURA: compara dos instantáneas con la plantilla) se llaman en el mismo punto del guardado: `before = snapshot(...)`, cambiar el evento,
  `record(...)`, `commit`, y si `record` devolvió algo, `jobs.kick()`.
* Privacidad: solo campos DEL EVENTO, nunca datos de asistentes. Los campos de tipo «contacto» se guardan ocultos («[oculto]») y todo valor se recorta a MAX_VALUE.
* Correos: un guardado = UN correo por destinatario (comercial y coordinador del evento, distintos de quien cambió, sin repetir y solo con correo válido). El trabajo (`event_change_mail`)
  lleva solo ids y es idempotente por `dedupe_key`. Nada de nombres ni valores en logs.
"""
import html
import json
import logging
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import event_template as et
from app.auth import sees_event_tenant, staff_with_role
from app import event_template_svc, jobs, publicurl
from app.database import SessionLocal
from app.mailer import clean_subject, send_mail
from app.models import Event, EventChangeLog, EventState, StaffUser, SuperEvent
from app.staff_credentials import valid_email
from app.timeutil import to_local, utcnow

log = logging.getLogger("golden.event_history")

KIND = "event_change_mail"
MAX_VALUE = 300                  # largo del valor guardado (la columna admite 500)
HIDDEN = "[oculto]"
SENSITIVE_TYPES = ("contact",)          # tipos de campo cuyo valor no se guarda
SOURCES = ("edit", "state", "switch", "import")
PAGE_MAX = 100

# Columnas de texto/fecha de `events` que registra el historial (la clave es la de la plantilla de evento).
SCALAR_KEYS = ("name", "country", "city", "location", "address", "start_date", "end_date", "event_time_start", "event_time_end", "setup_date", "setup_time_start", "setup_time_end", "notes")
EXTRA_LABELS = {"state_id": "Estado", "bandana": "Color de pañoleta"}
STATE_KEYS = ("state_id",)          # los que se registran con source «state»
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


# ------------------------------------------------------------------------------------------------------------------------------------ valores (puros)
def norm(value):
    """Valor comparable: vacío (None, '', espacios, [], {}) -> None; fecha -> ISO; hora 'H:MM' -> 'HH:MM'; número entero con decimales cero -> entero; listas/dicts -> JSON estable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if value else None
    text = str(value).strip()
    if not text:
        return None
    m = _TIME.match(text)
    if m and int(m.group(1)) < 24:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return text


def _fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def show(value, ftype: Optional[str] = None) -> Optional[str]:
    """Texto legible y recortado que se guarda y se muestra. None = vacío."""
    if value is None:
        return None
    if ftype in SENSITIVE_TYPES:
        return HIDDEN
    if isinstance(value, bool):
        return "Sí" if value else "No"
    text = str(value)
    if ftype == "date" or (isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)):
        text = _fmt_date(text)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE - 1] + "…"


def _fields_by_key(template: Optional[dict]) -> dict:
    return {f["key"]: f for f in ((template or {}).get("fields") or [])}


def diff_event(before: dict, after: dict, template: Optional[dict] = None) -> list:
    """Cambios entre dos instantáneas ({clave: valor}). PURA. Devuelve [{key, label, old, new, required, source}] en el orden de la plantilla (después, los demás por clave).
    Una clave que falta en una de las dos cuenta como vacía (un campo nuevo que se llena es un cambio; vacío -> vacío no lo es)."""
    by_key = _fields_by_key(template)
    order = {k: i for i, k in enumerate(by_key)}
    keys = sorted(set(before) | set(after), key=lambda k: (order.get(k, len(order)), k))
    out = []
    for k in keys:
        old, new = norm(before.get(k)), norm(after.get(k))
        if old == new:
            continue
        f = by_key.get(k)
        ftype = f["type"] if f else None
        label = (f["title"] if f else None) or EXTRA_LABELS.get(k) or et.default_title_for(k)
        out.append({"key": k, "label": label, "old": show(old, ftype), "new": show(new, ftype), "required": bool(f and f.get("required")),
                    "source": "state" if k in STATE_KEYS else ("switch" if k.startswith("sw_") else "edit")})
    return out


# ------------------------------------------------------------------------------------------------------------------------------------ instantánea (lee el evento)
def _staff_name(db: Session, staff_id) -> Optional[str]:
    if not staff_id:
        return None
    s = db.get(StaffUser, staff_id)
    return ((s.full_name or "").strip() or s.username) if s is not None else f"#{staff_id}"


def snapshot(db: Session, event: Event) -> dict:
    """Los campos del evento que registra el historial, ya con nombres en vez de ids. No toca la base más que para esos nombres (db.get usa el caché de la sesión)."""
    snap = {k: getattr(event, k, None) for k in SCALAR_KEYS}
    snap["coordinator_staff_id"] = _staff_name(db, event.coordinator_staff_id)
    snap["commercial_staff_id"] = _staff_name(db, event.commercial_staff_id)
    sup = db.get(SuperEvent, event.super_event_id) if event.super_event_id else None
    snap["super_event_id"] = sup.name if sup is not None else (f"#{event.super_event_id}" if event.super_event_id else None)
    snap["bandana"] = " ".join(x for x in ((event.bandana_color_name or "").strip(), (event.bandana_color or "").strip()) if x) or None
    state = db.get(EventState, event.state_id) if event.state_id else None
    snap["state_id"] = state.name if state is not None else event.status
    for sw in et.SWITCH_KEYS:
        snap[et.switch_field_key(sw)] = bool(getattr(event, sw, False))
    for k, v in event.get_extra().items():
        snap[k] = v
    return snap


# ------------------------------------------------------------------------------------------------------------------------------------ registrar y avisar
def record(db: Session, event: Event, before: dict, staff: Optional[StaffUser], source: str = "edit", notify: bool = True) -> list:
    """Compara `before` con el estado actual del evento, agrega las filas del historial a la transacción (no confirma) y, si algún campo clave cambió, encola los correos. Devuelve las filas
    nuevas ([] si no cambió nada). Quien llama confirma y, si la lista no está vacía, llama `jobs.kick()` (se puede llamar siempre)."""
    template = event_template_svc.load(db)
    changes = diff_event(before, snapshot(db, event), template)
    if not changes:
        return []
    now = utcnow()
    rows = []
    for c in changes:
        row = EventChangeLog(event_id=event.id, field_key=c["key"][:64], field_label=c["label"][:120], old_value=c["old"], new_value=c["new"],
                             changed_by_id=staff.id if staff is not None else None, changed_at=now, source=c["source"] if source == "edit" else source)
        rows.append(row)
    db.add_all(rows)
    db.flush()
    key_rows = [r for r, c in zip(rows, changes) if c["required"]]
    if notify and key_rows:
        for rid in recipients(db, event, staff):
            jobs.enqueue(db, KIND, {"event_id": int(event.id), "log_ids": [int(r.id) for r in key_rows], "to_staff_id": int(rid), "actor_id": int(staff.id) if staff is not None else 0},
                         max_attempts=4, dedupe_key=f"{KIND}:{key_rows[0].id}:{rid}")
    return rows


def kick_after(rows: list) -> None:
    """Después del commit: despierta la cola si el guardado dejó filas (puede haber encolado correos de campos clave)."""
    if rows:
        jobs.kick()


def recipients(db: Session, event: Event, actor: Optional[StaffUser]) -> list:
    """Ids de quienes reciben el aviso de cambio de campos clave: la comercial y el coordinador del evento, más TODAS las cuentas de almacén y de contabilidad (plan de la Fase 5). Sin repetir, sin
    quien hizo el cambio, activos, no archivados y con un correo válido."""
    out = []
    candidates = [event.commercial_staff_id, event.coordinator_staff_id]
    for role in ("almacen", "contabilidad"):
        candidates += [s.id for s in staff_with_role(db, role)]
    for sid in candidates:
        if not sid or sid in out or (actor is not None and sid == actor.id):
            continue
        s = db.get(StaffUser, sid)
        if s is None or not s.is_active or s.archived_at is not None or not valid_email(s.email) or not sees_event_tenant(s, event):          # F5-9 D (D2): ni de otro cliente
            continue
        out.append(sid)
    return out


def render_mail(event_name: str, changes: list, actor_name: str, when: datetime, url: str = "") -> dict:
    """{subject, text, html}. `changes`: [{label, old, new}]. Un solo campo: el asunto lo nombra; varios: «N campos»."""
    labels = [c["label"] for c in changes]
    what = labels[0] if len(labels) == 1 else f"{len(labels)} campos"
    subject = clean_subject(f"Cambio en el evento {event_name}: {what}")
    local = to_local(when).strftime("%d/%m/%Y %H:%M") if when else ""
    who = actor_name or "el sistema"
    head = f"Se modificó el evento «{event_name}»."
    lines = [f"- {c['label']}: {c['old'] or '(vacío)'} → {c['new'] or '(vacío)'}" for c in changes]
    foot = f"Cambio hecho por {who}" + (f" el {local} (hora de Colombia)." if local else ".")
    text = "\n".join([head, ""] + lines + ["", foot] + ([f"Ver el evento: {url}"] if url else []))
    e = html.escape
    li = "".join(f"<li><b>{e(c['label'])}:</b> {e(c['old'] or '(vacío)')} &rarr; {e(c['new'] or '(vacío)')}</li>" for c in changes)
    link = f"<p><a href=\"{e(url)}\">Ver el evento</a></p>" if url else ""
    body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\"><p>{e(head)}</p>"
            f"<ul style=\"padding-left:18px\">{li}</ul><p style=\"font-size:13px;color:#555\">{e(foot)}</p>{link}</div>")
    return {"subject": subject, "text": text, "html": body}


def event_url(event_id: int) -> str:
    base = publicurl.base()
    return f"{base}/kiosk/{event_id}" if base else ""


@jobs.handler("event_change_mail")
def run_mail(payload: dict) -> None:
    event_id, to_id, ids = int(payload["event_id"]), int(payload["to_staff_id"]), [int(i) for i in payload.get("log_ids") or []]
    actor_id = int(payload.get("actor_id") or 0)
    with SessionLocal() as db:
        target = db.get(StaffUser, to_id)
        to = valid_email(target.email) if target is not None else ""
        event = db.get(Event, event_id)
        if target is None or not to or not target.is_active or target.archived_at is not None or event is None or event.archived_at is not None:
            return                                           # ya no corresponde avisar: no es un error
        rows = db.query(EventChangeLog).filter(EventChangeLog.event_id == event_id, EventChangeLog.id.in_(ids)).order_by(EventChangeLog.id).all()
        if not rows:
            return
        mail = render_mail(event.name, [{"label": r.field_label, "old": r.old_value, "new": r.new_value} for r in rows], _staff_name(db, actor_id) or "", rows[0].changed_at, event_url(event_id))
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("cambio de evento: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el correo de cambio de evento")


# ------------------------------------------------------------------------------------------------------------------------------------ leer
def history(db: Session, event_id: int, *, field: Optional[str] = None, page: int = 1, per_page: int = 25) -> dict:
    """Página del historial (lo más nuevo primero), con el nombre de quien cambió. `field` filtra por clave de campo. Horas en UTC ISO (el navegador las muestra en hora local)."""
    per_page = max(1, min(int(per_page or 25), PAGE_MAX))
    page = max(1, int(page or 1))
    q = db.query(EventChangeLog).filter(EventChangeLog.event_id == event_id)
    if field:
        q = q.filter(EventChangeLog.field_key == field)
    total = q.count()
    rows = q.order_by(EventChangeLog.changed_at.desc(), EventChangeLog.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    names = {}
    for r in rows:
        if r.changed_by_id and r.changed_by_id not in names:
            names[r.changed_by_id] = _staff_name(db, r.changed_by_id)
    fields = db.query(EventChangeLog.field_key, EventChangeLog.field_label).filter(EventChangeLog.event_id == event_id).distinct().order_by(EventChangeLog.field_label).all()
    return {"total": total, "page": page, "per_page": per_page,
            "fields": [{"key": k, "label": lbl} for k, lbl in fields],
            "items": [{"id": r.id, "field_key": r.field_key, "field_label": r.field_label, "old_value": r.old_value, "new_value": r.new_value, "source": r.source,
                       "changed_by": names.get(r.changed_by_id), "changed_at": r.changed_at.isoformat() + "Z",
                       "changed_at_local": to_local(r.changed_at).strftime("%d/%m/%Y %H:%M")} for r in rows]}
