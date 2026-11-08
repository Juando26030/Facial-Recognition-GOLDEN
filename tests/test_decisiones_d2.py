"""D2 (decisión del dueño, 8-nov-2026): un pago aprobado sin cupo no debe pasar nunca. (a) sin cupo no se accede ni se empieza a pagar; (b) el envío que crea el pago revisa el cupo
de forma atómica (`form_reserve_slot`); (c) el apartado de un pago pendiente dura lo que el pago puede tardar (constante configurable, renovada una vez al haber transacción en curso);
(d) `refund_due` queda solo como red de seguridad, sin sobreaforo. Las llaves de Wompi son inventadas."""
from datetime import timedelta

import pytest

from app import formsvc
from app.models import FormPayment, FormSubmission, SystemEvent
from app.timeutil import utcnow
from tests.test_form_payments import PROD, SANDBOX, TIPO, _event_for, _no_dns, _values, _with_payment  # noqa: F401
from tests.test_forms import _event, _state, _status, _submit, _url


@pytest.fixture()
def keys(monkeypatch):
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


VIP_QUOTA = {"rules": [{"id": "r1", "label": "VIP", "match": "all", "conds": [{"field": "tipo", "op": "equals", "value": "VIP"}], "limit": 1}]}


def _other(n):
    return {**_values(), "cedula": f"20{n}", "correo": f"p{n}@example.com"}


def _limited(client, factory, capacity):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert _status(client, ev, form, capacity=capacity).status_code == 200
    client.post("/logout")
    return ev, form


def _age(db, ref, minutes):
    """Envejece el apartado de un pago (y de su inscripción) como si hubiera pasado ese tiempo."""
    pay = db.query(FormPayment).filter_by(reference=ref).one()
    t = utcnow() - timedelta(minutes=minutes)
    pay.created_at = t
    db.get(FormSubmission, pay.submission_id).created_at = t
    db.commit()
    formsvc.invalidate_held()
    return pay.id


# ------------------------------- (a) y (b): sin cupo no se entra ni se crea el pago -------------------------------
def test_d2a_a_full_form_neither_opens_nor_creates_a_payment(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    first = _submit(client, ev, form, _values(), sid="a")
    assert first.status_code == 200 and first.json()["payment_required"] is True
    st = _state(client, ev, form)
    assert st["stage"] == "closed" and st["reason"] == "cupo_lleno"                       # el apartado del primero cuenta: ya no se puede ni entrar
    r = _submit(client, ev, form, _other(1), sid="b")
    assert r.status_code == 409 and r.json()["stage"] == "closed" and r.json()["detail"].startswith("Se agotaron los cupos")
    assert db.query(FormPayment).count() == 1 and db.query(FormSubmission).count() == 1   # no se creó otro pago ni otra inscripción


def test_d2b_the_reserve_under_lock_refuses_even_when_the_fast_path_cache_is_stale(client, factory, keys, db, monkeypatch):
    """Si la vía rápida (caché de ~2 s) dijera «hay cupo», la reserva atómica de la base manda y no crea el pago."""
    ev, form = _limited(client, factory, capacity=1)
    assert _submit(client, ev, form, _values(), sid="a").status_code == 200
    monkeypatch.setattr(formsvc, "held_count_cached", lambda db_, f_: 0)
    monkeypatch.setattr("app.routers.forms_public._access", lambda *a, **k: "activo")
    r = _submit(client, ev, form, _other(2), sid="b")
    assert r.status_code == 409 and "Se agotaron los cupos" in r.json()["detail"]
    assert db.query(FormPayment).count() == 1


def test_d2b_a_quota_by_variable_that_is_full_does_not_create_the_payment(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev, extra=[TIPO], quotas=VIP_QUOTA)
    client.post("/logout")
    assert _submit(client, ev, form, _values(tipo="VIP"), sid="a").status_code == 200
    r = _submit(client, ev, form, _other(3) | {"tipo": "VIP"}, sid="b")
    assert r.status_code == 409 and r.json()["stage"] == "quota"
    assert db.query(FormPayment).count() == 1
    assert _submit(client, ev, form, _other(4) | {"tipo": "General"}, sid="c").status_code == 200          # otra variable sigue abierta


# ------------------------------- (c) el apartado dura lo que el pago puede tardar -------------------------------
def test_d2c_the_hold_is_configurable_and_longer_than_15_minutes_by_default(monkeypatch):
    monkeypatch.delenv("FORM_PENDING_HOLD_MINUTES", raising=False)
    assert formsvc._hold_minutes() == 30
    monkeypatch.setenv("FORM_PENDING_HOLD_MINUTES", "45")
    assert formsvc._hold_minutes() == 45
    monkeypatch.setenv("FORM_PENDING_HOLD_MINUTES", "1")
    assert formsvc._hold_minutes() == 5                  # piso: menos que eso no deja pagar
    monkeypatch.setenv("FORM_PENDING_HOLD_MINUTES", "99999")
    assert formsvc._hold_minutes() == 180                # techo: más permitiría acaparar cupos sin pagar
    monkeypatch.setenv("FORM_PENDING_HOLD_MINUTES", "abc")
    assert formsvc._hold_minutes() == 30


def test_d2c_a_slow_payment_between_15_minutes_and_the_hold_keeps_its_seat(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref, 20)                                                                       # antes (15 min) ya habría perdido el cupo
    assert _submit(client, ev, form, _other(5), sid="b").status_code == 409
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED"))
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="a").one().status == "confirmed"


