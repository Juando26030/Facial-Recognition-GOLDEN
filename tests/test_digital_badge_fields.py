"""Escarapela digital: datos visibles elegibles por evento (app/digital_fields.py, /api/events/{id}/digital-badge-fields, /b/<token>/data)."""
import json

from app import digital_badge, digital_fields
from app.models import EventAttendee, User
from tests.conftest import login

from tests.test_digital_fields_pure import LABELS  # noqa: E402


# ---- endpoints ----
def _setup(client, factory, db, **extra):
    admin = factory.staff("admin", "adm-df")
    ev = factory.event("en_proceso", digital_badge_enabled=True, optional_field_labels=json.dumps(LABELS), **extra)
    user = User(id="1001", tenant_id=ev.tenant_id, first_name="Ana", last_name="Mora", role="Ingeniera", entity="ACME", phone="3001234567", email="ana@example.com",
                extra_fields=json.dumps({"opcional_1": "Ninguna", "opcional_2": "M", "secreto": "x"}))
    db.add(user)
    db.flush()
    att = EventAttendee(event_id=ev.id, user_id=user.id, tenant_id=ev.tenant_id)
    db.add(att)
    db.commit()
    token = digital_badge.ensure_token(db, att)
    db.commit()
    login(client, admin.username)
    return ev, token


def _data(client, token):
    return client.get(f"/b/{token}/data").json()


def test_default_null_list_keeps_todays_behaviour(client, factory, db):
    ev, token = _setup(client, factory, db)
    person = _data(client, token)["person"]
    assert "phone" not in person and "email" not in person and "secreto" not in person["extra_fields"]
    assert _data(client, token)["extra_list"] == []
    state = client.get(f"/api/events/{ev.id}/digital-badge-fields").json()
    assert state["selected"] is None and state["enabled"] is True and "Teléfono" in [f["label"] for f in state["fields"]]
    assert "datos personales" in state["warning"]


def test_explicit_list_delivers_exactly_those_fields(client, factory, db):
    ev, token = _setup(client, factory, db)
    r = client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["entity", "opcional_2"]})
    assert r.status_code == 200 and r.json()["selected"] == ["entity", "opcional_2"]
    body = _data(client, token)
    assert body["person"]["entity"] == "ACME" and "role" not in body["person"] and body["person"]["extra_fields"] == {"opcional_2": "M"}
    assert {(x["label"], x["value"]) for x in body["extra_list"]} == {("Entidad", "ACME"), ("Talla", "M")}


def test_phone_and_email_only_when_marked_explicitly(client, factory, db):
    ev, token = _setup(client, factory, db)
    client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["role"]})
    person = _data(client, token)["person"]
    assert "phone" not in person and "email" not in person
    client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["phone", "email"]})
    person = _data(client, token)["person"]
    assert person["phone"] == "3001234567" and person["email"] == "ana@example.com"
    client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": None})          # volver al por defecto
    assert "phone" not in _data(client, token)["person"]


def test_invalid_keys_are_rejected_and_nothing_is_saved(client, factory, db):
    ev, token = _setup(client, factory, db)
    for bad in (["id"], ["role", "cedula"], ["opcional_9"], "role"):
        r = client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": bad})
        assert r.status_code == 400, bad
    db.refresh(ev)
    assert ev.digital_badge_fields is None


def test_the_id_card_number_never_comes_out_as_a_field(client, factory, db):
    ev, token = _setup(client, factory, db)
    client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": digital_fields.allowed_keys(LABELS)})          # todo lo elegible
    body = _data(client, token)
    flat = {k: v for k, v in body["person"].items() if k not in ("id", "extra_fields")}
    assert "1001" not in json.dumps(flat) and "1001" not in json.dumps(body["person"]["extra_fields"]) and "1001" not in json.dumps(body["extra_list"])


def test_choosing_fields_needs_the_module_and_leaves_an_audit_record(client, factory, db):
    from app.models import AuditAction

    ev, _ = _setup(client, factory, db)
    client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["role", "phone"]})
    row = db.query(AuditAction).filter_by(entity="event_digital_badge_fields", entity_id=str(ev.id)).one()
    assert row.detail == "role, phone" and "3001234567" not in (row.detail or "")
    off = factory.event("en_proceso", digital_badge_enabled=False)
    assert client.put(f"/api/events/{off.id}/digital-badge-fields", json={"fields": ["role"]}).status_code == 409


def test_a_digitador_cannot_change_it(client, factory, db):
    ev, _ = _setup(client, factory, db)
    dig = factory.staff("digitador", "9990009")
    factory.authorize(ev, dig)
    client.post("/api/logout")
    login(client, dig.username)
    assert client.put(f"/api/events/{ev.id}/digital-badge-fields", json={"fields": ["role"]}).status_code in (401, 403)
