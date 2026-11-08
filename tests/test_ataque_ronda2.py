"""Ronda de ataque 2 (8-nov-2026): H1 apartado y aprobación tardía tras un rechazo, H2 topes de pendientes bajo candado y por cédula, H3 renovaciones por sesión,
auditoría de ajustes de control y escarapela digital. Las llaves de Wompi son inventadas."""
import json
from datetime import timedelta

import pytest

from app import formsvc, wompi
from app.models import AuditAction, FormPayment, FormSubmission, RateLimitEvent, SystemEvent, WebForm
from tests.conftest import login
from tests.test_decisiones_d2 import _limited, _other
from tests.test_form_payments import PROD, SANDBOX, _event_for, _no_dns, _values, _with_payment  # noqa: F401
from tests.test_forms import _event, _submit


@pytest.fixture()
def keys(monkeypatch):
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


def _hook(client, ref, status, txn="T"):
    return client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, status, txn=txn))


# ------------------------------- H1 -------------------------------
def test_h1_a_late_approval_after_a_decline_does_not_oversell_a_seat_taken_by_someone_else(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref_a = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _hook(client, ref_a, "DECLINED", "TA0")                                                   # A es rechazado: el cupo se libera
    ref_b = _submit(client, ev, form, _other(7), sid="b").json()["payment"]["reference"]      # B lo toma y paga
    _hook(client, ref_b, "APPROVED", "TB")
    _hook(client, ref_a, "APPROVED", "TA")                                                    # Wompi aprueba después la referencia de A (dentro de los 10 min)
    db.expire_all()
    got = {s.sid: s.status for s in db.query(FormSubmission)}
    assert got == {"b": "confirmed", "a": formsvc.REFUND_DUE}
    assert db.query(FormSubmission).filter_by(status="confirmed").count() == 1
    assert db.query(SystemEvent).filter_by(kind="payment_refund_due").count() == 1


def test_h1_a_late_approval_after_a_decline_with_the_seat_still_free_is_admitted(client, factory, keys, db):
    ev, form = _limited(client, factory, capacity=1)
    ref = _submit(client, ev, form, _values(), sid="a").json()["payment"]["reference"]
    _hook(client, ref, "ERROR")
    _hook(client, ref, "APPROVED", "TA")
    db.expire_all()
    assert db.query(FormSubmission).filter_by(sid="a").one().status == "confirmed"


# ------------------------------- H2 -------------------------------
def test_h2_the_ip_and_person_caps_are_checked_after_the_lock_is_taken():
    src = open("app/routers/forms_public.py", encoding="utf-8").read()
    body = src[src.index("def _reserve_and_store"):src.index("def _widget_params")]
    assert body.index("formsvc.reserve_slot(") < body.index("formsvc.pending_from_ip(") < body.index("db.commit()")
    assert body.index("formsvc.reserve_slot(") < body.index("formsvc.pending_for_person(")


def test_h2_person_cap_is_configurable(monkeypatch):
    monkeypatch.delenv("FORM_PENDING_MAX_PER_PERSON", raising=False)
    assert formsvc.pending_max_per_person() == 2
    monkeypatch.setenv("FORM_PENDING_MAX_PER_PERSON", "0")
    assert formsvc.pending_max_per_person() == 0
    monkeypatch.setenv("FORM_PENDING_MAX_PER_PERSON", "basura")
    assert formsvc.pending_max_per_person() == 2


def test_h2_one_cedula_cannot_hold_more_than_the_cap_of_pending_payments(client, factory, keys, db, monkeypatch):
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "0")
    monkeypatch.setenv("FORM_PENDING_MAX_PER_PERSON", "2")
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert _submit(client, ev, form, _values(), sid="s1").status_code == 200
    assert _submit(client, ev, form, _values(), sid="s2").status_code == 200
    r = _submit(client, ev, form, _values(), sid="s3")
    assert r.status_code == 429 and "Este documento" in r.json()["detail"]
    assert db.query(FormSubmission).count() == 2 and db.query(FormPayment).count() == 2     # no se creó otra inscripción ni otro pago


