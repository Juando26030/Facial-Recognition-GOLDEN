"""F5-9 revisión de seguridad C (dinero): docs/seguridad/F5-9_C_pagos.md. Llaves inventadas; Wompi real no se toca."""
import hashlib

import pytest
from cryptography.fernet import Fernet

from app import payment_accounts as pa
from app import wompi
from app.models import Event, EventState, FormPayment, PaymentAccount
from tests.conftest import login
from tests.test_cuentas_cobro import ACC
from tests.test_form_payments import PROD, SANDBOX
from tests.test_forms import _event, _submit
from tests.test_form_payments import _values, _with_payment

CFG = {"public_key": "pub_prod_GOLDEN0001", "private_key": "prv_prod_GOLDEN0001", "api": "https://production.wompi.co/v1", "test": False}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


# ------------------------------- C1: transacción de OTRO comercio (lógica pura) -------------------------------
def test_c1_belongs_compares_merchant_public_key():
    assert wompi.belongs(CFG, {"merchant": {"public_key": CFG["public_key"]}}, scoped=False)
    assert not wompi.belongs(CFG, {"merchant": {"public_key": "pub_prod_OTRO000001"}}, scoped=True)
    assert not wompi.belongs(CFG, {"id": "t"}, scoped=False)                 # sin comercio y sin consulta propia del comercio: no se cree
    assert wompi.belongs(CFG, {"id": "t"}, scoped=True)                      # listado con llave privada = del propio comercio
    assert not wompi.belongs({**CFG, "private_key": ""}, {"id": "t"}, scoped=True)


def test_c1_fetch_own_transaction_rejects_foreign_merchant(monkeypatch):
    foreign = {"id": "T1", "reference": "GW-1", "status": "APPROVED", "merchant": {"public_key": "pub_prod_ATACANTE01"}}
    monkeypatch.setattr(wompi, "fetch_transaction", lambda cfg, tid: foreign)
    assert wompi.fetch_own_transaction(CFG, "T1", "GW-1") is None


def test_c1_without_merchant_field_it_cross_checks_the_merchant_listing(monkeypatch):
    monkeypatch.setattr(wompi, "fetch_transaction", lambda cfg, tid: {"id": tid, "reference": "GW-1", "status": "APPROVED"})
    monkeypatch.setattr(wompi, "_rows_by_reference", lambda cfg, ref: [{"id": "T-MIO", "status": "APPROVED"}])
    assert wompi.fetch_own_transaction(CFG, "T-AJENO", "GW-1") is None          # el id no está entre las transacciones del comercio
    assert wompi.fetch_own_transaction(CFG, "T-MIO", "GW-1")["id"] == "T-MIO"
    assert wompi.fetch_own_transaction({**CFG, "private_key": ""}, "T-MIO", "GW-1") is None       # sin llave privada no hay cómo comprobarlo: lo resuelve el webhook


def test_c1_reconcile_listing_ignores_other_merchants(monkeypatch):
    rows = [{"id": "A", "status": "APPROVED", "merchant": {"public_key": "pub_prod_ATACANTE01"}}, {"id": "B", "status": "PENDING", "merchant": {"public_key": CFG["public_key"]}}]
    monkeypatch.setattr(wompi, "_rows_by_reference", lambda cfg, ref: rows)
    assert wompi.fetch_by_reference(CFG, "GW-1")["id"] == "B"


# ------------------------------- C4: llave de cifrado mal copiada -------------------------------
def test_c4_malformed_encryption_key_never_raises(monkeypatch):
    token = pa.encrypt("prod_events_ABCDEFGH12")
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", "no-es-una-llave-fernet")
    assert pa.enabled() is False and pa.decrypt(token) == ""
    with pytest.raises(pa.KeyMissing):
        pa.encrypt("x")


