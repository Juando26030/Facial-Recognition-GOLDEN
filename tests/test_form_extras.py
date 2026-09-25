"""Formularios (2026-09-25): escarapela virtual al inscribirse, acompañantes que pagan, y descuentos por link / categoría / código."""
import json

import pytest

from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _open, _put, _status, _submit, _url, _person_values  # noqa: F401


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _staff(client):
    login(client, "coord1")


# ------------------------------- escarapela virtual al inscribirse -------------------------------
def _badge_form(client, factory, feed="realtime", send=True, module=True):
    if not getattr(factory, "_coord", None):
        factory._coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", digital_badge_enabled=module)
    login(client, "coord1")
    form = _create(client, ev)
    _put(client, ev, form, settings={"feed": feed, "send_digital_badge": send})
    _open(client, ev, form)
    return ev, form


def test_registration_sends_the_virtual_badge_when_it_enters_the_event_base(client, factory, outbox, db):
    from app.models import EventAttendee
    ev, form = _badge_form(client, factory)
    assert _submit(client, ev, form, _person_values()).status_code == 200
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").first()
    assert att.digital_contact == "ana@example.com" and att.digital_sent_at is not None and att.digital_token
    assert [m["to"] for m in outbox] == ["ana@example.com"] and "/b/" in outbox[0]["body"]
    st = client.get(f"{_url(ev, form)}/state").json()
    assert st["badge_email_field"] == "correo"                              # el correo del formulario lleva la aclaración


def test_no_badge_when_off_module_disabled_test_mode_or_not_yet_in_the_base(client, factory, outbox, db):
    ev, form = _badge_form(client, factory, send=False)
    _submit(client, ev, form, _person_values())
    assert outbox == [] and client.get(f"{_url(ev, form)}/state").json()["badge_email_field"] is None
    ev2, form2 = _badge_form(client, factory, module=False)               # el evento no tiene el módulo activado
    _submit(client, ev2, form2, _person_values())
    assert outbox == [] and client.get(f"{_url(ev2, form2)}/state").json()["badge_email_field"] is None
    ev3, form3 = _badge_form(client, factory, feed="manual")             # modo manual: todavía no entra a la base, no se envía
    _submit(client, ev3, form3, _person_values())
    assert outbox == []
    _staff(client)                                                       # «Cargar a la base ahora» sí la envía
    r = client.post(f"/api/events/{ev3.id}/forms/{form3['id']}/feed-now").json()
    assert r["fed"] == 1 and [m["to"] for m in outbox] == ["ana@example.com"]


def test_the_badge_is_sent_once_and_never_for_test_submissions(client, factory, outbox):
    ev, form = _badge_form(client, factory)
    _submit(client, ev, form, _person_values())
    _staff(client)
    client.post(f"/api/events/{ev.id}/forms/{form['id']}/feed-now")
    assert len(outbox) == 1                                              # ya estaba cargada: no se reenvía
    ev2, form2 = _badge_form(client, factory)
    _staff(client)
    _status(client, ev2, form2, manual_status="pruebas")
    key = client.get(f"/api/events/{ev2.id}/forms/{form2['id']}").json()["test_key"]
    client.post("/logout")
    outbox.clear()
    assert _submit(client, ev2, form2, _person_values(), key=key).status_code == 200
    assert outbox == []                                                  # las de prueba nunca salen a nadie


# ------------------------------- acompañantes que pagan -------------------------------
from app import formlib  # noqa: E402
from tests.test_form_payments import PROD, SANDBOX, _pay  # noqa: E402

COMP = {"id": "acomp", "type": "companions", "label": "Acompañantes", "max": 5, "min": 0,
        "person_fields": [{"id": "nombre", "label": "Nombre completo", "type": "text_short", "required": True}, {"id": "correo", "label": "Correo", "type": "email", "required": False}]}


@pytest.fixture()
def keys(monkeypatch):
    for k, v in {**PROD, **SANDBOX}.items():
        monkeypatch.setenv(k, v)


def _comp_form(client, factory, charge=True, amount=5000, comp=None, **pay):
    if not getattr(factory, "_coord", None):
        factory._coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    form = _create(client, ev)
    fields = _basic_fields() + [dict(comp or COMP), _pay(amount=amount, companions_charge=charge, **pay)]
    r = _put(client, ev, form, design=_design(fields))
    assert r.status_code == 200, r.text
    _open(client, ev, form)
    client.post("/logout")
    return ev, form


def _people(n):
    return [{"nombre": f"Persona {i}", "correo": f"p{i}@example.com"} for i in range(1, n + 1)]


