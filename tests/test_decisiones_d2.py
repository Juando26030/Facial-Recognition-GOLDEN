"""D2 (decisión del dueño, 8-nov-2026): un pago aprobado sin cupo no debe pasar nunca. (a) sin cupo no se accede ni se empieza a pagar; (b) el envío que crea el pago revisa el cupo
de forma atómica (`form_reserve_slot`); (c) el cupo se BLOQUEA al hacer clic en pagar y se libera solo a los 10 minutos (FORM_HOLD_MINUTES; como un asiento de cine);
(d) `refund_due` queda solo como red de seguridad, sin sobreaforo. Las llaves de Wompi son inventadas."""
from datetime import timedelta

import pytest

from app import formsvc
from app.models import FormPayment, FormSubmission, SystemEvent, WebForm
from app.timeutil import utcnow
from tests.test_form_payments import PROD, SANDBOX, TIPO, _event_for, _no_dns, _staff, _values, _with_payment  # noqa: F401
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
    _staff(client)                                                                          # _with_payment cierra la sesión: se vuelve a entrar para fijar el cupo
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


# ------------------------------- (c) cupo como asiento de cine: se bloquea al pagar, se libera a los 10 minutos -------------------------------
def test_d2c_the_hold_is_10_minutes_by_default_and_configurable(monkeypatch):
    monkeypatch.delenv("FORM_HOLD_MINUTES", raising=False)
    assert formsvc._hold_minutes() == 10 and formsvc.PENDING_HOLD == timedelta(minutes=10)
    monkeypatch.setenv("FORM_HOLD_MINUTES", "20")
    assert formsvc._hold_minutes() == 20
    monkeypatch.setenv("FORM_HOLD_MINUTES", "0")
    assert formsvc._hold_minutes() == 2              # piso
    monkeypatch.setenv("FORM_HOLD_MINUTES", "99999")
    assert formsvc._hold_minutes() == 180            # techo
    monkeypatch.setenv("FORM_HOLD_MINUTES", "abc")
    assert formsvc._hold_minutes() == 10


def test_d2c_clicking_pay_blocks_the_seat_and_tells_the_person(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    r = _submit(client, ev, form, _values(), sid="a").json()
    assert r["payment_required"] is True and r["hold_minutes"] == 10
    assert formsvc.held_count(db, db.get(WebForm, form["id"])) == 1                          # bloqueado aunque no haya terminado de pagar
    assert _submit(client, ev, form, _other(8), sid="b").status_code == 409
    assert "Tu cupo está reservado por ${data.hold_minutes} minutos mientras pagas." in open("templates/form_public.html", encoding="utf-8").read()


def test_d2c_approval_confirms_the_blocked_seat(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref, 8)                                                                          # aún dentro de los 10 minutos
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED"))
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="a").one().status == "confirmed"
    assert formsvc.held_count(db, db.get(WebForm, form["id"])) == 1


def test_d2c_the_seat_is_released_after_10_minutes_without_paying(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref, 9)
    assert _submit(client, ev, form, _other(9), sid="b").status_code == 409                   # a los 9 min sigue bloqueado
    _age(db, ref, 11)
    assert formsvc.held_count(db, db.get(WebForm, form["id"])) == 0
    assert _submit(client, ev, form, _other(9), sid="c").status_code == 200                   # a los 11 min otra persona lo toma


@pytest.mark.parametrize("status", ["DECLINED", "ERROR", "VOIDED"])
def test_d2c_a_failed_or_cancelled_payment_releases_the_seat_at_once(client, factory, keys, db, status):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, status))
    assert formsvc.held_count(db, db.get(WebForm, form["id"])) == 0
    assert _submit(client, ev, form, _other(10), sid="b").status_code == 200


def test_d2c_two_people_competing_for_the_last_seat_only_one_gets_it(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=2)
    assert _submit(client, ev, form, _values(), sid="a").status_code == 200                   # queda 1
    r1 = _submit(client, ev, form, _other(11), sid="b")
    r2 = _submit(client, ev, form, _other(12), sid="c")
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    assert db.query(FormPayment).count() == 2                                                  # solo 2 pagos creados para 2 cupos


# ------------------------------- (d) red de seguridad: sin sobreaforo -------------------------------
def test_d2d_an_approval_after_the_hold_expired_and_the_seat_was_taken_goes_to_refund_due(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref_a = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _age(db, ref_a, 15)                                                                      # el apartado de A venció (y nadie lo renovó)
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
    _age(db, ref, 15)
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED"))
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="a").one().status == "confirmed"


def test_d2d_an_expired_payment_does_not_overflow_a_variable_quota(client, factory, keys, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev, extra=[TIPO], quotas=VIP_QUOTA)
    client.post("/logout")
    ref_a = _submit(client, ev, form, _values(tipo="VIP"), sid="a").json()["payment"]["reference"]
    _age(db, ref_a, 15)
    ref_b = _submit(client, ev, form, _other(7) | {"tipo": "VIP"}, sid="b").json()["payment"]["reference"]
    client.post("/webhooks/wompi", json=_event_for("prod", ref_b, 15000000, "APPROVED", txn="TB"))
    client.post("/webhooks/wompi", json=_event_for("prod", ref_a, 15000000, "APPROVED", txn="TA"))
    db.expire_all()
    assert {s.sid: s.status for s in db.query(FormSubmission)} == {"b": "confirmed", "a": formsvc.REFUND_DUE}
