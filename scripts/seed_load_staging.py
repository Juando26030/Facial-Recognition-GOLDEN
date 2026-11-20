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


def guard(production_ok: str = "", allow_live: bool = False) -> None:
    """Solo la base de STAGING en Neon (se llama al ejecutar el script; las pruebas usan las funciones directamente sobre su base de pruebas).

    PRODUCCIÓN (19-nov-2026, orden expresa de Juan David: probar 40.000 escaneos en un evento sintético y borrarlo después) solo si se cumplen TODAS: DEPLOY_ENV=production,
    el Job es el `golden-ops` de producción (Cloud Run pone CLOUD_RUN_JOB) y `--production-ok <proyecto>` lo pone run_phase4.sh después de que la persona escribió el ID del proyecto."""
    host = (urlsplit(os.environ.get("DATABASE_URL", "")).hostname or "")
    env = os.environ.get("DEPLOY_ENV")
    if not host.endswith(".neon.tech"):
        sys.exit(f"Solo para una base en Neon (host={host!r}).")
    if env == "staging":
        return
    if env == "production" and production_ok and os.environ.get("CLOUD_RUN_JOB") == "golden-ops":
        print(f"AVISO: PRODUCCIÓN (proyecto {production_ok}). Solo toca el cliente y el evento sintéticos de la prueba de carga.", flush=True)
        return
    sys.exit(f"Solo para staging con DEPLOY_ENV=staging (o producción con la confirmación de run_phase4.sh): host={host!r}, DEPLOY_ENV={env!r}.")


def refuse_if_live_events(db, allow_live: bool) -> None:
    """En producción NO se siembra ni se reinicia mientras haya un evento REAL en proceso: la prueba compite por CPU y base con la puerta de un evento de verdad.
    `--allow-live-events` (LOAD_ALLOW_LIVE=1 en run_phase4.sh) lo salta, a propósito y sabiendo qué evento hay."""
    if os.environ.get("DEPLOY_ENV") != "production" or allow_live:
        return
    live = db.execute(text("SELECT count(*) FROM events WHERE status = 'en_proceso' AND event_code <> :c"), {"c": EVENT_CODE}).scalar()
    if live:
        sys.exit(f"HAY {live} EVENTO(S) REAL(ES) EN PROCESO en producción: no se siembra. Espera a que no haya ninguno (o, sabiéndolo, LOAD_ALLOW_LIVE=1).")


from sqlalchemy import func, insert, text  # noqa: E402

from app import formlib  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AccessLog, Event, EventAttendee, EventStaffAuthorization, FormSubmission, StaffUser, Tenant, User, WebForm  # noqa: E402
from app.timeutil import utcnow  # noqa: E402
from scripts.load_cfg import EVENT_CODE, FORM_SLUG, PAY_FORM_SLUG, TENANT, USERNAME, derived_password  # noqa: E402

# Cliente donde vive la prueba. Por defecto el sintético `carga-staging` (se crea y se borra entero). Con `--tenant <id>` (LOAD_TENANT en run_phase4.sh) la prueba vive en un cliente
# YA EXISTENTE (p. ej. el cliente «prueba» de producción): no se crea y NUNCA se borra, y el borrado solo quita lo sintético (evento LOAD-STG, personas «Sintética» con cédula 9xxxxxxxxx, cuenta de carga).
ACTIVE = {"tenant": TENANT}


def custom_tenant() -> bool:
    return ACTIVE["tenant"] != TENANT


def synthetic_users(db):
    """Personas SINTÉTICAS del cliente activo: nombre «Persona», entidad «Sintética» y cédula de 10 dígitos que empieza por 9 (las que crea `seed`). En el cliente sintético son todas las del cliente."""
    q = db.query(User).filter(User.tenant_id == ACTIVE["tenant"])
    if custom_tenant():
        q = q.filter(User.first_name == "Persona", User.entity == "Sintética", User.id.op("~")("^9[0-9]{9}$"))
    return q


