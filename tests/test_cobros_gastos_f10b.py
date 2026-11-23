"""Fase 10, bloque B: cuentas de cobro abiertas (alcance por evento/formulario/panelista) y gastos de infraestructura (estado de conexiones, carga por archivo, contabilidad)."""
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from app import infra_costs as ic
from app import payment_accounts as pa
from app.models import AuditAction, InfraCost, PaymentAccount, WebForm
from tests.conftest import login
from tests.test_cuentas_cobro import ACC
from tests.test_forms import _event
from tests.test_form_payments import _with_payment


@pytest.fixture(autouse=True)
def _enc(monkeypatch):
    monkeypatch.setenv("PAYMENT_KEYS_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _admin(client, factory, name="admin1"):
    factory.staff("admin", name)
    login(client, name)


def _acc(n, **extra):
    return {**ACC, "name": f"Cuenta {n}", "public_key": f"pub_prod_ACCOUNT{n:02d}", "integrity_secret": f"prod_integrity_acc{n:02d}abcd", "events_secret": f"prod_events_acc{n:02d}abcd", **extra}


# ------------------------------------------------------------------ cuentas de cobro
def test_account_is_not_created_or_assigned_automatically(client, factory, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert db.query(PaymentAccount).count() == 0                      # crear un formulario con pago NO crea cuentas
    assert db.get(WebForm, form["id"]).payment_account_id is None


def test_many_accounts_per_event_and_default_scope_is_general(client, factory):
    ev = _event(client, factory)
    _admin(client, factory)
    general = client.post("/api/payment-accounts", json=_acc(1)).json()
    assert general["scope"] == "general" and general["event_id"] is None
    for n in (2, 3):
        r = client.post("/api/payment-accounts", json=_acc(n, scope="evento", event_id=ev.id))
        assert r.status_code == 200, r.text
        assert r.json()["scope"] == "evento" and r.json()["event_id"] == ev.id and r.json()["event_name"] == ev.name
    assert len(client.get("/api/payment-accounts").json()["accounts"]) == 3


def test_scope_validation(client, factory):
    ev = _event(client, factory)
    _admin(client, factory)
    assert client.post("/api/payment-accounts", json=_acc(1, scope="evento")).status_code == 400            # falta el evento
    assert client.post("/api/payment-accounts", json=_acc(1, scope="evento", event_id=999999)).status_code == 400
    assert client.post("/api/payment-accounts", json=_acc(1, scope="formulario")).status_code == 400
    assert client.post("/api/payment-accounts", json=_acc(1, scope="panelista")).status_code == 400          # falta el panelista
    assert client.post("/api/payment-accounts", json=_acc(1, scope="otro")).status_code == 400
    r = client.post("/api/payment-accounts", json=_acc(1, scope="panelista", panelist_ref="Ana Pérez", event_id=ev.id))
    assert r.status_code == 200 and r.json()["panelist_ref"] == "Ana Pérez"


def test_form_scope_derives_event_and_restricts_assignment(client, factory):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    login(client, "coord1")          # _with_payment publica el formulario y cierra la sesión: se entra de nuevo para crear el segundo
    other = _with_payment(client, ev)
    _admin(client, factory)
    acc = client.post("/api/payment-accounts", json=_acc(1, scope="formulario", form_id=form["id"])).json()
    assert acc["event_id"] == ev.id and acc["form_id"] == form["id"] and acc["form_name"]
    assert client.put(f"/api/events/{ev.id}/forms/{other['id']}", json={"payment_account_id": acc["id"]}).status_code == 400      # es de otro formulario
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc["id"]}).status_code == 200


def test_event_scope_blocks_form_of_other_event(client, factory):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    ev2 = factory.event("en_proceso", tenant_id="acme")
    _admin(client, factory)
    acc = client.post("/api/payment-accounts", json=_acc(1, scope="evento", event_id=ev2.id)).json()
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc["id"]}).status_code == 400
    assert client.put(f"/api/payment-accounts/{acc['id']}", json={"scope": "general"}).status_code == 200
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc["id"]}).status_code == 200