# ------------------------------- C2 / C3: cuenta desactivada y cambio de comercio -------------------------------
def _account_form(client, factory, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    factory.staff("admin", "admin1")
    login(client, "admin1")
    created = client.post("/api/payment-accounts", json=ACC).json()
    client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": created["id"]})
    client.post("/logout")
    ref = _submit(client, ev, form, _values()).json()["payment"]["reference"]
    return ev, form, created, ref


def _signed(ref, cents, secret, txn="T9"):
    e = {"event": "transaction.updated", "timestamp": 1700000000,
         "data": {"transaction": {"id": txn, "status": "APPROVED", "amount_in_cents": cents, "reference": ref, "currency": "COP", "payment_method_type": "PSE"}},
         "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"], "checksum": ""}}
    e["signature"]["checksum"] = hashlib.sha256(f"{txn}APPROVED{cents}1700000000{secret}".encode()).hexdigest()
    return e


def test_c2_deactivated_account_still_confirms_and_refunds_what_it_already_charged(client, factory, db):
    ev, form, created, ref = _account_form(client, factory, db)
    login(client, "admin1")
    assert client.put(f"/api/payment-accounts/{created['id']}", json={"active": False}).json()["active"] is False
    pay = db.query(FormPayment).filter(FormPayment.reference == ref).one()
    assert pa.cfg_for_payment(db, pay)["public_key"] == ACC["public_key"]          # reembolsos y conciliación siguen con SUS llaves
    assert pa.cfg_for(db, created["id"], test=False) is None                       # pero no cobra nada nuevo
    hook = created["webhook_url"].split("/webhooks/wompi/")[1]
    r = client.post(f"/webhooks/wompi/{hook}", json=_signed(ref, pay.amount_cents, ACC["events_secret"]))
    assert r.status_code == 200 and r.json() == {"ok": True}
    db.expire_all()
    assert db.query(FormPayment).filter(FormPayment.reference == ref).one().status == "approved"


def test_c3_public_key_is_fixed_once_the_account_charged(client, factory, db):
    _, _, created, _ = _account_form(client, factory, db)
    login(client, "admin1")
    other = {**ACC, "public_key": "pub_prod_OTROCOMERCIO", "private_key": "prv_prod_OTROCOMERCIO"}
    assert client.put(f"/api/payment-accounts/{created['id']}", json=other).status_code == 409
    rotated = {**ACC, "integrity_secret": "prod_integrity_rotado01", "events_secret": "prod_events_rotado01"}
    assert client.put(f"/api/payment-accounts/{created['id']}", json=rotated).status_code == 200          # rotar secretos del MISMO comercio sí
    acc = db.get(PaymentAccount, created["id"])
    db.refresh(acc)
    assert pa.cfg_of(acc)["events_secret"] == "prod_events_rotado01"


# ------------------------------- C6: regla de facturación en estados -------------------------------
def test_c6_billing_rule_only_on_finalizado_base_and_not_on_states_in_use(client, factory, db):
    factory.staff("admin", "admin1")
    login(client, "admin1")
    r = client.post("/api/event-states", json={"name": "Facturado en curso", "base_status": "en_proceso", "rules": {"client_delivery": True}})
    assert r.status_code == 400
    proceso = EventState(name="En proceso X", base_status="en_proceso", position=50, is_active=True, rules_json="{}")
    final = EventState(name="Finalizado X", base_status="finalizado", position=51, is_active=True, rules_json="{}")
    db.add_all([proceso, final])
    db.commit()
    assert client.patch(f"/api/event-states/{proceso.id}", json={"rules": {"client_delivery": True}}).status_code == 400
    ev = factory.event("finalizado", state_id=final.id)
    assert client.patch(f"/api/event-states/{final.id}", json={"rules": {"client_delivery": True}}).status_code == 400          # tiene eventos: «facturarlos» de golpe, no
    db.query(Event).filter(Event.id == ev.id).update({Event.state_id: None})
    db.commit()
    assert client.patch(f"/api/event-states/{final.id}", json={"rules": {"client_delivery": True}}).status_code == 200
