"""Auditoría de dinero (Fase 3E): D1/R1 (nadie descarta el pago de otra persona), R2 (dos pendientes con la misma cédula no se confirman ambos), D16 (descartar una anulación pendiente
pregunta a Wompi), R3 (la conciliación rota), R4 (códigos de un solo uso), D8 (el secreto que firma decide el ambiente) y R8 (monto «inf» en un reembolso). Las llaves son inventadas."""
import pytest

from app import wompi
from app.models import FormPayment, FormSubmission, SystemEvent, WebForm
from tests.conftest import login
from tests.test_form_extras import _codes, _disc_form
from tests.test_form_payments import PROD, SANDBOX, _approved, _event_for, _no_dns, _refund, _values, _with_payment  # noqa: F401
from tests.test_forms import _event, _submit, _url

@pytest.fixture()
def keys(monkeypatch):
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


OTHER = {"cedula": "3003", "nombres": "Eva", "apellidos": "Ruiz", "correo": "eva@example.com"}


def _approve(client, ref, txn="T1", cents=15000000):
    return client.post("/webhooks/wompi", json=_event_for("prod", ref, cents, "APPROVED", txn=txn))


# ------------------------------- D1 / R1 / R9 -------------------------------
def test_d1_another_person_typing_my_cedula_cannot_discard_my_payment_in_progress(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    victim = _submit(client, ev, form, _values(), sid="victima").json()["payment"]["reference"]
    assert _submit(client, ev, form, _values(), sid="atacante").status_code == 200       # misma cédula 1001, otra sesión: conviven
    assert db.query(FormSubmission).filter_by(sid="victima").count() == 1                 # la de la víctima NO se borró
    assert _approve(client, victim).json() == {"ok": True}
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="victima").one().status == "confirmed"
    assert db.query(FormPayment).filter_by(reference=victim).one().submission_id is not None      # el pago sigue ligado a su inscripción


@pytest.mark.parametrize("state, blocked", [("pending", True), ("approved", True), ("unknown", True), ("declined", False), ("none", False)])
def test_d1_retry_in_the_same_session_asks_wompi_before_discarding(client, factory, keys, db, monkeypatch, state, blocked):
    monkeypatch.setattr(wompi, "reference_state", lambda cfg, reference: state)
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    first = _submit(client, ev, form, _values(), sid="s1").json()["payment"]["reference"]
    r = _submit(client, ev, form, _values(), sid="s1")
    assert db.query(FormSubmission).count() == 1
    if blocked:
        assert r.status_code == 409 and "pago en proceso" in r.json()["detail"]
        assert db.query(FormPayment).one().reference == first                              # el intento anterior sigue intacto
    else:
        assert r.status_code == 200 and r.json()["payment"]["reference"] != first


def test_r9_the_per_ip_pending_cap_no_longer_skips_submissions_with_the_same_cedula(client, factory, keys, monkeypatch):
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "3")
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    for n in range(3):
        assert _submit(client, ev, form, _values(), sid=f"s{n}").status_code == 200       # misma cédula, tres sesiones
    assert _submit(client, ev, form, _values(), sid="s9").status_code == 429               # antes la cédula repetida no contaba y el tope no frenaba nada


def test_r1_discard_never_deletes_a_submission_confirmed_in_the_meantime(client, factory, keys, db):
    from app import formsvc
    from app.database import SessionLocal
    from app.routers.form_payments import apply_result
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    _submit(client, ev, form, _values(), sid="s1")
    pay = db.query(FormPayment).one()
    pay_id = pay.id
    stale = db.get(FormSubmission, pay.submission_id)                                       # en memoria de ESTA sesión: awaiting_payment
    assert stale.status == formsvc.PENDING
    other = SessionLocal()
    try:
        apply_result(other, pay_id, "APPROVED", "T1")                                      # otro proceso (el webhook) la confirma
    finally:
        other.close()
    assert formsvc.discard_submission(db, db.get(WebForm, form["id"]), stale, force=True) is False
    db.expire_all()
    assert db.get(FormSubmission, stale.id).status == "confirmed"
    assert db.get(FormPayment, pay_id).submission_id == stale.id


