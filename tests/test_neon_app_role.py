"""scripts/neon_app_role.py contra el ORDEN REAL de producción: el bootstrap crea el rol `golden_app` y verifica su conexión ANTES de la primera migración (base vacía).
Falló en el primer intento real (9-oct-2026): `check_app` leía `alembic_version`, que todavía no existe en una base recién creada."""
import os
import uuid
from urllib.parse import quote

import psycopg2
import pytest
from alembic import command
from alembic.config import Config

from app.database import engine
from scripts import neon_app_role

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "probe-pw-1"


def _dsn(db: str, user: str = None, password: str = None) -> str:
    u = engine.url
    return f"postgresql://{quote(user or u.username)}:{quote(password if password is not None else (u.password or ''), safe='')}@{u.host}:{u.port or 5432}/{db}"


@pytest.fixture()
def fresh():
    """Una base VACÍA y un rol de prueba con acceso mínimo (como golden_app antes de migrar); todo se borra al terminar."""
    suffix = uuid.uuid4().hex[:8]
    db, role = f"golden_probe_{suffix}", f"golden_probe_app_{suffix}"
    admin = psycopg2.connect(_dsn("postgres"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db}"')
        cur.execute(f"CREATE ROLE \"{role}\" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{PW}'")
    owner = psycopg2.connect(_dsn(db))
    owner.autocommit = True
    with owner.cursor() as cur:
        cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cur.execute(f'GRANT CONNECT ON DATABASE "{db}" TO "{role}"')
        cur.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
    try:
        yield type("F", (), {"db": db, "role": role, "owner": owner, "app_url": _dsn(db, role, PW), "owner_url": _dsn(db)})
    finally:
        owner.close()
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
            cur.execute(f'DROP ROLE IF EXISTS "{role}"')
        admin.close()


def test_check_app_accepts_a_brand_new_database_without_alembic_version(fresh):
    neon_app_role.check_app(fresh.app_url)                      # antes: UndefinedTable: relation "alembic_version" does not exist


def test_check_app_still_requires_reading_alembic_version_on_a_migrated_database(fresh):
    with fresh.owner.cursor() as cur:
        cur.execute("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)")
        cur.execute("INSERT INTO alembic_version VALUES ('0001')")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):    # existe y el rol no puede leerla: la comprobación NO se relaja
        neon_app_role.check_app(fresh.app_url)
    with fresh.owner.cursor() as cur:
        cur.execute(f'GRANT SELECT ON alembic_version TO "{fresh.role}"')
    neon_app_role.check_app(fresh.app_url)                      # con permiso de lectura pasa


def test_check_app_still_fails_if_the_app_role_could_create_tables(fresh):
    with fresh.owner.cursor() as cur:
        cur.execute(f'GRANT CREATE ON SCHEMA public TO "{fresh.role}"')
    with pytest.raises(SystemExit, match="pudo crear una tabla"):     # tanto en base vacía como en migrada
        neon_app_role.check_app(fresh.app_url)


def test_the_real_production_order_role_first_then_migrations_leaves_the_audit_table_insert_only(fresh, monkeypatch):
    """1) base vacía + rol de la app con sus permisos (lo que hace el bootstrap), 2) migraciones con el dueño, 3) la app NO puede modificar ni borrar la prueba legal."""
    with fresh.owner.cursor() as cur:
        cur.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN CREATE ROLE golden_app NOLOGIN; END IF; END $$")
    conn = psycopg2.connect(fresh.owner_url)
    try:
        neon_app_role.apply_grants(conn)                         # el rol se creó ANTES de que existiera ninguna tabla
    finally:
        conn.close()
    monkeypatch.setenv("DIRECT_DATABASE_URL", fresh.owner_url)
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")
    with fresh.owner.cursor() as cur:
        priv = lambda table, p: (cur.execute("SELECT has_table_privilege('golden_app', %s, %s)", (table, p)) or cur.fetchone()[0])
        assert priv("audit_consent_logs", "INSERT") and priv("audit_consent_logs", "SELECT")
        assert not (priv("audit_consent_logs", "UPDATE") or priv("audit_consent_logs", "DELETE") or priv("audit_consent_logs", "TRUNCATE"))      # lo quita la migración 0054
        assert priv("users", "UPDATE") and priv("event_attendees", "DELETE") and priv("person_changes", "INSERT")      # lo demás sí: privilegios por defecto del dueño
        assert priv("alembic_version", "SELECT")


def test_rerun_resets_the_role_password_and_stores_the_connection_as_the_first_version_of_the_secret(fresh, monkeypatch):
    """El reintento del bootstrap tras el fallo: el rol `golden_app` ya existe con una contraseña que nadie guardó; con --rotate se le pone una nueva y la cadena queda como versión del secreto."""
    import sys
    with fresh.owner.cursor() as cur:
        cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'golden_app'")
        row = cur.fetchone()
    if row and row[0]:
        pytest.skip("en este servidor ya existe un golden_app real con acceso: no se le cambia la contraseña desde una prueba")
    captured = []
    monkeypatch.setattr(neon_app_role, "gcloud_secret", lambda name: fresh.owner_url)
    monkeypatch.setattr(neon_app_role, "app_url", lambda owner, pw: _dsn(fresh.db, "golden_app", pw))        # en Neon sería el host del pooler
    monkeypatch.setattr(neon_app_role.subprocess, "run", lambda cmd, input=None, **kw: captured.append((cmd, input)))
    argv = ["neon_app_role.py", "--owner-secret", "golden-direct-database-url", "--app-secret", "golden-database-url", "--rotate"]
    try:
        for _ in range(2):                                           # la corrida que falló dejó el rol creado; esta es la repetición sobre la base TODAVÍA vacía
            monkeypatch.setattr(sys, "argv", argv)
            neon_app_role.main()
        assert [c[0] for c in captured] == [["gcloud", "secrets", "versions", "add", "golden-database-url", "--data-file=-"]] * 2
        first, second = captured[0][1], captured[1][1]
        assert first.startswith("postgresql://golden_app:") and second.startswith("postgresql://golden_app:") and first != second       # contraseña nueva cada vez
        psycopg2.connect(second).close()
        with pytest.raises((psycopg2.OperationalError, UnicodeDecodeError)):      # (en un Postgres en español el mensaje de «autenticación fallida» puede no decodificarse como UTF-8)
            psycopg2.connect(first)                                  # la contraseña anterior (la que nadie guardó) ya no sirve
    finally:
        with fresh.owner.cursor() as cur:
            cur.execute("ALTER ROLE golden_app NOLOGIN PASSWORD NULL")
