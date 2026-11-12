"""CRM C1a: códigos consecutivos (app/crm/codes.py), interruptor CRM_ENABLED en la creación de clientes y aviso en /sistema. Necesitan PostgreSQL (docs/crm/STAGING_C1A.md, «Pruebas»)."""
import re
import threading

import pytest
from sqlalchemy import text

from app import models as m
from app import ops
from app.crm.codes import CodeCounterNotReady, bump_floor, counter_state, next_code
from tests.conftest import login
from tests.crm_helpers import seed_counters


def _account(db, code, name="Cuenta"):
    a = m.CrmAccount(code=code, name=name, name_norm=name.lower())
    db.add(a)
    db.commit()
    return a


def test_a_counter_that_is_not_ready_refuses_and_so_does_a_missing_one(db):
    seed_counters(db, ready=False)
    with pytest.raises(CodeCounterNotReady):
        next_code(db, "account")
    db.rollback()
    db.execute(text("DELETE FROM crm_counters"))
    db.commit()
    with pytest.raises(CodeCounterNotReady):
        next_code(db, "account")


def test_numbers_are_consecutive_and_start_after_the_floor(db):
    seed_counters(db, account=100)
    assert [next_code(db, "account") for _ in range(3)] == [101, 102, 103]
    db.commit()
    assert counter_state(db, "account") == {"exists": True, "value": 103, "ready": True}


def test_bump_floor_makes_it_ready_never_lowers_and_creates_a_missing_row(db):
    seed_counters(db, ready=False)
    assert bump_floor(db, "account", 100) == 100 and counter_state(db, "account")["ready"] is True
    assert bump_floor(db, "account", 50) == 100                                              # nunca baja
    db.execute(text("DELETE FROM crm_counters WHERE name = 'event'"))
    assert bump_floor(db, "event", 10) == 10 and counter_state(db, "event")["ready"] is True
    db.commit()
    with pytest.raises(ValueError):
        bump_floor(db, "otro", 1)
    with pytest.raises(ValueError):
        next_code(db, "otro")


def test_a_rollback_does_not_burn_a_number(db):
    seed_counters(db, account=100)
    first = next_code(db, "account")
    db.rollback()
    assert first == 101 and next_code(db, "account") == 101                                  # sin huecos


def test_it_skips_numbers_already_used_as_hex_code_legacy_alias_or_crm_account(db):
    seed_counters(db, account=103)
    db.add(m.Tenant(id="t104", client_code="104", name="Hex de solo dígitos"))
    db.add(m.Tenant(id="t105", client_code="AAAA1111", legacy_client_code="105", name="Con alias"))
    db.commit()
    _account(db, 106)
    assert next_code(db, "account") == 107


def test_a_hex_code_that_happens_to_be_all_digits_is_never_handed_out_again(db):
    seed_counters(db, account=12345676)
    db.add(m.Tenant(id="t8", client_code="12345678", name="Hex de 8 dígitos"))
    db.commit()
    assert next_code(db, "account") == 12345677 and next_code(db, "account") == 12345679


def test_event_counter_skips_numeric_event_codes_ignoring_spaces(db, factory):
    seed_counters(db, event=10)
    factory.tenant("acme")
    db.add(m.Event(tenant_id="acme", event_code=" 11 ", name="Evento con código numérico"))
    db.commit()
    assert next_code(db, "event") == 12


def test_concurrent_requests_get_distinct_consecutive_numbers(db):
    from app.database import SessionLocal
    seed_counters(db, account=1000)
    n, results, errors = 12, [], []
    barrier = threading.Barrier(n)

    def worker(i):
        s = SessionLocal()
        try:
            barrier.wait(timeout=30)
            code = next_code(s, "account")
            s.add(m.CrmAccount(code=code, name=f"c{i}", name_norm=f"c{i}"))
            s.commit()
            results.append(code)
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            errors.append(repr(exc))
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors and sorted(results) == list(range(1001, 1001 + n))


# ------------------------------------------------------------------------------------------------ interruptor CRM_ENABLED y crear cliente
def test_create_tenant_gives_the_next_consecutive_number_when_crm_is_enabled(client, db, factory, monkeypatch):
    monkeypatch.setenv("CRM_ENABLED", "1")
    seed_counters(db, account=21500)
    factory.staff("comercial", "com")
    login(client, "com")
    a = client.post("/api/tenants", json={"name": "Cliente Nuevo"})
    b = client.post("/api/tenants", json={"name": "Cliente Nuevo Dos"})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert (a.json()["client_code"], b.json()["client_code"]) == ("21501", "21502")


def test_create_tenant_is_refused_with_a_clear_message_when_enabled_without_a_ready_counter(client, db, factory, monkeypatch):
    monkeypatch.setenv("CRM_ENABLED", "1")
    seed_counters(db, ready=False)
    factory.staff("comercial", "com")
    login(client, "com")
    r = client.post("/api/tenants", json={"name": "Sin contador"})
    assert r.status_code == 409 and "contador" in r.json()["detail"]
    assert db.query(m.Tenant).count() == 0                                                   # no se crea nada a medias


def test_create_tenant_keeps_the_hex_code_when_crm_is_off_as_in_the_local_server(client, db, factory, monkeypatch):
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    seed_counters(db, account=21500)
    factory.staff("comercial", "com")
    login(client, "com")
    r = client.post("/api/tenants", json={"name": "Cliente Local"})
    assert r.status_code == 200 and re.fullmatch(r"[0-9A-F]{8}", r.json()["client_code"])
    assert counter_state(db, "account")["value"] == 21500                                    # el contador ni se tocó


# ------------------------------------------------------------------------------------------------ aviso en /sistema
def test_system_check_is_red_without_a_counter_and_green_with_one(db):
    seed_counters(db, ready=False)
    red = ops.check_crm(db)
    assert red["id"] == "crm" and red["level"] == "red" and "crm_set_counter.py" in red["action"]
    seed_counters(db, account=5)
    green = ops.check_crm(db)
    assert green["level"] == "green" and green["data"]["counter"] == 5


def test_system_status_shows_the_crm_item_only_when_crm_is_enabled(db, monkeypatch):
    seed_counters(db, ready=False)
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    assert "crm" not in {i["id"] for i in ops.system_status(db)["items"]}
    monkeypatch.setenv("CRM_ENABLED", "1")
    items = {i["id"]: i for i in ops.system_status(db)["items"]}
    assert items["crm"]["level"] == "red"
