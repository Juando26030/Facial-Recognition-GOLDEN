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

from tests.test_digital_badge import _register, _setup  # noqa: E402

# ------------------------------- IVA en el campo de pago -------------------------------
def test_tax_option_adds_19_percent_or_only_states_it(client, factory, keys):
    ev, form, _ = _disc_form(client, factory, [], amount=5000)
    login(client, "coord1")
    for mode, expected in (("add", 5950), ("none", 5000), ("", 5000)):
        pay = _pay(amount=5000, tax=mode)
        r = _put(client, ev, form, design=_design(_basic_fields() + [pay]))
        assert r.status_code == 200 and r.json()["design"]["fields"]["pago"]["pay"]["tax"] == mode
        q = _q(client, ev, form)
        assert q["amount"] == expected, mode
    pay = _pay(amount=5000, tax="add", companions_charge=True, discounts=[{"label": "10", "kind": "percent", "value": 10, "when": []}])
    _put(client, ev, form, design=_design(_basic_fields() + [dict(COMP), pay]))
    q = _q(client, ev, form, values={"acomp": _people(2)})
    assert (q["unit"], q["subtotal"], q["tax"], q["amount"]) == (4500, 13500, 2565, 16065)         # descuento por persona, × 3 personas, y el IVA al final
    assert q["applied"][-1] == {"label": "IVA 19%", "kind": "tax", "effect": "+$2.565"}
    assert _put(client, ev, form, design=_design(_basic_fields() + [_pay(amount=5000, tax="raro")])).json()["design"]["fields"]["pago"]["pay"]["tax"] == ""


# ------------------------------- correo de la escarapela virtual -------------------------------
def test_email_sanitizer_keeps_formatting_and_drops_anything_dangerous():
    from app import email_template as et
    dirty = ('<p style="color:red;background:url(http://x)" onclick="x()">Hola <b>{nombre}</b></p><script>alert(1)</script>'
             '<a href="javascript:alert(1)">malo</a><a href="https://ok.com/x">bueno</a><img src="https://ok.com/i.png" onerror="x()"><img src="javascript:1"><iframe src="x"></iframe>')
    clean = et.sanitize(dirty)
    assert "script" not in clean and "onclick" not in clean and "onerror" not in clean and "javascript" not in clean and "iframe" not in clean and "url(" not in clean
    assert 'style="color:red"' in clean and "<b>{nombre}</b>" in clean and 'href="https://ok.com/x"' in clean and 'src="https://ok.com/i.png"' in clean
    assert et.sanitize("<p>sin cerrar <b>negrita") == "<p>sin cerrar <b>negrita</b></p>"


def test_email_render_replaces_variables_and_escapes_the_values(factory):
    from types import SimpleNamespace
    from app import email_template as et
    ev = SimpleNamespace(name="Feria <X>", start_date=None, location="Sede", city="Bogotá", digital_email_subject="Hola {nombre} - {evento}",
                         digital_email_body='<p>{nombre_completo}</p><a href="{enlace}">entra</a> {boton}')
    subject, html_body, text = et.render(ev, "Ana", "<b>Mora</b>", "https://x.com/b/T")
    assert subject == "Hola Ana - Feria <X>"
    assert "&lt;b&gt;Mora&lt;/b&gt;" in html_body and "<b>Mora</b>" not in html_body and 'href="https://x.com/b/T"' in html_body and "Abrir mi escarapela" in html_body
    assert "https://x.com/b/T" in text


