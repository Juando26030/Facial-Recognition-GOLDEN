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


# ------------------------------- descuentos: por variable, por enlace propio y por código -------------------------------
TIPO_ = {"id": "tipo", "type": "select", "label": "Tipo", "options": ["General", "Estudiante"]}


def _who(n):
    return {"cedula": f"20{n:02d}", "nombres": f"Persona{n}", "apellidos": "Prueba", "correo": f"p{n}@example.com"}


def _disc_form(client, factory, discounts, rules=None, extra=(), amount=100000):
    if not getattr(factory, "_coord", None):
        factory._coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    form = _create(client, ev)
    pay = _pay(amount=amount, discounts=discounts, **({"mode": "rules", "rules": rules} if rules else {}))
    r = _put(client, ev, form, design=_design(_basic_fields() + list(extra) + [pay]))
    assert r.status_code == 200, r.text
    _open(client, ev, form)
    saved = r.json()["design"]["fields"]["pago"]["pay"]
    client.post("/logout")
    return ev, form, saved


def _codes(client, ev, form, **body):
    login(client, "coord1")
    r = client.post(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes", json=body)
    client.post("/logout")
    return r


def _q(client, ev, form, **body):
    return client.post(f"{_url(ev, form)}/quote", json={"values": {}, **body}).json()


def test_price_items_get_ids_how_and_link_keys_and_the_public_never_sees_the_keys(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [
        {"label": "Solo enlace", "kind": "percent", "value": 10, "how": "link", "when": []},
        {"label": "Con código", "kind": "percent", "value": 20, "how": "code", "when": []},
        {"label": "Por respuesta", "kind": "percent", "value": 5, "how": "raro", "when": []}])
    d = saved["discounts"]
    assert [x["how"] for x in d] == ["link", "code", "category"] and len({x["id"] for x in d}) == 3 and len(d[0]["link_key"]) == 10 and "link_key" not in d[1]
    state = client.get(f"{_url(ev, form)}/state").json()
    assert d[0]["link_key"] not in json.dumps(state["design"]) and state["design"]["fields"]["pago"]["pay"]["codes"] is True
    login(client, "coord1")                                                                # guardar de nuevo conserva la clave del enlace (no la cambia)
    again = _put(client, ev, form, design=_design(_basic_fields() + [{"id": "pago", "type": "payment", "label": "P", "pay": saved}])).json()
    assert again["design"]["fields"]["pago"]["pay"]["discounts"][0]["link_key"] == d[0]["link_key"]


def test_a_discount_link_only_applies_to_people_who_come_through_it(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [{"label": "Prensa", "kind": "percent", "value": 50, "how": "link", "when": []}],
                                 rules=[{"label": "VIP", "amount": 300000, "how": "link", "when": []}])
    key_disc = saved["discounts"][0]["link_key"]
    key_rule = saved["rules"][0]["link_key"]
    assert _q(client, ev, form)["amount"] == 100000                                          # entrada normal
    assert _q(client, ev, form, d=key_disc)["amount"] == 50000                                # enlace del descuento
    assert _q(client, ev, form, d=key_rule)["amount"] == 300000                               # enlace de otro precio
    assert _q(client, ev, form, d="clave-inventada")["amount"] == 100000                      # una clave falsa no hace nada
    r = _submit(client, ev, form, _person_values(), d=key_disc)
    assert r.json()["payment"]["amount_in_cents"] == 5000000                                 # el servidor lo aplica al enviar


def test_shared_code_stops_working_after_its_uses_run_out(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [{"label": "Código", "kind": "percent", "value": 20, "how": "code", "when": []}])
    did = saved["discounts"][0]["id"]
    assert _codes(client, ev, form, discount_id=did, mode="shared", code="feria 2026", max_uses=2).status_code == 200      # se normaliza: FERIA2026
    assert _q(client, ev, form, code="feria2026")["amount"] == 80000
    assert _q(client, ev, form, code="feria2026")["code"] == {"status": "ok", "message": "Código aplicado"}
    assert _q(client, ev, form, code="NOEXISTE")["code"]["status"] == "invalid" and _q(client, ev, form, code="NOEXISTE")["amount"] == 100000
    for n in (1, 2):
        assert _submit(client, ev, form, _who(n), code="FERIA2026", sid=f"s{n}").json()["payment"]["amount_in_cents"] == 8000000
    assert _q(client, ev, form, code="FERIA2026")["code"]["status"] == "exhausted"
    r = _submit(client, ev, form, _who(3), code="FERIA2026", sid="s3")
    assert r.status_code == 422 and r.json()["code_error"] and "agotó" in r.json()["detail"]
    login(client, "coord1")
    row = client.get(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes").json()[0]
    assert (row["max_uses"], row["used"], row["left"]) == (2, 2, 0)
    assert client.delete(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes/{row['id']}").status_code == 409     # ya se usó


def test_unique_codes_are_single_use_and_come_out_in_an_excel(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [{"label": "Cortesía", "kind": "percent", "value": 100, "how": "code", "when": []}])
    r = _codes(client, ev, form, discount_id=saved["discounts"][0]["id"], mode="unique", count=3, prefix="vip")
    assert r.status_code == 200 and r.json()["created"] == 3
    codes = r.json()["codes"]
    assert len(set(codes)) == 3 and all(c.startswith("VIP") and len(c) == 8 for c in codes)
    free = _submit(client, ev, form, _who(1), code=codes[0], sid="a")                        # 100 %: no hay pago y se confirma directo
    assert free.status_code == 200 and "payment_required" not in free.json()
    again = _submit(client, ev, form, _who(2), code=codes[0], sid="b")                       # el mismo código no sirve dos veces
    assert again.status_code == 422 and "agotó" in again.json()["detail"]
    assert _submit(client, ev, form, _who(3), code=codes[1], sid="c").status_code == 200      # otro código distinto sí
    login(client, "coord1")
    x = client.get(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes/export")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert sorted(r["used"] for r in client.get(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes").json()) == [0, 1, 1]


def test_a_code_also_respects_the_conditions_of_its_discount(client, factory, keys):
    ev, form, saved = _disc_form(client, factory, [
        {"label": "Estudiantes", "kind": "percent", "value": 50, "how": "code", "when": [{"field": "tipo", "op": "equals", "value": "Estudiante"}]}], extra=[TIPO_])
    _codes(client, ev, form, discount_id=saved["discounts"][0]["id"], mode="shared", code="ESTU", max_uses=10)
    assert _q(client, ev, form, code="ESTU", values={"tipo": "General"})["code"]["status"] == "not_applicable"
    assert _q(client, ev, form, code="ESTU", values={"tipo": "Estudiante"})["amount"] == 50000
    r = _submit(client, ev, form, {**_who(1), "tipo": "General"}, code="ESTU", sid="a")       # el código no vale si no cumple las respuestas
    assert r.status_code == 422 and r.json()["code_error"]
    login(client, "coord1")                                                                   # y solo los descuentos «con código» generan códigos
    bad = client.post(f"/api/events/{ev.id}/forms/{form['id']}/discount-codes", json={"discount_id": "nope", "mode": "shared", "max_uses": 1})
    assert bad.status_code == 400


def test_value_suggestions_offer_what_the_base_already_has(client, factory, keys, db):
    from app.models import EventAttendee, User
    ev, form, _ = _disc_form(client, factory, [])
    for i, (ent, cat) in enumerate([("ACME", "Speaker"), ("ACME", "Speaker"), ("Globex", "Visitante")]):
        db.add(User(id=f"90{i}", tenant_id=ev.tenant_id, first_name="N", last_name="A", entity=ent))
        db.flush()
        att = EventAttendee(event_id=ev.id, user_id=f"90{i}", tenant_id=ev.tenant_id)
        att.set_categories([cat])
        db.add(att)
    db.commit()
    login(client, "coord1")
    url = f"/api/events/{ev.id}/forms/{form['id']}/value-suggestions"
    assert client.get(url, params={"key": "entity"}).json() == {"values": ["ACME", "Globex"], "total": 2}          # pocos valores: el editor los ofrece como lista
    assert client.get(url, params={"key": "categories"}).json()["values"] == ["Speaker", "Visitante"]
    assert client.get(url, params={"key": "email"}).json() == {"values": [], "total": 0}                          # lo único por persona no se sugiere
