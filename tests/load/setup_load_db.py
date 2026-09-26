"""Crea y llena la base LOCAL de pruebas de carga (`golden_load`) con datos 100 % sintéticos: nadie real, ningún encoding real.

    python tests/load/setup_load_db.py                 # 8.000 personas, evento con auto-registro, formulario abierto
    python tests/load/setup_load_db.py --people 2000

SEGURIDAD: se niega a correr si el servidor de base de datos no es local o si el nombre de la base no contiene «load». Nunca apuntes esto a producción.
Deja escrito `tests/load/.load_env.json` (gitignored) con los ids/usuarios que usa el locustfile.
"""
import argparse
import json
import os
import random
import string
import subprocess
import sys
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

PASSWORD = os.getenv("LOAD_PASSWORD", "Carga#2026x")
DB_NAME = os.getenv("LOAD_DB_NAME", "golden_load")


def load_url() -> str:
    base = os.getenv("LOAD_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    parts = urlsplit(base)
    url = urlunsplit(parts._replace(path="/" + DB_NAME))
    host = (urlsplit(url).hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        sys.exit(f"Por seguridad las pruebas de carga solo corren contra una base LOCAL (host={host!r}).")
    if "load" not in DB_NAME:
        sys.exit("Por seguridad el nombre de la base de pruebas de carga debe contener «load».")
    return url


def ensure_db(url: str) -> None:
    import psycopg2
    admin = urlunsplit(urlsplit(url)._replace(path="/postgres"))
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB_NAME,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", type=int, default=8000)
    ap.add_argument("--reset", action="store_true", help="vacía la base de carga antes de llenarla")
    args = ap.parse_args()

    url = load_url()
    ensure_db(url)
    os.environ["DATABASE_URL"] = url
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, env={**os.environ, "DATABASE_URL": url})

    import numpy as np
    from sqlalchemy import insert, text

    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import AccessLog, Event, EventAttendee, StaffUser, Tenant, User, WebForm

    db = SessionLocal()
    if args.reset:
        db.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in [t.name for t in __import__("app.models", fromlist=["Base"]).Base.metadata.sorted_tables if t.name != "alembic_version"]) + " RESTART IDENTITY CASCADE"))
        db.commit()

    tenant_id = "carga"
    if not db.query(Tenant).filter_by(id=tenant_id).first():
        db.add(Tenant(id=tenant_id, client_code="CARGA", name="Cliente de carga (sintético)"))
    pw = hash_password(PASSWORD)
    for username, role in (("carga_admin", "coordinador"), ("carga_dig", "digitador")):
        if not db.query(StaffUser).filter_by(username=username).first():
            db.add(StaffUser(username=username, password_hash=pw, role=role, full_name=username, phone=f"+5730{random.randint(10000000, 99999999)}"))
    db.commit()

    ev = db.query(Event).filter_by(event_code="LOAD01").first()
    if not ev:
        coord = db.query(StaffUser).filter_by(username="carga_admin").first()
        ev = Event(tenant_id=tenant_id, event_code="LOAD01", name="Evento de carga", status="en_proceso", auto_register=True, facial_enabled=True,
                   start_date=date.today(), end_date=date.today() + timedelta(days=1), coordinator_staff_id=coord.id)
        db.add(ev)
        db.commit()
    dig = db.query(StaffUser).filter_by(username="carga_dig").first()
    from app.models import EventStaffAuthorization
    if not db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=dig.id).first():
        db.add(EventStaffAuthorization(event_id=ev.id, staff_user_id=dig.id))
        db.commit()

    have = db.query(User).filter(User.tenant_id == tenant_id).count()
    rng = np.random.default_rng(42)
    todo = max(0, args.people - have)
    ids = [f"9{i:09d}" for i in range(have, have + todo)]
    now = datetime.utcnow()
    users_rows, att_rows, enc_rows = [], [], []
    for uid in ids:
        vec = rng.normal(0, 0.1, 128)
        users_rows.append({"id": uid, "tenant_id": tenant_id, "first_name": "Persona", "last_name": uid[-5:], "entity": "Sintética", "face_encoding": json.dumps(vec.round(6).tolist())})
        att_rows.append({"event_id": ev.id, "user_id": uid, "tenant_id": tenant_id, "created_at": now})
    for i in range(0, len(users_rows), 2000):
        db.execute(insert(User), users_rows[i:i + 2000])
        db.execute(insert(EventAttendee), att_rows[i:i + 2000])
    db.commit()

    # una parte ya "registrada" (como en un evento en marcha) para que el directorio y los escaneos repetidos sean realistas
    if db.query(AccessLog).filter_by(event_id=ev.id).count() == 0:
        some = [u for u in [r["id"] for r in db.execute(text("SELECT user_id AS id FROM event_attendees WHERE event_id=:e LIMIT 2000"), {"e": ev.id}).mappings()]]
        db.execute(insert(AccessLog), [{"tenant_id": tenant_id, "user_id": u, "record_type": "Existente", "event_id": ev.id, "registration_method": "tradicional", "timestamp": now} for u in some])
        db.commit()

    form = db.query(WebForm).filter_by(event_id=ev.id, slug="carga").first()
    if not form:
        from app import formlib
        design = formlib.sanitize_design({"theme": {"title": "Formulario de carga"}, "rows": [{"align": "left", "items": ["cedula", "nombres", "apellidos"]}, {"align": "left", "items": ["correo", "tel"]}],
                                          "fields": {
                                              "cedula": {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True},
                                              "nombres": {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
                                              "apellidos": {"id": "apellidos", "type": "text_short", "label": "Apellidos", "key": "last_name", "required": True},
                                              "correo": {"id": "correo", "type": "email", "label": "Correo", "key": "email", "required": True},
                                              "tel": {"id": "tel", "type": "phone", "label": "Teléfono", "key": "phone"}}}, set())
        settings = formlib.sanitize_settings({"feed": "manual"})
        form = WebForm(event_id=ev.id, name="Formulario de carga", slug="carga", manual_status="activo", design_json=json.dumps(design), settings_json=json.dumps(settings),
                       capacity=None, test_key="cargatestkey0001")
        db.add(form)
        db.commit()

    info = {"database": DB_NAME, "event_id": ev.id, "form_slug": form.slug, "people": db.query(User).filter(User.tenant_id == tenant_id).count(),
            "digitador": "carga_dig", "coordinador": "carga_admin", "password": PASSWORD, "ids_prefix": "9", "id_first": ids[0] if ids else "900000000"}
    with open(os.path.join(os.path.dirname(__file__), ".load_env.json"), "w", encoding="utf8") as fh:
        json.dump(info, fh, indent=2)
    print(json.dumps({k: v for k, v in info.items() if k != "password"}, indent=2))
    print(f"Base de carga lista: {DB_NAME}. Arranca el servidor en otra terminal con DATABASE_URL apuntando a {DB_NAME} "
          f"(misma URL del .env cambiando el nombre de la base) y: uvicorn app.main:app --port 5002")


if __name__ == "__main__":
    main()