def test_badge_email_link_is_absolute_and_uses_the_events_own_template(client, factory, outbox, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    ev = _setup(client, factory, role="coordinador")
    _register(client, ev, "1001", send="true")
    import re
    assert re.search(r"https?://\S+/b/\w+", outbox[0]["body"]) and 'href="http' in outbox[0]["html"]           # nunca «/b/…» a secas (no sirve en un correo)
    r = client.put(f"/api/events/{ev.id}/digital-email", json={"subject": "Tu pase, {nombre}", "body": "<p>Entra: {boton}</p>"})
    assert r.status_code == 200 and client.get(f"/api/events/{ev.id}/digital-email").json()["custom"] is True
    outbox.clear()
    _register(client, ev, "1002", send="true")
    assert outbox[0]["subject"] == "Tu pase, Ana" and "Entra:" in outbox[0]["body"]


def test_email_template_editing_rules(client, factory, outbox):
    ev = _setup(client, factory, role="coordinador")
    url = f"/api/events/{ev.id}/digital-email"
    assert client.get(url).json()["custom"] is False and "{boton}" in client.get(url).json()["body"]
    assert client.put(url, json={"subject": "", "body": "<p>{boton}</p>"}).status_code == 400              # sin asunto
    assert client.put(url, json={"subject": "Hola", "body": "<p>sin enlace</p>"}).status_code == 400        # sin el enlace a la escarapela
    assert client.put(url, json={"subject": "Hola", "body": "<p>{boton}</p><script>x</script>"}).status_code == 200
    assert "script" not in client.get(url).json()["body"]
    pv = client.post(f"{url}/preview", json={"subject": "Hola {nombre}", "body": "<p>{enlace}</p>"}).json()
    assert pv["subject"] == "Hola María" and "/b/EJEMPLO" in pv["html"]
    assert client.post(f"{url}/test", json={"to": "no-es-correo", "body": "<p>{boton}</p>", "subject": "x"}).status_code == 400
    assert client.put(url, json={"reset": True}).json()["custom"] is False


def test_email_images_are_public_but_only_real_unguessable_images(client, factory, tmp_path, monkeypatch):
    import io
    from PIL import Image
    ev = _setup(client, factory, role="coordinador")
    buf = io.BytesIO(); Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    r = client.post(f"/api/events/{ev.id}/digital-email/upload-image", files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    path = "/" + r.json()["url"].split("/", 3)[3]
    bad = client.post(f"/api/events/{ev.id}/digital-email/upload-image", files={"file": ("x.png", b"no soy imagen", "image/png")})
    assert bad.status_code == 400
    client.post("/logout")
    assert client.get(path).status_code == 200                                                            # el lector de correo no tiene sesión
    assert client.get(path.replace(".png", "x.png")).status_code == 404 and client.get(f"/api/email-assets/{ev.tenant_id}/../.env").status_code == 404


# ------------------------------- validación de tipo de datos y documentos de identidad -------------------------------
def test_id_documents_are_validated_by_type_including_check_digits():
    from app import formlib as fl
    good = [("CC", "1.020.304.050"), ("CE", "1234567"), ("TI", "1020304050"), ("PPT", "1234567"), ("NIT", "899999068-1"), ("NIT", "900.123.456"), ("PA", "ab 123456"),
            ("RUT", "12.345.678-5"), ("RUT", "123456785"), ("CPF", "529.982.247-25"), ("NIE", "X1234567L"), ("CI_VE", "V-12345678"), ("CURP", "GOMC800101HDFRRL09"), ("OTRO", "AB-1234")]
    bad = [("CC", "12ab"), ("CC", "12345"), ("CC", "12345678901"), ("NIT", "899999068-2"), ("PA", "12"), ("RUT", "12345678-4"), ("CPF", "111.111.111-11"), ("CPF", "529.982.247-24"),
           ("NIE", "X1234567A"), ("CI_VE", "12345678"), ("XX", "123")]
    assert [c for c, v in good if not fl.validate_id_doc(c, v)[0]] == []
    assert [c for c, v in bad if fl.validate_id_doc(c, v)[0]] == []
    assert fl.validate_id_doc("CC", "1.020.304.050")[1] == "1020304050" and fl.validate_id_doc("PA", "ab 123456")[1] == "AB123456" and fl.validate_id_doc("RUT", "123456785")[1] == "12345678-5"
    assert len(fl.id_docs_public()) >= 15 and all("check" not in d for d in fl.id_docs_public())


def test_numeric_and_phone_fields_reject_letters_on_the_server_too():
    from app import formlib as fl
    design = {"theme": {}, "rows": [], "fields": {"n": {"id": "n", "type": "number", "label": "Edad"}, "t": {"id": "t", "type": "phone", "label": "Tel"}}}
    design = fl.sanitize_design(design, set())
    for raw in ("abc", "12a", "inf", "nan", "1e5", "1,2,3", "--4"):
        assert "n" in fl.validate_submission(design, {"n": raw, "t": "3001234567"}, {})[1], raw
    assert fl.validate_submission(design, {"n": "12,5", "t": "+57 300 123 4567"}, {})[1] == {}
    assert "t" in fl.validate_submission(design, {"n": "1", "t": "abc123456"}, {})[1]


def test_a_form_id_field_can_offer_several_document_types_and_validates_the_chosen_one(client, factory):
    if not getattr(factory, "_coord", None):
        factory._coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    form = _create(client, ev)
    fields = _basic_fields()
    fields[0] = {**fields[0], "doc_types": ["CC", "CE", "PA", "NIT", "XX"]}
    r = _put(client, ev, form, design=_design(fields))
    assert r.status_code == 200 and r.json()["design"]["fields"]["cedula"]["doc_types"] == ["CC", "CE", "PA", "NIT"]          # los tipos inventados se descartan
    _open(client, ev, form)
    login(client, "coord1")
    r = client.get("/api/form-id-docs")
    assert r.status_code == 200 and r.json()[0]["code"] == "CC", r.text
    client.post("/logout")
    assert client.get(f"{_url(ev, form)}/state").json()["id_docs"][0]["pattern"]
    base = {"nombres": "Ana", "apellidos": "Mora", "correo": "ana@example.com"}
    r = _submit(client, ev, form, {**base, "cedula": "AB123", "cedula__tipo": "CC"}, sid="a")
    assert r.status_code == 422 and "Cédula de ciudadanía" in r.json()["errors"]["cedula"]                                        # letras en una cédula
    assert _submit(client, ev, form, {**base, "cedula": "1234", "cedula__tipo": "PA"}, sid="b").status_code == 422              # pasaporte muy corto
    assert _submit(client, ev, form, {**base, "cedula": "1234567", "cedula__tipo": "RUT"}, sid="c").status_code == 422           # tipo no permitido en este formulario
    ok = _submit(client, ev, form, {**base, "cedula": "ab 123456", "cedula__tipo": "PA"}, sid="d")
    assert ok.status_code == 200, ok.text
    login(client, "coord1")
    rows = client.get(f"/api/events/{ev.id}/forms/{form['id']}/submissions").json()["rows"]
    assert rows[0]["data"]["cedula"] == "AB123456" and rows[0]["data"]["cedula__tipo"] == "PA"                                    # guarda el número normalizado y el tipo
    assert any(c["label"].endswith("tipo de documento") for c in client.get(f"/api/events/{ev.id}/forms/{form['id']}/submissions").json()["columns"])


# ------------------------------- reglas de visibilidad con varias reglas -------------------------------
def _vis_design(show_if_x, show_if_y=None):
    from app import formlib as fl
    fields = {"cat": {"id": "cat", "type": "select", "label": "Categoría", "options": ["A", "B", "C", "D", "E"]},
              "otro": {"id": "otro", "type": "text_short", "label": "Otro"},
              "x": {"id": "x", "type": "text_short", "label": "X", "show_if": show_if_x}}
    if show_if_y is not None:
        fields["y"] = {"id": "y", "type": "text_short", "label": "Y", "show_if": show_if_y}
    return fl.sanitize_design({"theme": {}, "rows": [], "fields": fields}, set())


def test_visibility_supports_several_rules_all_or_any_and_several_values():
    from app import formlib as fl
    grupo = {"match": "any", "rules": [{"field": "cat", "op": "in", "value": ["A", "B", "C"]}, {"field": "otro", "op": "filled"}]}
    d = _vis_design(grupo, {"field": "cat", "op": "in", "value": ["D", "E"]})
    assert fl.visible_ids(d, {"cat": "B"}) >= {"x"} and "y" not in fl.visible_ids(d, {"cat": "B"})          # A, B o C → X; D, E → Y
    assert "x" not in fl.visible_ids(d, {"cat": "D"}) and "y" in fl.visible_ids(d, {"cat": "E"})
    assert "x" in fl.visible_ids(d, {"cat": "D", "otro": "hola"})                                            # «alguna»: la segunda regla también basta
    todas = _vis_design({"match": "all", "rules": [{"field": "cat", "op": "in", "value": ["A", "B"]}, {"field": "otro", "op": "filled"}]})
    assert "x" not in fl.visible_ids(todas, {"cat": "A"}) and "x" in fl.visible_ids(todas, {"cat": "A", "otro": "hola"})
    assert "x" not in fl.visible_ids(todas, {"cat": "C", "otro": "hola"})


def test_a_one_rule_group_collapses_and_bad_groups_are_rejected():
    import pytest
    d = _vis_design({"match": "any", "rules": [{"field": "cat", "op": "equals", "value": "A"}]})
    assert d["fields"]["x"]["show_if"] == {"field": "cat", "op": "equals", "value": "A"}                     # una sola regla queda como siempre (compatible)
    assert _vis_design({"match": "any", "rules": []})["fields"]["x"].get("show_if") is None
    with pytest.raises(ValueError):
        _vis_design({"match": "all", "rules": [{"field": "cat", "op": "equals", "value": "A"}, {"field": "nope", "op": "filled"}]})
    with pytest.raises(ValueError):                                                                           # x depende de y y y de x, ahora también dentro de un grupo
        _vis_design({"match": "all", "rules": [{"field": "y", "op": "filled"}, {"field": "cat", "op": "filled"}]}, {"field": "x", "op": "filled"})


# ------------------------------- precios: gana la regla más específica -------------------------------
def test_the_most_specific_price_rule_wins_even_if_a_broader_one_is_listed_first(client, factory, keys):
    cat = {"id": "cat", "type": "select", "label": "Categoría", "options": ["X", "Y", "Z"]}
    extra = {"id": "extra", "type": "text_short", "label": "Extra"}
    ev, form, _ = _disc_form(client, factory, [], extra=[cat, extra], amount=50000, rules=[
        {"label": "Cat X", "amount": 100000, "when": [{"field": "cat", "op": "equals", "value": "X"}]},                              # la general va primero
        {"label": "Cat X + Extra", "amount": 150000, "when": [{"field": "cat", "op": "equals", "value": "X"}, {"field": "extra", "op": "filled"}]},
        {"label": "Cat Y o Z", "amount": 80000, "when": [{"field": "cat", "op": "in", "value": ["Y", "Z"]}]}])
    assert _q(client, ev, form, values={"cat": "X"})["amount"] == 100000                                                          # solo la categoría
    assert _q(client, ev, form, values={"cat": "X", "extra": "algo"})["amount"] == 150000                                         # categoría + respondió: la más específica
    assert _q(client, ev, form, values={"cat": "Z"})["amount"] == 80000 and _q(client, ev, form, values={"cat": "Y", "extra": "a"})["amount"] == 80000
    assert _q(client, ev, form)["amount"] == 50000                                                                                # ninguna: monto base
    r = _submit(client, ev, form, {**_who(1), "cat": "X", "extra": "hola"}, sid="a")
    assert r.json()["payment"]["amount_in_cents"] == 15000000                                                                     # y el servidor cobra lo mismo


def test_an_unconditional_rule_never_hides_a_more_specific_one_and_a_link_wins_ties(client, factory, keys):
    cat = {"id": "cat", "type": "select", "label": "Categoría", "options": ["X", "Y"]}
    ev, form, saved = _disc_form(client, factory, [], extra=[cat], amount=50000, rules=[
        {"label": "Para todos", "amount": 70000, "when": []},
        {"label": "Cat X", "amount": 100000, "when": [{"field": "cat", "op": "equals", "value": "X"}]},
        {"label": "Enlace prensa", "amount": 20000, "how": "link", "when": []}])
    assert _q(client, ev, form, values={"cat": "Y"})["amount"] == 70000 and _q(client, ev, form, values={"cat": "X"})["amount"] == 100000
    key = saved["rules"][2]["link_key"]
    assert _q(client, ev, form, values={"cat": "X"}, d=key)["amount"] == 20000                                                   # el enlace gana el empate (1 condición cada uno)


# ------------------------------- cupo por categoría -------------------------------
def _quota_form(client, factory, limits, capacity=None):
    if not getattr(factory, "_coord", None):
        factory._coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    form = _create(client, ev)
    cat = {"id": "cat", "type": "select", "label": "Categoría", "options": ["VIP", "General", "Estudiante"]}
    r = _put(client, ev, form, design=_design(_basic_fields() + [cat]), settings={"quotas": {"field": "cat", "limits": limits}})
    assert r.status_code == 200, r.text
    if capacity:
        r = _status(client, ev, form, capacity=capacity)
        assert r.status_code == 200, r.text
    _open(client, ev, form)
    client.post("/logout")
    return ev, form


def test_category_quota_blocks_a_full_category_but_not_the_others(client, factory):
    ev, form = _quota_form(client, factory, {"VIP": 2, "Estudiante": 1, "Basura": "x", "General": 0})
    st = client.get(f"{_url(ev, form)}/state").json()
    assert st["quota_left"] == {"cat": {"VIP": 2, "Estudiante": 1}}                                   # lo inválido/0 se descarta; General queda sin límite
    assert _submit(client, ev, form, {**_who(1), "cat": "Estudiante"}, sid="a").status_code == 200
    r = _submit(client, ev, form, {**_who(2), "cat": "Estudiante"}, sid="b")
    assert r.status_code == 409 and r.json()["stage"] == "quota" and "Estudiante" in r.json()["detail"]
    assert _submit(client, ev, form, {**_who(3), "cat": "VIP"}, sid="c").status_code == 200           # otra categoría sigue abierta
    assert _submit(client, ev, form, {**_who(4), "cat": "General"}, sid="d").status_code == 200       # sin límite
    assert client.get(f"{_url(ev, form)}/state").json()["quota_left"] == {"cat": {"VIP": 1, "Estudiante": 0}}


def test_category_quota_does_not_count_tests_and_frees_up_when_a_registration_is_cancelled(client, factory):
    ev, form = _quota_form(client, factory, {"VIP": 1})
    login(client, "coord1")
    _status(client, ev, form, manual_status="pruebas")
    key = client.get(f"/api/events/{ev.id}/forms/{form['id']}").json()["test_key"]
    client.post("/logout")
    for n in (1, 2):
        assert _submit(client, ev, form, {**_who(n), "cat": "VIP"}, key=key, sid=f"t{n}").status_code == 200          # las pruebas ni cuentan ni se bloquean
    login(client, "coord1")
    _status(client, ev, form, manual_status="activo")
    used = client.get(f"/api/events/{ev.id}/forms/{form['id']}").json()
    assert used["quota_used"] == {}                                                                              # sin inscripciones reales
    client.post("/logout")
    assert _submit(client, ev, form, {**_who(3), "cat": "VIP"}, sid="a").status_code == 200
    assert _submit(client, ev, form, {**_who(4), "cat": "VIP"}, sid="b").status_code == 409


def test_category_quota_and_total_capacity_apply_together(client, factory):
    ev, form = _quota_form(client, factory, {"VIP": 5}, capacity=1)
    assert _submit(client, ev, form, {**_who(1), "cat": "General"}, sid="a").status_code == 200
    r = _submit(client, ev, form, {**_who(2), "cat": "VIP"}, sid="b")                                             # VIP tiene cupo, pero el total ya se llenó
    assert r.status_code == 409


# ------------------------------- tamaño de logos e imágenes -------------------------------
def test_form_logo_and_image_sizes_are_sanitized():
    from app import formlib as fl
    d = fl.sanitize_design({"theme": {"logo": "a.png", "logo_width": "60", "logo_full": 1},
                            "fields": {"i": {"id": "i", "type": "image", "src": "b.png", "width": 45}}, "rows": []}, set())
    assert (d["theme"]["logo_width"], d["theme"]["logo_full"], d["fields"]["i"]["width"]) == (60, True, 45)
    d = fl.sanitize_design({"theme": {"logo_width": 500}, "fields": {"i": {"id": "i", "type": "image", "width": "abc"}}, "rows": []}, set())
    assert (d["theme"]["logo_width"], d["theme"]["logo_full"], d["fields"]["i"]["width"]) == (0, False, 100)          # fuera de rango: automático / 100 %


def test_event_logo_height_and_banner_mode_reach_the_event_pages(client, factory, tmp_path):
    ev = factory.event("en_proceso")
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.put(f"/api/events/{ev.id}/logo", json={"height": 20}).status_code == 200                           # se limita a 30–80
    assert client.put(f"/api/events/{ev.id}/logo", json={"fit": "raro"}).status_code == 400
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (600, 100), "blue").save(buf, "PNG")
    assert client.post(f"/api/events/{ev.id}/logo/upload", files={"file": ("banner.png", buf.getvalue(), "image/png")}).status_code == 200
    r = client.put(f"/api/events/{ev.id}/logo", json={"height": 200, "fit": "banner"}).json()
    assert (r["logo_height"], r["logo_fit"]) == (80, "banner")
    page = client.get(f"/kiosk/{ev.id}").text
    assert 'style="height:80px; width:100%; object-fit:cover;" data-banner="1"' in page
    client.put(f"/api/events/{ev.id}/logo", json={"height": 40, "fit": "logo"})
    assert 'style="height:40px;"' in client.get(f"/kiosk/{ev.id}").text
    client.put(f"/api/events/{ev.id}/logo", json={"mode": "default"})
    assert "height:40px" not in client.get(f"/kiosk/{ev.id}").text                                                   # el logo de Golden no se toca
