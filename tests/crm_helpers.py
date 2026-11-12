"""Ayudas de las pruebas del CRM. `_clean_tables` (conftest) vacía TODAS las tablas antes de cada prueba, también `crm_counters`: aquí se vuelven a sembrar como los deja la migración 0130."""
from sqlalchemy import text


def seed_counters(db, *, ready=True, account=0, event=0):
    db.execute(text("DELETE FROM crm_counters"))
    db.execute(text("INSERT INTO crm_counters (name, value, ready) VALUES ('account', :a, :r), ('event', :e, :r)"), {"a": account, "e": event, "r": ready})
    db.commit()


import pytest  # noqa: E402


@pytest.fixture()
def crm_on(monkeypatch, db):
    """CRM encendido con el contador listo en 1000 (la primera cuenta es la 1001). Se importa en cada archivo de pruebas: `from tests.crm_helpers import crm_on  # noqa: F401`."""
    monkeypatch.setenv("CRM_ENABLED", "1")
    seed_counters(db, ready=True, account=1000)


def staff_client(client, factory, role="comercial", username=None, **extra):
    from tests.conftest import login
    s = factory.staff(role, username or f"{role}_crm", **extra)
    login(client, s.username)
    return s


def new_account(client, name="Cámara de Comercio de Bogotá", **extra):
    r = client.post("/api/crm/accounts", json={"name": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def new_contact(client, account_id, first="Ana", last="Pérez", **extra):
    r = client.post(f"/api/crm/accounts/{account_id}/contacts", json={"first_name": first, "last_name": last, **extra})
    assert r.status_code == 200, r.text
    return r.json()
