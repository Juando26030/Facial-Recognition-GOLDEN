"""Siembra en la base de STAGING el evento y el formulario de la prueba de carga de la Fase 4 (datos 100 % sintéticos: nadie real, encodings aleatorios).

Como Cloud Run Job (la imagen de la app ya trae este script; DATABASE_URL de `golden_app` alcanza: solo inserta filas):
    gcloud run jobs execute golden-ops-staging --region "$REGION" --args="-m,scripts.seed_load_staging,--people,5000,--capacity,4000" --wait
    gcloud run jobs execute golden-ops-staging --region "$REGION" --args="-m,scripts.seed_load_staging,--verify" --wait        # después de la prueba

Idempotente (no duplica). Imprime UNA línea `LOAD_SEED {json}` con los ids que necesitan los generadores (event_id, form_slug): nada secreto. La contraseña de la
cuenta `carga_dig` (digitador) se DERIVA de OPS_TOKEN (scripts/load_cfg.py) y nunca se imprime.
Se niega a correr si DEPLOY_ENV no es «staging» o DATABASE_URL no es de Neon: producción también vivirá en Neon, así que el host solo no basta.

`--capacity` (por defecto 4000) es MENOR que los 5.000 envíos de la prueba a propósito: comprueba el cupo (los envíos sobrantes deben recibir 409 «cupo completo»,
nunca pasar de 4.000 ni dar 5xx). `--verify` cuenta inscripciones (confirmadas, cédulas repetidas) y escaneos por cédula duplicados, solo cifras."""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def guard() -> None:
    """Solo staging en Neon (se llama al ejecutar el script; las pruebas usan las funciones directamente sobre su base de pruebas)."""
    host = (urlsplit(os.environ.get("DATABASE_URL", "")).hostname or "")
    if not host.endswith(".neon.tech") or os.environ.get("DEPLOY_ENV") != "staging":
        sys.exit(f"Solo para la base de staging en Neon con DEPLOY_ENV=staging (host={host!r}, DEPLOY_ENV={os.environ.get('DEPLOY_ENV')!r}).")


from sqlalchemy import func, insert, text  # noqa: E402

from app import formlib  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AccessLog, Event, EventAttendee, EventStaffAuthorization, FormSubmission, StaffUser, Tenant, User, WebForm  # noqa: E402
from app.timeutil import utcnow  # noqa: E402
from scripts.load_cfg import EVENT_CODE, FORM_SLUG, TENANT, USERNAME, derived_password  # noqa: E402