def test_h2_the_person_cap_does_not_count_the_own_session_nor_other_people(client, factory, keys, db, monkeypatch):
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "0")
    monkeypatch.setenv("FORM_PENDING_MAX_PER_PERSON", "1")
    monkeypatch.setattr(wompi, "reference_state", lambda cfg, reference: "none")
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert _submit(client, ev, form, _values(), sid="s1").status_code == 200
    assert _submit(client, ev, form, _values(), sid="s1").status_code == 200               # reintento de la misma sesión: no es «otra» inscripción
    assert _submit(client, ev, form, _other(3), sid="s2").status_code == 200               # otra cédula


# ------------------------------- H3 -------------------------------
def test_h3_one_session_cannot_renew_its_hold_without_limit(client, factory, keys, db, monkeypatch):
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "0")
    monkeypatch.setenv("FORM_RENEWALS_MAX", "3")
    monkeypatch.setattr(wompi, "reference_state", lambda cfg, reference: "none")
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    for _ in range(3):
        assert _submit(client, ev, form, _values(), sid="s1").status_code == 200
    r = _submit(client, ev, form, _values(), sid="s1")
    assert r.status_code == 429 and "demasiadas veces" in r.json()["detail"]
    assert db.query(FormSubmission).count() == 1 and db.query(FormPayment).count() == 3    # los pagos viejos quedan sin inscripción; no se creó un cuarto apartado
    assert _submit(client, ev, form, _other(4), sid="s2").status_code == 200                  # otra sesión no se ve afectada
    db.query(RateLimitEvent).filter_by(kind=formsvc.RENEWAL_KIND).update({"created_at": formsvc.utcnow() - formsvc.PENDING_HOLD * 3 - timedelta(minutes=1)})
    db.commit()
    assert _submit(client, ev, form, _values(), sid="s1").status_code == 200                  # pasada la ventana vuelve a poder


def test_h3_renewals_default_is_five(monkeypatch):
    monkeypatch.delenv("FORM_RENEWALS_MAX", raising=False)
    assert formsvc.renewals_max() == 5


# ------------------------------- auditoría y escarapela digital -------------------------------
def test_audit_for_allow_repeat_delivery_changes(client, factory, db):
    from tests.test_decisiones_d7 import _setup
    ev = _setup(client, factory)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Agua", "initial_qty": 5}).json()
    client.patch(f"/api/events/{ev.id}/inventory/{item['id']}", json={"allow_repeat_delivery": False})        # sin cambio: no audita
    assert db.query(AuditAction).filter_by(entity="inventory_item", action="update").count() == 0
    client.patch(f"/api/events/{ev.id}/inventory/{item['id']}", json={"allow_repeat_delivery": True})
    row = db.query(AuditAction).filter_by(entity="inventory_item", action="update").one()
    assert "False -> True" in row.detail


def test_audit_for_accept_no_birth_mode_changes(client, factory, db):
    from tests.test_coordinador_crea_eventos import _payload
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    eid = client.post("/api/events", json=_payload(coord.id)).json()["id"]
    assert client.put(f"/api/events/{eid}/biometric-setup", json={"accept_no_birth_mode": "any"}).status_code == 200
    row = db.query(AuditAction).filter_by(entity="event_accept_no_birth_mode").one()
    assert row.detail == "require_personal_link -> any"


def test_turning_the_digital_badge_off_audits_and_forgets_the_selected_fields(client, factory, db):
    from app.models import Event
    from tests.test_digital_badge_fields import _setup
    ev, _token = _setup(client, factory, db)
    assert client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["phone", "email"]}).status_code == 200
    assert client.put(f"/api/events/{ev.id}/digital-badge-enabled", json={"enabled": False}).status_code == 200
    db.expire_all()
    assert db.get(Event, ev.id).digital_badge_fields is None
    assert client.put(f"/api/events/{ev.id}/digital-badge-enabled", json={"enabled": True}).status_code == 200
    assert client.get(f"/api/events/{ev.id}/digital-badge-fields").json()["selected"] is None
    details = [r.detail for r in db.query(AuditAction).filter_by(entity="event_digital_badge_enabled").order_by(AuditAction.id)]
    assert details == ["True -> False", "False -> True"]


def test_the_digital_badge_data_is_never_cached(client, factory, db):
    from tests.test_digital_badge_fields import _setup
    _ev, token = _setup(client, factory, db)
    r = client.get(f"/b/{token}/data")
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
