"""Pruebas automáticas (Sprint 4). Corren contra una base de datos de PRUEBAS separada (nunca la de desarrollo):
`TEST_DATABASE_URL`, o por defecto la misma instancia de `DATABASE_URL` pero con base `golden_test`. Se aplican
las migraciones reales de Alembic (así cada corrida también prueba que las migraciones suben limpias).

El motor biométrico (dlib/face_recognition) se reemplaza por un doble: las pruebas no necesitan el modelo real ni
fotos, y así también corren en CI sin compilar dlib."""
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock
from urllib.parse import urlsplit, urlunsplit

import pytest

# --- 1) base de pruebas: se decide ANTES de importar la app (app/database.py lee DATABASE_URL al importarse) ---
from dotenv import load_dotenv

load_dotenv()
_dev_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/golden_db")
_parts = urlsplit(_dev_url)
TEST_URL = os.getenv("TEST_DATABASE_URL") or urlunsplit(_parts._replace(path="/golden_test"))
TEST_DB_NAME = urlsplit(TEST_URL).path.lstrip("/")
assert "test" in TEST_DB_NAME, f"Por seguridad las pruebas solo corren contra una base con 'test' en el nombre (es '{TEST_DB_NAME}')"
os.environ["DATABASE_URL"] = TEST_URL
os.environ.pop("ENVIRONMENT", None)          # las pruebas corren como desarrollo
os.environ.pop("PUBLIC_BASE_URL", None)
for _k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "GRAPH_SENDER", "SMTP_HOST"):
    os.environ.pop(_k, None)                 # nunca enviar correo real desde una prueba

# --- 2) doble del motor biométrico ---
if "face_recognition" not in sys.modules or os.getenv("FORCE_FACE_STUB", "1") == "1":
    stub = ModuleType("face_recognition")
    stub.face_encodings = MagicMock(return_value=[])
    stub.face_distance = MagicMock(return_value=[0.0])
    stub.load_image_file = MagicMock()
    sys.modules["face_recognition"] = stub


def _ensure_database():
    import psycopg2

    admin = urlunsplit(urlsplit(TEST_URL)._replace(path="/postgres"))
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def _database():
    _ensure_database()
    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.downgrade(cfg, "base")   # arranca siempre de cero
    command.upgrade(cfg, "head")
    yield


def _wipe_test_files():
    """Las pruebas escriben archivos (fotos, logos...) en data/<cliente>/ con clientes de mentira; se borran para que
    un archivo que quedó de una prueba no contamine la siguiente (bug real: una foto vieja rompía la carga masiva)."""
    import shutil
    for tenant in ("acme", "otro"):
        shutil.rmtree(os.path.join("data", tenant), ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_tables(_database):
    """Vacía todas las tablas de datos antes de cada prueba (no toca alembic_version)."""
    from sqlalchemy import text
    from app.database import engine
    from app.models import Base

    import threading
    for t in threading.enumerate():          # una carga en segundo plano de la prueba anterior no puede seguir tocando la base
        if t.name.startswith("bulk-"):
            t.join(timeout=60)
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    _wipe_test_files()
    yield
    _wipe_test_files()


@pytest.fixture()
def db():
    from app.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def outbox(monkeypatch):
    """Correos que la app intentó enviar (no sale nada al exterior)."""
    sent = []

    def fake_send_mail(to, subject, body, attachments=None):
        sent.append({"to": to, "subject": subject, "body": body})
        return {"sent": True, "detail": "prueba"}

    monkeypatch.setattr("app.routers.auth.send_mail", fake_send_mail)
    monkeypatch.setattr("app.routers.event_report.send_mail", fake_send_mail)
    monkeypatch.setattr("app.digital_badge.send_mail", fake_send_mail)
    return sent


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, follow_redirects=False) as c:
        yield c


# ------------------------------- fábricas -------------------------------
PASSWORD = "Prueba#2026"


@pytest.fixture()
def factory(db):
    from app.auth import hash_password
    from app.models import Event, EventStaffAuthorization, StaffUser, Tenant, User

    class F:
        counter = 0

        def tenant(self, tenant_id="acme"):
            t = db.query(Tenant).filter_by(id=tenant_id).first()
            if not t:
                t = Tenant(id=tenant_id, client_code=f"C{tenant_id}", name=tenant_id.upper())
                db.add(t)
                db.commit()
            return t

        def staff(self, role, username=None, password=PASSWORD, email=None, tenant_id=None, phone=None, **extra):
            self.counter += 1
            s = StaffUser(
                username=username or f"{role}{self.counter}", password_hash=hash_password(password), role=role,
                full_name=f"{role} {self.counter}", email=email, tenant_id=tenant_id,
                phone=phone or f"+57300000{self.counter:04d}", **extra,
            )
            db.add(s)
            db.commit()
            return s

        def event(self, status="en_proceso", tenant_id="acme", coordinator=None, commercial=None, **extra):
            self.tenant(tenant_id)
            self.counter += 1
            e = Event(
                tenant_id=tenant_id, event_code=f"EV{self.counter}", name=f"Evento {self.counter}", status=status,
                coordinator_staff_id=coordinator.id if coordinator else None,
                commercial_staff_id=commercial.id if commercial else None, **extra,
            )
            db.add(e)
            db.commit()
            return e

        def authorize(self, event, staff):
            db.add(EventStaffAuthorization(event_id=event.id, staff_user_id=staff.id))
            db.commit()

        def person(self, event, user_id="1001", first_name="Ana", last_name="Prueba", attend=True):
            from app.models import EventAttendee

            u = db.query(User).filter_by(id=user_id, tenant_id=event.tenant_id).first()
            if not u:
                u = User(id=user_id, tenant_id=event.tenant_id, first_name=first_name, last_name=last_name)
                db.add(u)
                db.commit()
            if attend:
                db.add(EventAttendee(event_id=event.id, user_id=u.id, tenant_id=event.tenant_id))
                db.commit()
            return u

    return F()


def login(client, username, password=PASSWORD):
    return client.post("/login", data={"username": username, "password": password})