def seed(db, people: int, capacity: int) -> dict:
    import numpy as np
    if not db.get(Tenant, TENANT):
        db.add(Tenant(id=TENANT, client_code="CARGA-STG", name="Carga staging (datos sintéticos)"))
    staff = db.query(StaffUser).filter_by(username=USERNAME).first()
    if staff:
        staff.password_hash = hash_password(derived_password())
    else:
        staff = StaffUser(username=USERNAME, password_hash=hash_password(derived_password()), role="digitador", full_name="Carga (sintético)", is_active=True, phone="+573000000000")
        db.add(staff)
    db.flush()
    ev = db.query(Event).filter_by(event_code=EVENT_CODE).first()
    if not ev:
        ev = Event(tenant_id=TENANT, event_code=EVENT_CODE, name="Evento de carga (staging)", status="en_proceso", facial_enabled=True, auto_register=False,
                   start_date=date.today(), end_date=date.today() + timedelta(days=30), coordinator_staff_id=staff.id, created_by_id=staff.id)
        db.add(ev)
        db.flush()
    if not db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=staff.id).first():
        db.add(EventStaffAuthorization(event_id=ev.id, staff_user_id=staff.id))
    have = db.query(User).filter(User.tenant_id == TENANT).count()
    rng = np.random.default_rng(42)
    now = utcnow()
    rows_u, rows_a = [], []
    for i in range(have, max(have, people)):
        uid = f"9{i:09d}"
        rows_u.append({"id": uid, "tenant_id": TENANT, "first_name": "Persona", "last_name": uid[-5:], "entity": "Sintética", "face_encoding": json.dumps(rng.normal(0, 0.1, 128).round(6).tolist())})
        rows_a.append({"event_id": ev.id, "user_id": uid, "tenant_id": TENANT, "created_at": now})
    for i in range(0, len(rows_u), 1000):
        db.execute(insert(User), rows_u[i:i + 1000])
        db.execute(insert(EventAttendee), rows_a[i:i + 1000])
    form = db.query(WebForm).filter_by(event_id=ev.id, slug=FORM_SLUG).first()
    if not form:
        fields = {"cedula": {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True},
                  "nombres": {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
                  "apellidos": {"id": "apellidos", "type": "text_short", "label": "Apellidos", "key": "last_name", "required": True},
                  "correo": {"id": "correo", "type": "email", "label": "Correo", "key": "email", "required": True},
                  "tel": {"id": "tel", "type": "phone", "label": "Teléfono", "key": "phone"}}
        design = formlib.sanitize_design({"theme": {"title": "Formulario de carga"}, "rows": [{"align": "left", "items": ["cedula", "nombres", "apellidos"]}, {"align": "left", "items": ["correo", "tel"]}],
                                          "fields": fields}, set())
        form = WebForm(event_id=ev.id, name="Formulario de carga", slug=FORM_SLUG, manual_status="activo", design_json=json.dumps(design),
                       settings_json=json.dumps(formlib.sanitize_settings({"feed": "manual"})), capacity=capacity, test_key="cargastgkey00001")
        db.add(form)
    else:
        form.capacity = capacity
    db.commit()
    return {"event_id": ev.id, "form_slug": form.slug, "people": db.query(User).filter(User.tenant_id == TENANT).count(), "capacity": capacity}


def verify(db) -> dict:
    form = db.query(WebForm).filter_by(slug=FORM_SLUG).join(Event, Event.id == WebForm.event_id).filter(Event.event_code == EVENT_CODE).first()
    if not form:
        return {"error": "no hay formulario de carga"}
    confirmed = db.query(func.count(FormSubmission.id)).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed", FormSubmission.is_test.is_(False)).scalar()
    dup_persons = db.execute(text("SELECT count(*) FROM (SELECT person_id FROM form_submissions WHERE form_id = :f AND status = 'confirmed' AND person_id IS NOT NULL "
                                  "GROUP BY person_id HAVING count(*) > 1) t"), {"f": form.id}).scalar()
    dup_sid = db.execute(text("SELECT count(*) FROM (SELECT sid FROM form_submissions WHERE form_id = :f AND status = 'confirmed' AND sid IS NOT NULL "
                              "GROUP BY sid HAVING count(*) > 1) t"), {"f": form.id}).scalar()
    ev = db.get(Event, form.event_id)
    logs = db.query(func.count(AccessLog.id)).filter(AccessLog.event_id == ev.id).scalar()
    return {"event_id": ev.id, "form_slug": form.slug, "capacity": form.capacity, "confirmed_submissions": confirmed, "oversold": max(0, confirmed - (form.capacity or confirmed)),
            "duplicate_persons": dup_persons, "duplicate_sids": dup_sid, "access_logs_in_event": logs}


def _load_event(db):
    return db.query(Event).filter_by(event_code=EVENT_CODE, tenant_id=TENANT).first()


def reset_runs(db) -> dict:
    """Vuelve a cero lo que dejó una corrida (inscripciones, ingresos, límites por IP) SIN tocar el evento, el formulario ni las personas: para repetir la prueba desde
    cero (p. ej. tras el modo pequeño). Solo cifras."""
    ev = _load_event(db)
    if not ev:
        return {"error": "no hay evento de carga"}
    form_ids = [f.id for f in db.query(WebForm).filter_by(event_id=ev.id)]
    out = {}
    if form_ids:
        out["form_submissions"] = db.query(FormSubmission).filter(FormSubmission.form_id.in_(form_ids)).delete(synchronize_session=False)
    out["access_logs"] = db.query(AccessLog).filter(AccessLog.event_id == ev.id).delete(synchronize_session=False)
    out["rate_limit_events"] = db.execute(text("DELETE FROM rate_limit_events WHERE key = :u"), {"u": USERNAME}).rowcount
    db.commit()
    return out


def delete_all(db) -> dict:
    """Borra TODO lo de la prueba de carga: el evento LOAD-STG con sus filas dependientes (cualquier tabla con `event_id` o `form_id`), el formulario, las personas
    sintéticas del cliente `carga-staging`, la cuenta `carga_dig` y el cliente. Nada más (todo se busca por el evento y el cliente de la prueba)."""
    from app.models import Base
    ev = _load_event(db)
    counts = {}
    if ev:
        form_ids = [f.id for f in db.query(WebForm).filter_by(event_id=ev.id)]
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in ("events", "web_forms", "users", "tenants", "staff_users"):
                continue
            conds = []
            if "form_id" in table.c and form_ids:
                conds.append(table.c.form_id.in_(form_ids))
            if "event_id" in table.c:
                conds.append(table.c.event_id == ev.id)
            for cond in conds:
                n = db.execute(table.delete().where(cond)).rowcount
                if n:
                    counts[table.name] = counts.get(table.name, 0) + n
        db.execute(text("DELETE FROM web_forms WHERE event_id = :e"), {"e": ev.id})
        db.execute(text("DELETE FROM events WHERE id = :e"), {"e": ev.id})
    counts["users"] = db.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": TENANT}).rowcount
    counts["staff_users"] = db.execute(text("DELETE FROM staff_users WHERE username = :u"), {"u": USERNAME}).rowcount
    db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": TENANT})
    db.commit()
    return counts


def main() -> None:
    guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", type=int, default=5000)
    ap.add_argument("--capacity", type=int, default=4000)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--reset-runs", action="store_true", help="borra inscripciones, ingresos y límites de una corrida; deja evento, formulario y personas")
    ap.add_argument("--delete-all", action="store_true", help="borra TODO lo de la prueba (evento LOAD-STG, formulario, personas sintéticas, cuenta carga_dig, cliente)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.verify:
            print("LOAD_VERIFY " + json.dumps(verify(db)))
        elif args.reset_runs:
            print("LOAD_RESET " + json.dumps(reset_runs(db)))
        elif args.delete_all:
            print("LOAD_DELETED " + json.dumps(delete_all(db)))
        else:
            print("LOAD_SEED " + json.dumps(seed(db, args.people, args.capacity)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