def payment_form_design() -> dict:
    """Diseño del formulario de pago de la prueba: los mismos campos y UN campo «Pago» fijo de $50.000. Solo se cotiza (`quote`): en staging no hay llaves de Wompi y un envío con cobro daría 503."""
    fields = {"cedula": {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True},
              "nombres": {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
              "pago": {"id": "pago", "type": "payment", "label": "Pago de inscripción", "pay": {"mode": "fixed", "amount": 50000}}}
    return formlib.sanitize_design({"theme": {"title": "Formulario de carga con pago"}, "rows": [{"align": "left", "items": ["cedula", "nombres"]}, {"align": "left", "items": ["pago"]}],
                                    "fields": fields}, set())


def ensure_payment_form(db, ev) -> WebForm:
    form = db.query(WebForm).filter_by(event_id=ev.id, slug=PAY_FORM_SLUG).first()
    if not form:
        form = WebForm(event_id=ev.id, name="Formulario de carga con pago", slug=PAY_FORM_SLUG, manual_status="activo", design_json=json.dumps(payment_form_design()),
                       settings_json=json.dumps(formlib.sanitize_settings({"feed": "manual"})), test_key="cargapagokey0001")
        db.add(form)
    return form


def seed(db, people: int, capacity: int) -> dict:
    import numpy as np
    if custom_tenant():
        if not db.get(Tenant, ACTIVE["tenant"]):
            sys.exit(f"El cliente {ACTIVE['tenant']!r} no existe: no se crea (usa `--info` para ver los ids).")
    elif not db.get(Tenant, TENANT):
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
        ev = Event(tenant_id=ACTIVE["tenant"], event_code=EVENT_CODE, name="Evento de carga (staging)", status="en_proceso", facial_enabled=True, auto_register=False,
                   start_date=date.today(), end_date=date.today() + timedelta(days=30), coordinator_staff_id=staff.id, created_by_id=staff.id)
        db.add(ev)
        db.flush()
    # Re-sembrar deja la cuenta y el evento listos aunque una corrida anterior los dejara mal: sin desbloqueo, sin fallos acumulados, evento «en proceso» (el digitador
    # solo entra con un evento en proceso asignado) y sin los intentos de login anotados (rate_limit_events), que bloquean al par usuario+IP por 15 minutos.
    staff.is_active = True
    staff.locked_at = None
    staff.failed_logins = 0
    ev.status = "en_proceso"
    ev.state_id = None            # sin estado configurable: manda el estado base «en proceso» (un estado viejo como «Finalizado» deja registration=False aunque status diga en_proceso)
    ev.archived_at = None          # un evento archivado queda de solo lectura (event_rules.ARCHIVED_OFF)
    ev.data_archived_at = None
    ev.finalized_at = None
    db.execute(text("DELETE FROM rate_limit_events WHERE key = :u AND kind IN ('login_fail', 'login_ok')"), {"u": USERNAME})
    if not db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=staff.id).first():
        db.add(EventStaffAuthorization(event_id=ev.id, staff_user_id=staff.id))
    have = synthetic_users(db).count()
    rng = np.random.default_rng(42)
    now = utcnow()
    rows_u, rows_a = [], []
    for i in range(have, max(have, people)):
        uid = f"9{i:09d}"
        rows_u.append({"id": uid, "tenant_id": ACTIVE["tenant"], "first_name": "Persona", "last_name": uid[-5:], "entity": "Sintética", "face_encoding": json.dumps(rng.normal(0, 0.1, 128).round(6).tolist())})
        rows_a.append({"event_id": ev.id, "user_id": uid, "tenant_id": ACTIVE["tenant"], "created_at": now})
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
    ensure_payment_form(db, ev)
    db.commit()
    return {"event_id": ev.id, "form_slug": form.slug, "pay_form_slug": PAY_FORM_SLUG, "people": synthetic_users(db).count(), "capacity": capacity}