def test_companions_field_is_sanitized_and_needs_to_exist_to_charge_for_them():
    d = {"theme": {}, "rows": [], "fields": {"a": {"id": "a", "type": "companions", "label": "X", "max": 99, "person_fields": []}}}
    f = formlib.sanitize_design(d, set())["fields"]["a"]
    assert f["max"] == 20 and f["person_fields"][0]["type"] == "text_short"            # tope y un dato por defecto
    d = {"theme": {}, "rows": [], "fields": {"a": {"id": "a", "type": "companions", "person_fields": [{"id": "n", "label": "N"}, {"id": "n", "label": "M"}]}}}
    with pytest.raises(ValueError):                                                    # ids repetidos
        formlib.sanitize_design(d, set())
    d = {"theme": {}, "rows": [], "fields": {"p": {"id": "p", "type": "payment", "pay": {"amount": 5000, "companions_charge": True}}}}
    with pytest.raises(ValueError):                                                    # cobrar por acompañantes sin el campo
        formlib.sanitize_design(d, set())


def test_price_is_per_person_including_the_registrant(client, factory, keys):
    ev, form = _comp_form(client, factory)
    url = f"{_url(ev, form)}/quote"
    assert client.post(url, json={"values": {"acomp": _people(5)}}).json()["amount"] == 30000            # 5 acompañantes + quien se inscribe = 6 × 5.000
    q = client.post(url, json={"values": {"acomp": _people(2)}}).json()
    assert (q["amount"], q["unit"], q["people"]) == (15000, 5000, 3) and q["applied"][-1]["kind"] == "people"
    assert client.post(url, json={"values": {}}).json()["amount"] == 5000                                # sin acompañantes: solo quien se inscribe
    ev2, form2 = _comp_form(client, factory, charge=False)                                               # sin la casilla de cobro no se multiplica
    assert client.post(f"{_url(ev2, form2)}/quote", json={"values": {"acomp": _people(5)}}).json()["amount"] == 5000


def test_discounts_apply_per_person_before_multiplying(client, factory, keys):
    ev, form = _comp_form(client, factory, discounts=[{"label": "Early", "kind": "percent", "value": 20, "when": []}])
    q = client.post(f"{_url(ev, form)}/quote", json={"values": {"acomp": _people(3)}}).json()
    assert (q["unit"], q["amount"]) == (4000, 16000)


def test_submit_charges_everyone_and_stores_the_companions(client, factory, keys):
    ev, form = _comp_form(client, factory)
    r = _submit(client, ev, form, {**_person_values(), "acomp": _people(5)})
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["amount_in_cents"] == 3000000
    from app.models import FormPayment  # noqa: F401
    login(client, "coord1")
    from tests.test_form_payments import _event_for
    client.post("/logout")
    assert client.post("/webhooks/wompi", json=_event_for("prod", r.json()["payment"]["reference"], 3000000, "APPROVED", txn="TC-1")).json() == {"ok": True}
    login(client, "coord1")
    rows = client.get(f"/api/events/{ev.id}/forms/{form['id']}/submissions").json()
    row = rows["rows"][0]
    assert row["data"]["acomp"].startswith("5: Persona 1") and row["paid"] == 30000            # se ven en las respuestas
    kpis = {k["label"]: k["value"] for k in client.get(f"/api/events/{ev.id}/forms/{form['id']}/analytics").json()["kpis"]}
    assert kpis.get("Acompañantes") == 5


def test_companion_validation_max_required_and_hidden_field(client, factory, keys):
    ev, form = _comp_form(client, factory)
    r = _submit(client, ev, form, {**_person_values(), "acomp": _people(6)})
    assert r.status_code == 422                                                                          # más del máximo
    r = _submit(client, ev, form, {**_person_values(), "acomp": [{"nombre": ""}]}, sid="b")
    assert r.status_code == 422 and "Acompañante 1" in r.json()["errors"]["acomp"]                             # falta un dato obligatorio
    r = _submit(client, ev, form, {**_person_values(), "acomp": [{"nombre": "X", "correo": "mal"}]}, sid="c")
    assert r.status_code == 422                                                                          # correo mal escrito


def test_a_group_bigger_than_wompis_limit_is_refused_instead_of_failing_at_the_widget(client, factory, keys):
    ev, form = _comp_form(client, factory, amount=900000, comp={**COMP, "max": 20})
    r = _submit(client, ev, form, {**_person_values(), "acomp": _people(20)})                             # 21 × 900.000 > 10.000.000
    assert r.status_code == 422 and "máximo" in r.json()["detail"]