# ------------------------------- R2 -------------------------------
def test_r2_two_pending_submissions_of_the_same_cedula_cannot_both_be_confirmed(client, factory, keys, db):
    from app import formsvc
    ev = _event(client, factory)
    factory.staff("admin", "adm1")
    form = _with_payment(client, ev)
    a = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    b = _submit(client, ev, form, _values(), sid="b").json()["payment"]["reference"]       # conviven (D1)
    _approve(client, a, "T1")
    _approve(client, b, "T2")                                                              # el segundo en llegar no se confirma
    db.expire_all()
    assert sorted(s.status for s in db.query(FormSubmission)) == ["confirmed", formsvc.REFUND_DUE]
    assert db.query(SystemEvent).filter_by(kind="payment_refund_due").count() == 1
    assert formsvc.held_count(db, db.get(WebForm, form["id"])) == 1                         # y no aparta cupo
    login(client, "adm1")
    rows = client.get(f"/api/events/{ev.id}/forms/{form['id']}/payments").json()["rows"]
    flagged = [r for r in rows if r["reference"] == b]
    assert len(flagged) == 1 and "reembolsa" in flagged[0]["review"].lower() and flagged[0]["status"] == "approved"
    assert len(client.get(f"/api/events/{ev.id}/forms/{form['id']}/submissions").json()["rows"]) == 1
    r = _refund(client, ev, form, flagged[0], reason="Cobro doble", manual=True, note="transferencia de prueba 1")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert sorted(s.status for s in db.query(FormSubmission)) == ["confirmed", "refunded"]


def test_r2_a_repeated_approval_of_a_flagged_payment_stays_flagged(client, factory, keys, db):
    from app import formsvc
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    a = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    b = _submit(client, ev, form, _values(), sid="b").json()["payment"]["reference"]
    _approve(client, a, "T1")
    _approve(client, b, "T2")
    _approve(client, b, "T2")                                                              # webhook repetido: idempotente
    db.expire_all()
    assert sorted(s.status for s in db.query(FormSubmission)) == ["confirmed", formsvc.REFUND_DUE]


