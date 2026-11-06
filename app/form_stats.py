"""Estadísticas de UN formulario para la página «Estadísticas» (staff y cliente de formulario): cupos, inscritos y distribución por las variables de elección.

SOLO AGREGADOS: nunca nombres, cédulas, correos ni ninguna respuesta individual. De las respuestas únicamente se cuentan los campos de ELECCIÓN (lista desplegable, opciones, casillas),
cuyos valores son las opciones que el propio formulario ofrece. Los campos de texto libre, correo, teléfono, fecha, número o archivo nunca entran aquí."""
import json
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import analytics as an
from app import formlib, formsvc
from app.models import Event, FormEvent, FormSubmission, WebForm
from app.timeutil import utcnow

CHOICE_TYPES = ("select", "radio", "multiselect", "checkbox")
MAX_ITEMS = 25                     # opciones mostradas por variable; el resto se agrupa en «Otros»
_STATUS_LABELS = {"activo": "Abierto", "pruebas": "En pruebas", "cerrado": "Cerrado", "finalizado": "Finalizado", "cupo_lleno": "Cupo lleno"}
_OP_TEXT = {"equals": "es", "not_equals": "no es", "contains": "contiene", "in": "es alguno de", "filled": "está respondido"}


def _pct(part: int, total: int) -> int:
    return round(100 * part / total) if total else 0


def _describe_rule(rule: dict, design: dict) -> str:
    """«Ciudad es Bogotá y Categoría es VIP»: en palabras, con los nombres de los campos tal como los ve la persona."""
    parts = []
    for c in rule["conds"]:
        label = (design["fields"].get(c["field"]) or {}).get("label") or c["field"]
        value = c.get("value")
        value = ", ".join(value) if isinstance(value, list) else (value or "")
        text = _OP_TEXT.get(c.get("op", "equals"), c.get("op", ""))
        parts.append(f"{label} {text} {value}".strip())
    return (" o " if rule.get("match") == "any" else " y ").join(parts)


def _quotas(db: Session, form: WebForm, design: dict) -> list:
    rules = formsvc.quota_rules(form)
    if not rules:
        return []
    counts = formsvc.quota_counts(db, form, rules)
    db.commit()                                         # `quota_counts` puede recalcular llaves de inscripciones antiguas: se guardan para no repetirlo
    out = []
    now = formsvc.now_local()
    for r in rules:
        used = counts.get(r["id"], 0)
        info = formlib.rule_schedule_info(r, now)
        by_date = bool(info) and info["state"] != "abierto"
        out.append({"id": r["id"], "label": r["label"], "rule": _describe_rule(r, design), "limit": r["limit"], "used": used,
                    "left": 0 if by_date else max(0, r["limit"] - used), "pct": 100 if r["limit"] == 0 else min(100, _pct(used, r["limit"])), "closed": r["limit"] == 0 or by_date, "full": used >= r["limit"],
                    "schedule": info})
    return out


def _distributions(design: dict, subs: list) -> list:
    out = []
    for fid, f in design["fields"].items():
        if f["type"] not in CHOICE_TYPES:
            continue
        counts: dict = {}
        answered = 0
        for s in subs:
            v = s.get(fid)
            if isinstance(v, list):
                vals = [str(x) for x in v if x not in (None, "")]
            elif v is True:
                vals = ["Sí"]
            elif v is False:
                vals = ["No"]
            elif isinstance(v, str) and v:
                vals = [v]
            else:
                vals = []
            if vals:
                answered += 1
            for x in vals:
                counts[x] = counts.get(x, 0) + 1
        for o in f.get("options") or []:                # las opciones sin ninguna respuesta también se muestran (en 0)
            counts.setdefault(o, 0)
        if f["type"] == "checkbox" and not f.get("options"):
            counts.setdefault("Sí", 0)
        if not counts:
            continue
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        head, tail = ordered[:MAX_ITEMS], ordered[MAX_ITEMS:]
        items = [{"label": k, "count": n, "pct": _pct(n, answered)} for k, n in head]
        if tail:
            n = sum(x for _, x in tail)
            items.append({"label": f"Otros ({len(tail)} opciones)", "count": n, "pct": _pct(n, answered)})
        out.append({"id": fid, "label": f.get("label") or fid, "answered": answered, "featured": bool(f.get("stats")), "items": items})
    out.sort(key=lambda d: not d["featured"])           # primero las marcadas «genera estadísticas»; el orden del formulario se conserva dentro de cada grupo
    return out


def build(db: Session, form: WebForm, include_tests: bool = False) -> dict:
    design = formsvc.get_design(form)
    event: Optional[Event] = db.query(Event).filter(Event.id == form.event_id).first()
    q = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed")
    if not include_tests:
        q = q.filter(FormSubmission.is_test == False)  # noqa: E712
    rows = q.order_by(FormSubmission.id).all()
    values = [json.loads(r.data_json) for r in rows]
    n = len(rows)

    cf = next((fid for fid, f in design["fields"].items() if f["type"] == formlib.COMPANIONS_TYPE), None)
    companions = sum(len(v.get(cf) or []) for v in values) if cf else None

    ev_q = db.query(FormEvent.kind, func.count(func.distinct(FormEvent.sid))).filter(FormEvent.form_id == form.id)
    if not include_tests:
        ev_q = ev_q.filter(FormEvent.is_test == False)  # noqa: E712
    seen = dict(ev_q.group_by(FormEvent.kind).all())
    visits = int(seen.get("view", 0))

    capacity = None
    if form.capacity:
        used = formsvc.held_count(db, form)
        capacity = {"total": form.capacity, "used": used, "left": max(0, form.capacity - used), "pct": min(100, _pct(used, form.capacity)), "full": used >= form.capacity}

    state = formsvc.public_state(db, form)
    timeline = an.time_series("timeline", "Inscripciones en el tiempo", [r.created_at for r in rows], label="Inscripciones")
    return {
        "form": {"id": form.id, "name": form.name, "state": state, "state_label": _STATUS_LABELS.get(state, state)},
        "event": {"name": event.name if event else ""},
        "generated_at": utcnow().isoformat(timespec="seconds") + "Z",
        "includes_tests": include_tests,
        "summary": {"registered": n, "companions": companions, "people_total": n + (companions or 0), "visits": visits,
                    "conversion_pct": _pct(n, visits) if visits else None, "last_at": an.fmt_local(rows[-1].created_at) if rows else None},
        "capacity": capacity,
        "quotas": _quotas(db, form, design),
        "distributions": _distributions(design, values),
        "timeline": timeline,
    }