def test_cannot_narrow_scope_below_forms_already_using_it(client, factory):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    ev2 = factory.event("en_proceso", tenant_id="acme")
    _admin(client, factory)
    acc = client.post("/api/payment-accounts", json=_acc(1)).json()
    assert client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"payment_account_id": acc["id"]}).status_code == 200
    r = client.put(f"/api/payment-accounts/{acc['id']}", json={"scope": "evento", "event_id": ev2.id})
    assert r.status_code == 409
    assert client.put(f"/api/payment-accounts/{acc['id']}", json={"scope": "evento", "event_id": ev.id}).status_code == 200


def test_scope_change_keeps_keys_encrypted_and_hidden(client, factory, db):
    ev = _event(client, factory)
    _admin(client, factory)
    acc = client.post("/api/payment-accounts", json=_acc(1)).json()
    before = db.query(PaymentAccount).one().integrity_enc
    r = client.put(f"/api/payment-accounts/{acc['id']}", json={"scope": "evento", "event_id": ev.id})
    assert r.status_code == 200
    db.expire_all()
    row = db.query(PaymentAccount).one()
    assert row.integrity_enc == before and pa.cfg_of(row, for_new_charges=False)["integrity_secret"] == _acc(1)["integrity_secret"]
    assert _acc(1)["integrity_secret"] not in r.text


def test_forms_overview_lists_events_for_the_picker(client, factory):
    ev = _event(client, factory)
    _with_payment(client, ev)
    _admin(client, factory)
    d = client.get("/api/payment-accounts-forms").json()
    assert any(e["id"] == ev.id for e in d["events"]) and d["forms"]


# ------------------------------------------------------------------ gastos: conexiones
def test_connections_say_what_is_missing(monkeypatch):
    for k in ("GCP_BILLING_EXPORT_TABLE", "NEON_API_KEY", "NEON_ORG_ID"):
        monkeypatch.delenv(k, raising=False)
    conns = {c["key"]: c for c in ic.connections()}
    assert conns["google"]["state"] == "missing" and "GCP_BILLING_EXPORT_TABLE" in conns["google"]["summary"] and conns["google"]["steps"] and conns["google"]["iam"]
    assert conns["neon"]["state"] == "missing" and "NEON_API_KEY" in conns["neon"]["summary"]
    assert conns["manual"]["state"] == "ok"
    monkeypatch.setenv("GCP_BILLING_EXPORT_TABLE", "mal escrita")
    assert {c["key"]: c for c in ic.connections()}["google"]["state"] == "error"
    monkeypatch.setenv("GCP_BILLING_EXPORT_TABLE", "goldenweb-prod.billing_export.gcp_billing_export_v1_ABC")
    assert {c["key"]: c for c in ic.connections()}["google"]["state"] == "ok"


def test_status_endpoint_always_answers_and_never_leaks_values(client, factory, monkeypatch):
    monkeypatch.setenv("GCP_BILLING_EXPORT_TABLE", "goldenweb-prod.billing_export.gcp_billing_export_v1_ABC")
    monkeypatch.setenv("NEON_API_KEY", "secreto-neon-123")
    _admin(client, factory)
    r = client.get("/api/gastos/infra/status")
    assert r.status_code == 200 and r.json()["table_ready"] is True
    assert "secreto-neon-123" not in r.text and "gcp_billing_export_v1_ABC" not in r.text


def test_import_google_without_connection_explains(client, factory, monkeypatch):
    monkeypatch.delenv("GCP_BILLING_EXPORT_TABLE", raising=False)
    _admin(client, factory)
    r = client.post("/api/gastos/infra/import/google", json={})
    assert r.status_code == 409 and "GCP_BILLING_EXPORT_TABLE" in r.json()["detail"]


# ------------------------------------------------------------------ gastos: archivo CSV
CSV = "mes;proveedor;concepto;tipo;moneda;monto;trm\n2026-11;Neon;Cómputo;variable;USD;19,5;4100\n2026-11;Dominio;golden-eventos.com;fijo;COP;$ 55.000;\n2026-11;nada;X;fijo;COP;10;\n"


