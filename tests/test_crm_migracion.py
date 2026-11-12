"""CRM C1a: la migración 0130 sube limpia, deja los contadores como deben y su REVERSA restaura el código hexadecimal. Necesita PostgreSQL.
Sube y baja sobre la base de pruebas y SIEMPRE la deja en `head` al terminar."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text


def _cfg():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    return cfg


CRM_TABLES = {"crm_counters", "crm_accounts", "crm_contacts", "crm_notes", "crm_change_log"}


def test_upgrade_creates_the_crm_tables_seeds_the_counters_not_ready_and_leaves_client_codes_alone(db, factory):
    from app.database import engine
    insp = inspect(engine)
    assert CRM_TABLES <= set(insp.get_table_names())
    assert "legacy_client_code" in {c["name"] for c in insp.get_columns("tenants")}
    # lo que la migración sembró se vació con _clean_tables: se comprueba rehaciendo la subida
    db.close()
    command.downgrade(_cfg(), "0129_staff_client_temp")
    try:
        assert not (CRM_TABLES & set(inspect(engine).get_table_names()))
    finally:
        command.upgrade(_cfg(), "head")
    with engine.connect() as c:
        rows = {r[0]: (r[1], r[2]) for r in c.execute(text("SELECT name, value, ready FROM crm_counters"))}
        assert rows == {"account": (0, False), "event": (0, False)}
        assert c.execute(text("SELECT count(*) FROM tenants WHERE legacy_client_code IS NOT NULL")).scalar() == 0


def test_downgrade_restores_the_hex_code_of_clients_that_moved_to_a_number_and_upgrade_works_again(db, factory):
    from app.database import engine
    from app.models import Tenant
    factory.tenant("acme")
    t = db.query(Tenant).filter_by(id="acme").one()
    hex_code = t.client_code
    t.legacy_client_code, t.client_code = hex_code, "21500"
    db.commit()
    db.close()
    command.downgrade(_cfg(), "0129_staff_client_temp")
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT client_code FROM tenants WHERE id = 'acme'")).scalar() == hex_code
            assert "legacy_client_code" not in {col["name"] for col in inspect(engine).get_columns("tenants")}
    finally:
        command.upgrade(_cfg(), "head")
    with engine.connect() as c:
        assert c.execute(text("SELECT client_code, legacy_client_code FROM tenants WHERE id = 'acme'")).one() == (hex_code, None)
    assert CRM_TABLES <= set(inspect(engine).get_table_names())