def info(db) -> dict:
    """SOLO LECTURA (producción): los clientes cuyo nombre contiene «prueba» y los eventos REALES en proceso (id, cliente, fechas e ingresos de la última hora). Sin datos de personas."""
    tenants = [{"id": r[0], "client_code": r[1], "name": r[2], "archived": r[3] is not None}
               for r in db.execute(text("SELECT id, client_code, name, archived_at FROM tenants WHERE name ILIKE :p ORDER BY name"), {"p": "%prueba%"})]
    since = utcnow() - timedelta(hours=1)
    live = [{"id": r[0], "tenant_id": r[1], "start": str(r[2]), "end": str(r[3]), "accesses_last_hour": r[4]}
            for r in db.execute(text("SELECT e.id, e.tenant_id, e.start_date, e.end_date, "
                                     "(SELECT count(*) FROM access_logs a WHERE a.event_id = e.id AND a.timestamp >= :s) "
                                     "FROM events e WHERE e.status = 'en_proceso' AND e.event_code <> :c ORDER BY e.id"), {"s": since, "c": EVENT_CODE})]
    return {"tenants_named_prueba": tenants, "live_events": live}


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
    return db.query(Event).filter_by(event_code=EVENT_CODE, tenant_id=ACTIVE["tenant"]).first()


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
            if table.name.startswith("audit_"):   # registros inmutables (solo INSERT; el rol de la app no puede borrarlos): no se tocan; si el evento tiene filas ahí, se detiene sin borrar nada
                if "event_id" in table.c:
                    n = db.execute(text(f'SELECT count(*) FROM "{table.name}" WHERE event_id = :e'), {"e": ev.id}).scalar()
                    if n:
                        db.rollback()
                        sys.exit(f"El evento de carga tiene {n} fila(s) en {table.name} (inmutable): no se borra nada.")
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
    if custom_tenant():          # cliente existente: SOLO lo sintético; el cliente y todo lo demás de él se quedan
        counts["users"] = db.execute(text("DELETE FROM users WHERE tenant_id = :t AND first_name = 'Persona' AND entity = 'Sintética' AND id ~ '^9[0-9]{9}$'"), {"t": ACTIVE["tenant"]}).rowcount
    else:
        counts["users"] = db.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": TENANT}).rowcount
    counts["staff_users"] = db.execute(text("DELETE FROM staff_users WHERE username = :u"), {"u": USERNAME}).rowcount
    if not custom_tenant():
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": TENANT})
    db.commit()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", type=int, default=5000)
    ap.add_argument("--capacity", type=int, default=4000)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--reset-runs", action="store_true", help="borra inscripciones, ingresos y límites de una corrida; deja evento, formulario y personas")
    ap.add_argument("--delete-all", action="store_true", help="borra TODO lo de la prueba (evento LOAD-STG, formulario, personas sintéticas, cuenta carga_dig, cliente)")
    ap.add_argument("--production-ok", default="", help="solo producción: el ID del proyecto, que run_phase4.sh pone tras la confirmación escrita")
    ap.add_argument("--info", action="store_true", help="solo lectura: clientes llamados «prueba» y eventos reales en proceso")
    ap.add_argument("--tenant", default="", help="id de un cliente EXISTENTE donde vive la prueba (por defecto el sintético carga-staging)")
    ap.add_argument("--allow-live-events", action="store_true", help="solo producción: sembrar aunque haya un evento real en proceso (a propósito)")
    args = ap.parse_args()
    guard(args.production_ok, args.allow_live_events)
    if args.tenant:
        ACTIVE["tenant"] = args.tenant
    db = SessionLocal()
    try:
        if not (args.verify or args.delete_all or args.info):
            refuse_if_live_events(db, args.allow_live_events)
        if args.info:
            print("LOAD_INFO " + json.dumps(info(db)))
        elif args.verify:
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