def test_parse_csv_semicolon_decimal_comma_and_bad_rows():
    items, warns = ic.parse_csv(CSV)
    assert [i["provider"] for i in items] == ["neon", "domain"]
    assert items[0]["amount"] == Decimal("19.50") and items[0]["amount_cop"] == Decimal("79950.00")
    assert items[1]["amount"] == Decimal("55000.00") and items[1]["kind"] == "fixed"
    assert len(warns) == 1 and warns[0].startswith("Fila 4")


def test_parse_csv_google_export_columns_default_to_google():
    items, warns = ic.parse_csv("invoice_month,service,currency,net_cost\n202611,Cloud Run,COP,120000.50\n")
    assert not warns and items[0]["provider"] == "google" and items[0]["month"] == "2026-11" and items[0]["amount"] == Decimal("120000.50")


@pytest.mark.parametrize("bad", ["", "a,b\n1,2\n", "mes,concepto\n2026-11,x\n"])
def test_parse_csv_needs_columns(bad):
    with pytest.raises(ic.InfraError):
        ic.parse_csv(bad)


def test_csv_upload_is_idempotent_and_keeps_manual(client, factory, db):
    _admin(client, factory)
    manual = client.post("/api/gastos/infra/costs", json={"month": "2026-11", "provider": "neon", "concept": "Cómputo", "kind": "variable", "currency": "COP", "amount": "5"})
    assert manual.status_code == 200
    up = lambda body: client.post("/api/gastos/infra/import/csv", files={"file": ("gastos.csv", body.encode("utf-8"), "text/csv")})   # noqa: E731
    r = up(CSV)
    assert r.status_code == 200 and r.json()["imported"] == 2 and r.json()["skipped"] == 1
    r = up(CSV.replace("19,5", "20"))
    assert r.json() == {**r.json(), "imported": 0, "updated": 2}
    assert db.query(InfraCost).filter(InfraCost.source == "archivo").count() == 2
    assert db.query(InfraCost).filter(InfraCost.source == "manual").count() == 1
    assert db.query(AuditAction).filter_by(entity="infra_cost", action="import").count() == 2
    assert client.post("/api/gastos/infra/import/csv", files={"file": ("x.csv", b"hola", "text/csv")}).status_code == 400


# ------------------------------------------------------------------ gastos: roles
def test_contabilidad_sees_and_registers_costs_but_not_events_tab(client, factory):
    factory.staff("contabilidad", "cont1")
    login(client, "cont1")
    r = client.get("/gastos")
    assert r.status_code == 200 and "Infraestructura" in r.text and 'id="tab_eventos"' not in r.text
    assert client.get("/api/gastos/infra/status").status_code == 200
    body = {"month": "2026-11", "provider": "github", "concept": "Plan", "kind": "fixed", "currency": "COP", "amount": "100"}
    assert client.post("/api/gastos/infra/costs", json=body).status_code == 200
    assert client.get("/api/gastos/eventos/panel").status_code == 403          # satisfacción y tiempos siguen siendo solo de admin


def test_extra_contabilidad_role_on_a_coordinator(client, factory):
    factory.staff("coordinador", "coord_c", extra_roles="contabilidad")
    login(client, "coord_c")
    assert client.get("/api/gastos/infra/status").status_code == 200
    assert client.get("/gastos").status_code == 200


def test_almacen_and_other_roles_stay_out(client, factory):
    for i, role in enumerate(("almacen", "comercial", "digitador")):
        factory.staff(role, f"u{i}")
        login(client, f"u{i}")
        assert client.get("/api/gastos/infra/status").status_code == 403
        assert client.get("/gastos").status_code == 302
        client.post("/logout")


def test_summary_explains_missing_table(client, factory, monkeypatch):
    _admin(client, factory)
    monkeypatch.setattr(ic, "table_ready", lambda db: False)
    r = client.get("/api/gastos/infra/summary")
    assert r.status_code == 503 and "0121" in r.json()["detail"]
    st = client.get("/api/gastos/infra/status").json()
    assert st["table_ready"] is False and st["table_message"]
