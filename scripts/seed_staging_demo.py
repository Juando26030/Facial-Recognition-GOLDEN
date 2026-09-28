"""Evento de prueba con personas 100 % sintéticas en la base de STAGING, para revisar a mano el Directorio (paginación y cambios cada 15 s).

Dentro del contenedor (lee .env.staging):
    docker compose -f deploy/docker-compose.yml run --rm -v <carpeta fuera del repo>:/out web python scripts/seed_staging_demo.py --people 3000
    docker compose -f deploy/docker-compose.yml run --rm web python scripts/seed_staging_demo.py --simulate 120 --every 5   # acredita de a una

La contraseña (aleatoria) de la cuenta `revisor.staging` queda SOLO en el archivo de --password-file, nunca en la salida.

Se niega a correr si DATABASE_URL no apunta a Neon (host *.neon.tech) O si DEPLOY_ENV no es «staging»: producción también vivirá en
Neon, así que el host solo no basta. En Cloud Run: `gcloud run jobs execute golden-tools-staging --region <región> --args=scripts/seed_staging_demo.py,--people,3000`."""
import argparse
import os
import random
import secrets
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
host = (urlsplit(os.environ.get("DATABASE_URL", "")).hostname or "")
if not host.endswith(".neon.tech") or os.environ.get("DEPLOY_ENV") != "staging":
    sys.exit(f"Solo para la base de staging en Neon con DEPLOY_ENV=staging (host={host!r}, DEPLOY_ENV={os.environ.get('DEPLOY_ENV')!r}).")

from app.auth import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AccessLog, Event, EventAttendee, StaffUser, Tenant, User  # noqa: E402

TENANT, EVENT_CODE, USERNAME = "demo-staging", "DEMO-STG-3000", "revisor.staging"
NAMES = "Ana Beto Carla Diego Elena Felipe Gloria Hugo Irene Jorge Karen Luis María Nicolás Olga Pablo Quintina Raúl Sofía Tomás Úrsula Valeria Wilson Ximena Yolanda Zoe".split()
SURNAMES = "Gómez Pérez Rodríguez López Martínez Sánchez Ramírez Torres Flores Rivera Vargas Castro Ortiz Morales Jiménez Rojas Herrera Medina Aguilar Núñez".split()
ENTITIES = [f"Empresa {c}" for c in "ABCDEFGHIJKLMNO"]
TYPES = ["Asistente", "Expositor", "Prensa", "Staff", "VIP"]


def seed(db, people: int, password_file: str) -> None:
    if db.query(Event).filter_by(event_code=EVENT_CODE).first():
        sys.exit("El evento de prueba ya existe (no se duplica).")
    if not db.get(Tenant, TENANT):
        db.add(Tenant(id=TENANT, client_code=secrets.token_hex(4).upper(), name="Demo Staging (datos sintéticos)"))
    staff = db.query(StaffUser).filter_by(username=USERNAME).first()
    password = secrets.token_urlsafe(12)
    if staff:
        staff.password_hash = hash_password(password)
    else:
        staff = StaffUser(username=USERNAME, password_hash=hash_password(password), full_name="Revisor staging", role="super_admin", is_active=True)
        db.add(staff)
    db.flush()
    today = date.today()
    ev = Event(tenant_id=TENANT, event_code=EVENT_CODE, name="Directorio 3.000 (prueba)", status="en_proceso", location="Virtual",
               address="-", country="Colombia", city="Bogotá", start_date=today, end_date=today + timedelta(days=1), setup_date=today,
               event_time_start="08:00", event_time_end="18:00", setup_time_start="06:00", setup_time_end="07:30",
               coordinator_staff_id=staff.id, created_by_id=staff.id, roster_uploaded=True)
    db.add(ev)
    db.flush()
    rnd = random.Random(2026)
    now = datetime.utcnow()
    users, attendees, logs = [], [], []
    for i in range(people):
        cid = str(1_000_000_000 + i)
        first, last = rnd.choice(NAMES), f"{rnd.choice(SURNAMES)} {rnd.choice(SURNAMES)}"
        users.append(dict(id=cid, tenant_id=TENANT, first_name=first, last_name=last, entity=rnd.choice(ENTITIES), role="Cargo de prueba",
                          phone=f"300{i:07d}", email=f"persona{i}@ejemplo.test", opt_1=rnd.choice(TYPES)))
        attendees.append(dict(event_id=ev.id, user_id=cid, tenant_id=TENANT, created_at=now))
        if rnd.random() < 0.35:
            logs.append(dict(tenant_id=TENANT, user_id=cid, event_id=ev.id, record_type="Existente", registration_method="tradicional",
                             timestamp=now - timedelta(minutes=rnd.randint(1, 240)), registered_by_staff_id=staff.id))
    db.bulk_insert_mappings(User, users)
    db.bulk_insert_mappings(EventAttendee, attendees)
    db.bulk_insert_mappings(AccessLog, logs)
    db.commit()
    with open(password_file, "w", encoding="utf8") as fh:
        fh.write(f"Usuario: {USERNAME}\nContraseña: {password}\nEvento id: {ev.id}\n")
    print(f"listo: evento {ev.id}, {people} personas, {len(logs)} ya registradas; credenciales en {password_file}")


def simulate(db, n: int, every: float) -> None:
    ev = db.query(Event).filter_by(event_code=EVENT_CODE).one()
    staff = db.query(StaffUser).filter_by(username=USERNAME).one()
    done = {r[0] for r in db.query(AccessLog.user_id).filter(AccessLog.event_id == ev.id)}
    pending = [r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == ev.id) if r[0] not in done]
    random.shuffle(pending)
    for i, cid in enumerate(pending[:n], 1):
        db.add(AccessLog(tenant_id=TENANT, user_id=cid, event_id=ev.id, record_type="Existente", registration_method="tradicional",
                         timestamp=datetime.utcnow(), registered_by_staff_id=staff.id))
        db.commit()
        print(f"{i}/{n} acreditada {cid}", flush=True)
        time.sleep(every)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", type=int, default=3000)
    ap.add_argument("--password-file", default="/out/usuario_staging.txt")
    ap.add_argument("--simulate", type=int, default=0)
    ap.add_argument("--every", type=float, default=5)
    a = ap.parse_args()
    session = SessionLocal()
    try:
        simulate(session, a.simulate, a.every) if a.simulate else seed(session, a.people, a.password_file)
    finally:
        session.close()