def test_d2c_a_transaction_in_flight_renews_the_hold_once(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    pay_id = _age(db, ref, 25)
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "PENDING", txn="T9", method="PSE"))     # Wompi: hay una transacción PSE en curso
    db.expire_all()
    pay = db.get(FormPayment, pay_id)
    assert pay.transaction_id == "T9" and pay.created_at > utcnow() - timedelta(minutes=2)                      # el apartado volvió a empezar
    assert db.get(FormSubmission, pay.submission_id).created_at > utcnow() - timedelta(minutes=2)
    old = pay.created_at
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "PENDING", txn="T9", method="PSE"))     # un segundo aviso igual NO lo renueva otra vez
    db.expire_all()
    assert db.get(FormPayment, pay_id).created_at == old


def test_d2c_an_expired_hold_is_not_renewed_so_it_cannot_take_a_seat_someone_else_got(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    pay_id = _age(db, ref, 90)
    pay = db.get(FormPayment, pay_id)
    sub = db.get(FormSubmission, pay.submission_id)
    assert formsvc.extend_hold(pay, sub) is False


# ------------------------------- (d) red de seguridad: sin sobreaforo -------------------------------
def test_d2d_an_approval_after_the_hold_expired_and_the_seat_was_taken_goes_to_refund_due(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref_a = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref_a, 60)                                                                      # el apartado de A venció (y nadie lo renovó)
    ref_b = _submit(client, ev, form, _other(6), sid="b").json()["payment"]["reference"]     # B toma el cupo liberado
    client.post("/webhooks/wompi", json=_event_for("prod", ref_b, 15000000, "APPROVED", txn="TB"))
    client.post("/webhooks/wompi", json=_event_for("prod", ref_a, 15000000, "APPROVED", txn="TA"))    # el dinero de A se movió fuera de nuestro control
    db.expire_all()
    got = {s.sid: s.status for s in db.query(FormSubmission)}
    assert got == {"b": "confirmed", "a": formsvc.REFUND_DUE}                                # nunca más confirmadas que el cupo
    assert db.query(FormSubmission).filter_by(status="confirmed").count() <= 1
    assert db.query(FormPayment).filter_by(reference=ref_a).one().status == "approved"      # el cobro queda a la vista para reembolsar
    assert db.query(SystemEvent).filter_by(kind="payment_refund_due").count() == 1


def test_d2d_an_approval_after_the_hold_expired_with_the_seat_still_free_is_admitted(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref, 60)
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED"))
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="a").one().status == "confirmed"


def test_d2d_an_expired_payment_does_not_overflow_a_variable_quota(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev, extra=[TIPO], quotas=VIP_QUOTA)
    client.post("/logout")
    ref_a = _submit(client, ev, form, _values(tipo="VIP"), sid="a").json()["payment"]["reference"]
    _age(db, ref_a, 60)
    ref_b = _submit(client, ev, form, _other(7) | {"tipo": "VIP"}, sid="b").json()["payment"]["reference"]
    client.post("/webhooks/wompi", json=_event_for("prod", ref_b, 15000000, "APPROVED", txn="TB"))
    client.post("/webhooks/wompi", json=_event_for("prod", ref_a, 15000000, "APPROVED", txn="TA"))
    db.expire_all()
    assert {s.sid: s.status for s in db.query(FormSubmission)} == {"b": "confirmed", "a": formsvc.REFUND_DUE}