# ------------------------------- D8 -------------------------------
def test_d8_sandbox_secret_cannot_approve_a_production_payment_even_without_environment(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    ref = _submit(client, ev, form, _values()).json()["payment"]["reference"]
    forged = _event_for("test", ref, 15000000, "APPROVED")
    forged.pop("environment")                                                              # sin el campo (que no va firmado) antes se saltaba la defensa
    assert client.post("/webhooks/wompi", json=forged).json()["ignored"] == "ambiente distinto al del pago"
    assert db.query(FormPayment).one().status == "pending"


def test_d8_the_signing_secret_decides_the_environment_not_the_unsigned_field(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    ref = _submit(client, ev, form, _values()).json()["payment"]["reference"]
    genuine = _event_for("prod", ref, 15000000, "APPROVED")
    genuine["environment"] = "test"                                                        # mentira en un campo sin firma: no cambia nada
    assert client.post("/webhooks/wompi", json=genuine).json() == {"ok": True}
    assert db.query(FormPayment).one().status == "approved"


def test_d8_verify_event_env(keys):
    assert wompi.verify_event_env(_event_for("prod", "R", 100, "APPROVED")) == "prod"
    assert wompi.verify_event_env(_event_for("test", "R", 100, "APPROVED")) == "test"
    bad = _event_for("prod", "R", 100, "APPROVED")
    bad["signature"]["checksum"] = "0" * 64
    assert wompi.verify_event_env(bad) is False


# ------------------------------- D16 -------------------------------
def _pending_void(client, ev, form, pay, monkeypatch, txn_status="PENDING"):
    monkeypatch.setattr("app.routers.form_refunds.wompi.void_transaction", lambda cfg, txn, *a: (True, {"data": {"transaction": {"status": "PENDING"}}}))
    monkeypatch.setattr("app.routers.form_refunds.wompi.fetch_transaction", lambda cfg, txn: {"status": txn_status})
    assert _refund(client, ev, form, pay, reason="anular").json()["status"] == "pending"
    rid = client.get(f"/api/events/{ev.id}/forms/{form['id']}/payments").json()["rows"][0]["refunds"][0]["id"]
    return f"/api/events/{ev.id}/forms/{form['id']}/payments/{pay['id']}/refunds/{rid}"


def test_d16_discarding_a_pending_void_that_wompi_already_finished_completes_it(client, factory, keys, monkeypatch):
    ev, form, pay = _approved(client, factory)
    base = _pending_void(client, ev, form, pay, monkeypatch)
    monkeypatch.setattr("app.routers.form_refunds.wompi.fetch_transaction", lambda cfg, txn: {"status": "VOIDED"})
    r = client.post(f"{base}/discard")
    assert r.status_code == 200 and r.json()["status"] == "done" and "NO registres otro" in r.json()["message"]
    row = client.get(f"/api/events/{ev.id}/forms/{form['id']}/payments").json()["rows"][0]
    assert row["status"] == "refunded"
    assert _refund(client, ev, form, pay, reason="otra vez", manual=True, note="transferencia 1").status_code == 400      # ya no se puede devolver dos veces


def test_d16_discarding_a_pending_void_without_knowing_its_state_is_refused(client, factory, keys, monkeypatch):
    ev, form, pay = _approved(client, factory)
    base = _pending_void(client, ev, form, pay, monkeypatch)
    monkeypatch.setattr("app.routers.form_refunds.wompi.fetch_transaction", lambda cfg, txn: None)          # Wompi no responde
    assert client.post(f"{base}/discard").status_code == 503
    assert client.get(f"/api/events/{ev.id}/forms/{form['id']}/payments").json()["rows"][0]["refunds"][0]["status"] == "pending"


def test_d16_a_void_after_a_manual_refund_raises_an_alert_but_our_own_voids_do_not(client, factory, keys, db, monkeypatch):
    ev, form, pay = _approved(client, factory)
    base = _pending_void(client, ev, form, pay, monkeypatch)
    assert client.post(f"{base}/discard").json()["status"] == "failed"                      # Wompi decía «PENDING»: se descarta
    assert _refund(client, ev, form, pay, reason="a mano", manual=True, note="transferencia 1").status_code == 200
    client.post("/logout")
    client.post("/webhooks/wompi", json=_event_for("prod", pay["reference"], 15000000, "VOIDED", txn="T1"))   # y Wompi la anula igual: doble devolución
    assert db.query(SystemEvent).filter_by(kind="void_after_refund").count() == 1
    assert db.query(FormPayment).one().status == "refunded"                                 # el pago no cambia


def test_d16_the_webhook_of_a_void_we_made_ourselves_is_not_an_alert(client, factory, keys, db, monkeypatch):
    ev, form, pay = _approved(client, factory)
    monkeypatch.setattr("app.routers.form_refunds.wompi.void_transaction", lambda cfg, txn, *a: (True, {"data": {"transaction": {"status": "VOIDED"}}}))
    monkeypatch.setattr("app.routers.form_refunds.wompi.fetch_transaction", lambda cfg, txn: {"status": "VOIDED"})
    assert _refund(client, ev, form, pay, reason="anular").json()["status"] == "done"
    client.post("/logout")
    client.post("/webhooks/wompi", json=_event_for("prod", pay["reference"], 15000000, "VOIDED", txn="T1"))
    assert db.query(SystemEvent).filter_by(kind="void_after_refund").count() == 0


# ------------------------------- R8 -------------------------------
@pytest.mark.parametrize("amount", ["inf", "-inf", "nan", "1e999"])
def test_r8_a_non_finite_refund_amount_is_a_400_not_a_500(client, factory, keys, amount):
    ev, form, pay = _approved(client, factory)
    r = _refund(client, ev, form, pay, reason="prueba", manual=True, note="nota", amount=amount)
    assert r.status_code == 400 and "número" in r.json()["detail"]


# ------------------------------- R3 -------------------------------
def test_r3_reconcile_rotates_and_reaches_recent_payments(client, factory, keys, db, monkeypatch):
    from datetime import timedelta
    from app import reconcile
    from app.timeutil import utcnow
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    recent_ref = _submit(client, ev, form, _values(), sid="reciente").json()["payment"]["reference"]
    now = utcnow()
    recent = db.query(FormPayment).filter_by(reference=recent_ref).one()
    recent.created_at = now - timedelta(minutes=10)
    for i in range(205):                                                                    # pagos abandonados: la persona nunca abrió el widget
        db.add(FormPayment(form_id=recent.form_id, event_id=recent.event_id, amount_cents=15000000, currency="COP", status="pending", is_test=False, reference=f"GW-OLD-{i}",
                           created_at=now - timedelta(days=2), updated_at=now - timedelta(days=1)))
    db.commit()

    def fake_fetch(cfg, reference):
        if reference != recent_ref:
            return None                                                                     # Wompi no tiene nada de los abandonados
        return {"id": "TX-R", "status": "APPROVED", "amount_in_cents": 15000000, "currency": "COP", "payment_method_type": "CARD"}

    monkeypatch.setattr(reconcile.wompi, "fetch_by_reference", fake_fetch)
    first = reconcile.reconcile_pending(db, limit=200)
    assert first["checked"] == 200 and first["not_found"] == 200
    db.expire_all()
    assert db.query(FormPayment).filter_by(reference=recent_ref).one().status == "pending"  # en la primera corrida aún no le tocaba
    second = reconcile.reconcile_pending(db, limit=200)
    db.expire_all()
    assert db.query(FormPayment).filter_by(reference=recent_ref).one().status == "approved"      # en la segunda sí: ya no se atasca en los 200 más viejos
    assert db.query(FormSubmission).one().status == "confirmed"
    assert second["updated"] == 1


# ------------------------------- R4 -------------------------------
def test_r4_unique_codes_keep_at_least_six_random_characters(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [{"label": "Cortesía", "kind": "percent", "value": 100, "how": "code", "when": []}])
    did = saved["discounts"][0]["id"]
    for prefix in ("", "VIP", "ABCDE", "ABCDEF"):
        r = _codes(client, ev, form, discount_id=did, mode="unique", count=5, prefix=prefix)
        assert r.status_code == 200, r.text
        assert all(len(c) - len(prefix) >= 6 for c in r.json()["codes"]), (prefix, r.json()["codes"])


def test_r4_guessing_discount_codes_is_stopped_per_ip(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [{"label": "Código", "kind": "percent", "value": 20, "how": "code", "when": []}])
    assert _codes(client, ev, form, discount_id=saved["discounts"][0]["id"], mode="shared", code="FERIA", max_uses=5).status_code == 200
    quote = f"{_url(ev, form)}/quote"
    for i in range(12):
        r = client.post(quote, json={"values": {}, "code": f"NOPE{i}"})
        assert r.status_code == 200 and r.json()["code"]["status"] == "invalid"
    assert client.post(quote, json={"values": {}, "code": "NOPE99"}).status_code == 429       # frenado
    assert client.post(quote, json={"values": {}, "code": "FERIA"}).status_code == 429        # desde esta IP ni el bueno, hasta que pase la ventana
    r = client.post(quote, json={"values": {}, "code": "FERIA"}, headers={"cf-connecting-ip": "203.0.113.9"})      # otra IP no está castigada
    assert r.status_code == 200 and r.json()["code"]["status"] == "ok"


def test_r4_guessing_discount_codes_is_stopped_per_form_even_rotating_ips(client, factory, keys, monkeypatch):
    from app.routers import forms_public
    monkeypatch.setattr(forms_public, "CODE_FAIL_FORM_MAX", 3)
    ev, form, _ = _disc_form(client, factory, [{"label": "Código", "kind": "percent", "value": 20, "how": "code", "when": []}])
    quote = f"{_url(ev, form)}/quote"
    for i in range(3):
        assert client.post(quote, json={"values": {}, "code": f"NOPE{i}"}, headers={"cf-connecting-ip": f"203.0.113.{i + 1}"}).status_code == 200
    assert client.post(quote, json={"values": {}, "code": "NOPE9"}, headers={"cf-connecting-ip": "203.0.113.50"}).status_code == 429


def test_r4_wrong_codes_on_submit_also_count(client, factory, keys, monkeypatch):
    from app.routers import forms_public
    monkeypatch.setattr(forms_public, "CODE_FAIL_IP_MAX", 2)
    ev, form, _ = _disc_form(client, factory, [{"label": "Código", "kind": "percent", "value": 20, "how": "code", "when": []}])
    for n in range(2):
        r = _submit(client, ev, form, OTHER, code=f"MAL{n}", sid=f"s{n}")
        assert r.status_code == 422 and r.json()["code_error"]
    assert _submit(client, ev, form, OTHER, code="MAL9", sid="s9").status_code == 429
    assert _submit(client, ev, form, OTHER, sid="sx").status_code == 200                      # sin código se puede enviar con normalidad
