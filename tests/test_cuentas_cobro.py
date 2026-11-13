"""Cuentas de cobro de Wompi de terceros (Fase 8, docs/23): llaves cifradas, webhook por cuenta, cobro del formulario con SU cuenta. Las llaves son inventadas; Wompi real no se toca."""
import hashlib

import pytest
from cryptography.fernet import Fernet

from app import payment_accounts as pa
from app import wompi
from app.models import FormPayment, PaymentAccount, WebForm
from tests.conftest import login
from tests.test_forms import _event, _submit
from tests.test_form_payments import PROD, SANDBOX, _staff, _values, _with_payment  # noqa: F401

ACC = {"name": "Feria del Libro", "holder": "Libros S.A.S.", "public_key": "pub_prod_ACCOUNT01", "private_key": "prv_prod_ACCOUNTPRIV1",
       "integrity_secret": "prod_integrity_acc01abcd", "events_secret": "prod_events_acc01abcd"}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture()
def keys(monkeypatch):
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


def _admin(client, factory):
    factory.staff("admin", "admin1")
    login(client, "admin1")


# ------------------------------- lógica pura -------------------------------
def test_keys_are_encrypted_and_roundtrip(monkeypatch):
    token = pa.encrypt("prod_integrity_secret_1")
    assert token.startswith("pk1:") and "prod_integrity" not in token
    assert pa.decrypt(token) == "prod_integrity_secret_1"
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", Fernet.generate_key().decode())     # llave distinta: no se puede leer, pero no revienta
    assert pa.decrypt(token) == ""


def test_no_encryption_key_fails_closed(monkeypatch):
    monkeypatch.delenv("PAYMENT_KEYS_ENCRYPTION_KEY")
    assert not pa.enabled()
    with pytest.raises(pa.KeyMissing):
        pa.encrypt("x")


def test_key_rotation_reads_old_tokens(monkeypatch):
    old = Fernet.generate_key().decode()
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", old)
    token = pa.encrypt("prod_events_x1234567")
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", Fernet.generate_key().decode() + "," + old)
    assert pa.decrypt(token) == "prod_events_x1234567"


def test_validate_keys():
    ok = ("pub_prod_ABCDEFGH12", "prv_prod_ABCDEFGH12", "prod_integrity_ABCDEFGH12", "prod_events_ABCDEFGH12")
    assert pa.validate_keys(*ok) is None
    assert pa.validate_keys("abc", None, ok[2], ok[3])
    assert pa.validate_keys(ok[0], "prv_test_ABCDEFGH12", ok[2], ok[3])           # privada de otro ambiente
    assert pa.validate_keys(ok[0], None, ok[3], ok[2])                              # secretos al revés
    assert pa.validate_keys(ok[0], None, "test_integrity_ABCDEFGH12", ok[3])       # integridad de otro ambiente
    assert pa.validate_keys(ok[0], None, ok[2], ok[3]) is None                      # la privada es opcional


def test_verify_event_cfg_uses_only_that_account_secret():
    cfg = {"events_secret": "prod_events_acc01", "test": False}
    ev = {"event": "transaction.updated", "timestamp": 1, "data": {"transaction": {"id": "T", "status": "APPROVED", "amount_in_cents": 100}},
          "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"], "checksum": ""}}
    ev["signature"]["checksum"] = hashlib.sha256(f"TAPPROVED1001{cfg['events_secret']}".encode()).hexdigest()
    assert wompi.verify_event_cfg(ev, None, cfg) == "prod"
    assert wompi.verify_event_cfg(ev, None, {**cfg, "events_secret": "prod_events_otra"}) is False
    assert wompi.verify_event_cfg(ev, None, {"events_secret": "", "test": False}) is None


# ------------------------------- API -------------------------------
def test_only_admin_manages_accounts(client, factory):
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.get("/api/payment-accounts").status_code == 403
    assert client.post("/api/payment-accounts", json=ACC).status_code == 403


def test_create_account_never_returns_secrets(client, factory, db):
    _admin(client, factory)
    r = client.post("/api/payment-accounts", json=ACC)
    assert r.status_code == 200, r.text
    body = r.text
    for secret in (ACC["private_key"], ACC["integrity_secret"], ACC["events_secret"], ACC["public_key"]):
        assert secret not in body
    assert r.json()["webhook_url"].endswith("/webhooks/wompi/" + db.query(PaymentAccount).one().ref)
    row = db.query(PaymentAccount).one()
    assert ACC["integrity_secret"] not in row.integrity_enc and ACC["private_key"] not in (row.private_enc or "")
    assert ACC["integrity_secret"] not in client.get("/api/payment-accounts").text


def test_create_account_validates_and_needs_encryption_key(client, factory, monkeypatch):
    _admin(client, factory)
    assert client.post("/api/payment-accounts", json={**ACC, "events_secret": "oops"}).status_code == 400
    assert client.post("/api/payment-accounts", json={**ACC, "name": ""}).status_code == 400
    monkeypatch.delenv("PAYMENT_KEYS_ENCRYPTION_KEY")
    assert client.post("/api/payment-accounts", json=ACC).status_code == 503


def test_assign_account_and_form_charges_with_its_keys(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    factory.staff("admin", "admin1")
    login(client, "admin1")
    acc_id = client.post("/api/payment-accounts", json=ACC).json()["id"]
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc_id}).status_code == 200
    assert client.get(f"/api/events/{ev.id}/forms/{form['id']}").json()["payments"]["account_id"] == acc_id
    client.post("/logout")
    pay = _submit(client, ev, form, _values()).json()["payment"]
    assert pay["public_key"] == ACC["public_key"]          # el widget recibe la llave pública de la cuenta del tercero, no la de Golden
    row = db.query(FormPayment).filter(FormPayment.reference == pay["reference"]).one()
    assert row.account_id == acc_id
    expected = wompi.integrity_signature(pay["reference"], row.amount_cents, "COP", ACC["integrity_secret"])
    assert pay["integrity"] == expected                    # firmado con SU secreto de integridad


def test_webhook_per_account(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    factory.staff("admin", "admin1")
    login(client, "admin1")
    created = client.post("/api/payment-accounts", json=ACC).json()
    ref_url = created["webhook_url"].split("/webhooks/wompi/")[1]
    client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": created["id"]})
    client.post("/logout")
    ref = _submit(client, ev, form, _values()).json()["payment"]["reference"]
    cents = db.query(FormPayment).filter(FormPayment.reference == ref).one().amount_cents

    def event(secret):
        e = {"event": "transaction.updated", "timestamp": 1700000000, "data": {"transaction": {"id": "T9", "status": "APPROVED", "amount_in_cents": cents, "reference": ref, "currency": "COP", "payment_method_type": "CARD"}},
             "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"], "checksum": ""}}
        e["signature"]["checksum"] = hashlib.sha256(f"T9APPROVED{cents}1700000000{secret}".encode()).hexdigest()
        return e

    assert client.post("/webhooks/wompi/no-existe", json=event(ACC["events_secret"])).status_code == 404
    assert client.post(f"/webhooks/wompi/{ref_url}", json=event(PROD["WOMPI_EVENTS_SECRET"])).status_code == 401          # firmado con el secreto de Golden: no vale en la cuenta del tercero
    assert client.post("/webhooks/wompi", json=event(ACC["events_secret"])).status_code == 401                              # y el de la cuenta no vale en la URL de Golden
    assert client.post(f"/webhooks/wompi/{ref_url}", json=event(ACC["events_secret"])).json() == {"ok": True}
    assert db.query(FormPayment).filter(FormPayment.reference == ref).one().status == "approved"


def test_cannot_change_account_after_real_payments_and_cannot_delete_used_account(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    factory.staff("admin", "admin1")
    login(client, "admin1")
    acc_id = client.post("/api/payment-accounts", json=ACC).json()["id"]
    client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc_id})
    client.post("/logout")
    _submit(client, ev, form, _values())
    login(client, "admin1")
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": None}).status_code == 409
    assert client.delete(f"/api/payment-accounts/{acc_id}").status_code == 409
    assert client.put(f"/api/payment-accounts/{acc_id}", json={"active": False}).json()["active"] is False


def test_non_admin_cannot_assign_account(client, factory):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": 1}).status_code == 403


def test_test_form_never_uses_production_account_keys(db):
    acc = PaymentAccount(ref="r1", name="x", public_key="pub_prod_ABCDEFGH12", integrity_enc=pa.encrypt("prod_integrity_ABCDEFGH12"), events_enc=pa.encrypt("prod_events_ABCDEFGH12"), active=True)
    db.add(acc)
    db.flush()
    assert pa.cfg_for(db, acc.id, test=True) is None
    assert pa.cfg_for(db, acc.id, test=False)["public_key"] == "pub_prod_ABCDEFGH12"
    acc.active = False
    assert pa.cfg_for(db, acc.id, test=False) is None


def test_payment_link_requires_private_key_and_uses_wompi(client, factory, monkeypatch):
    _admin(client, factory)
    no_priv = client.post("/api/payment-accounts", json={**ACC, "private_key": ""}).json()["id"]
    assert client.post(f"/api/payment-accounts/{no_priv}/payment-link", json={"name": "Entrada"}).status_code == 409
    acc_id = client.post("/api/payment-accounts", json={**ACC, "public_key": "pub_prod_ACCOUNT02"}).json()["id"]
    seen = {}

    def fake(cfg, name, description, amount, single_use=False):
        seen.update(name=name, amount=amount, key=cfg["private_key"])
        return True, {"id": "abc123", "url": "https://checkout.wompi.co/l/abc123"}

    monkeypatch.setattr("app.routers.payment_accounts.wompi.create_payment_link", fake)
    r = client.post(f"/api/payment-accounts/{acc_id}/payment-link", json={"name": "Entrada", "amount_cop": 50000})
    assert r.json()["url"].endswith("/abc123") and seen == {"name": "Entrada", "amount": 50000, "key": ACC["private_key"]}
    assert client.post(f"/api/payment-accounts/{acc_id}/payment-link", json={"name": "Entrada", "amount_cop": 100}).status_code == 400


def test_page_is_admin_only(client, factory):
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.get("/cuentas-de-cobro", follow_redirects=False).status_code in (302, 303, 307)
    client.post("/logout")
    _admin(client, factory)
    assert client.get("/cuentas-de-cobro").status_code == 200
