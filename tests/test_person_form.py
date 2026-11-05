"""Formulario de persona diseñado por el admin (Fase 1A, pieza 5; app/personform.py, app/routers/person_form.py, bandeja `edit_person`).
Interruptor de entorno APAGADO por defecto y por evento; versión del diseño; «Texto al escribir» aplicado en el servidor (alta, edición y bandeja); obligatorio escrito en los parámetros del evento;
operaciones de la bandeja con una copia vieja del formulario (se aplican, con avisos, sin perder nada); edición sin red por cédula o por huella. Sin columna nueva ni migración."""
import json
from datetime import datetime

import pytest

from app import personform
from app.models import AccessLog, AppSetting, EventFieldConfig, User
from tests.conftest import login

CFG = [{"key": k, "label": k, "field_type": "text_short", "required": r, "options": []}
       for k, r in (("id", False), ("first_name", False), ("last_name", False), ("role", True), ("entity", False), ("phone", False), ("email", False))]
CFG += [{"key": f"opcional_{i}", "label": f"Campo {i}", "field_type": "text_short", "required": False, "options": []} for i in range(1, 15)]


@pytest.fixture
def pf_on(monkeypatch):
    monkeypatch.setenv("PERSON_FORM_ENABLED", "1")


def _admin(client, factory):
    factory.staff("super_admin", "boss")
    login(client, "boss")


def _event_with_labels(factory, db, **extra):
    ev = factory.event("en_proceso", **extra)
    ev.set_optional_labels({"opcional_1": "Ciudad", "opcional_2": "Talla"})
    db.commit()
    return ev


def _design(ev, client, **body):
    base = {"enabled": True, "sheets": [{"id": "datos", "title": "Datos", "open": True}], "rows": [], "fields": {}}
    base.update(body)
    return client.put(f"/api/events/{ev.id}/person-form", json=base)


# ------------------------------------------------------------------------------------------------------------------ lógica pura
def test_default_design_has_about_ten_fields_in_view_and_the_rest_in_collapsed_groups():
    d = personform.default_design(CFG)
    first = [k for r in d["rows"] if r["sheet"] == "datos" for k in r["items"]]
    assert first[:3] == ["id", "first_name", "last_name"] and "role" in first, "cédula, nombres, apellidos y los obligatorios del evento, a la vista"
    assert d["sheets"][0]["open"] is True and all(s["open"] is False for s in d["sheets"][1:])
    placed = [k for r in d["rows"] for k in r["items"]]
    assert sorted(placed) == sorted(c["key"] for c in CFG), "todos los campos del evento (no hay tope) quedan en alguna fila"
    assert all(len(r["items"]) <= 4 for r in d["rows"])


def test_sanitize_rejects_text_case_on_non_text_fields_and_show_if_on_required_ones():
    with pytest.raises(ValueError):
        personform.sanitize({"fields": {"phone": {"text_case": "upper"}}}, CFG)
    with pytest.raises(ValueError):
        personform.sanitize({"fields": {"email": {"text_case": "upper"}}}, CFG)
    with pytest.raises(ValueError, match="obligatorio"):
        personform.sanitize({"fields": {"role": {"show_if": {"field": "entity", "op": "equals", "value": "x"}}}}, CFG)
    ok = personform.sanitize({"fields": {"entity": {"text_case": "upper", "show_if": {"field": "phone", "op": "filled"}}}}, CFG)
    assert ok["fields"]["entity"]["text_case"] == "upper" and ok["fields"]["entity"]["show_if"]["field"] == "phone"
    with pytest.raises(ValueError):          # círculo entre dos condiciones
        personform.sanitize({"fields": {"entity": {"show_if": {"field": "phone", "op": "filled"}}, "phone": {"show_if": {"field": "entity", "op": "filled"}}}}, CFG)


def test_a_group_with_a_required_field_is_always_open_and_unknown_fields_go_to_the_end():
    raw = {"sheets": [{"id": "a", "title": "A", "open": False}, {"id": "b", "title": "B", "open": False}], "rows": [{"sheet": "a", "items": ["role", "borrado"]}], "fields": {}}
    clean = personform.sanitize(raw, CFG)
    assert clean["sheets"][0]["open"] is True, "role es obligatorio: su grupo queda abierto"
    assert clean["rows"][0]["items"] == ["role"] and sorted(k for r in clean["rows"] for k in r["items"]) == sorted(c["key"] for c in CFG)


def test_apply_case_only_touches_text_fields_and_lowercases_the_email():
    eff = personform.effective(None, CFG)
    eff["fields"]["first_name"]["text_case"] = "upper"
    eff["fields"]["opcional_1"]["text_case"] = "lower"
    data = {"first_name": "ana maría", "id": "abc", "phone": "3001", "email": " Ana@X.CO ", "extra_fields": {"opcional_1": "BOGOTÁ", "opcional_2": "Mm"}}
    personform.apply_case(data, eff)
    assert data == {"first_name": "ANA MARÍA", "id": "abc", "phone": "3001", "email": "ana@x.co", "extra_fields": {"opcional_1": "bogotá", "opcional_2": "Mm"}}
    untouched = {"first_name": "ana", "email": "A@B.CO"}
    personform.apply_case(untouched, None)
    assert untouched == {"first_name": "ana", "email": "A@B.CO"}, "sin formulario activo no se toca nada"


def test_stale_detection_uses_version_and_signature():
    eff = personform.effective({"form_version": 3}, CFG)
    assert personform.is_stale(eff, 2) and personform.is_stale(eff, "1") and not personform.is_stale(eff, 3)
    assert not personform.is_stale(eff, None) and not personform.is_stale(eff, 0) and not personform.is_stale(eff, "abc") and not personform.is_stale(eff, 9) and not personform.is_stale(eff, True)
    assert not personform.is_stale(eff, 3, "otra"), "la firma no decide: solo una versión entera menor"


# ------------------------------------------------------------------------------------------------------------------ interruptores
def test_with_the_env_switch_off_everything_is_as_before(client, factory, db):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    assert client.get(f"/api/events/{ev.id}/person-form").json() == {"env_enabled": False, "enabled": False, "definition": None}
    assert _design(ev, client).status_code == 404
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "window.PERSON_FORM = {" not in page and "person-form.js" not in page and "form-render.js" not in page
    r = client.post("/api/register", data={"event_id": ev.id, "id": "5001", "first_name": "ana maria", "email": "A@B.CO"})
    assert r.status_code == 200 and db.query(User).filter_by(id="5001").one().first_name == "ana maria", "sin el interruptor no se cambia ni una letra"


def test_env_on_but_event_off_keeps_the_classic_form(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    body = client.get(f"/api/events/{ev.id}/person-form").json()
    assert body["env_enabled"] is True and body["enabled"] is False and body["definition"]["sheets"], "el diseñador ve el diseño por defecto aunque el evento aún no lo use"
    assert "window.PERSON_FORM = {" not in client.get(f"/kiosk/{ev.id}/registro").text


def test_designer_is_admin_only_and_turning_it_on_injects_the_definition(client, factory, db, pf_on):
    ev = _event_with_labels(factory, db)
    dig = factory.staff("digitador", "dig")
    factory.authorize(ev, dig)
    login(client, "dig")
    assert client.get(f"/api/events/{ev.id}/person-form").status_code == 200, "el personal del evento la lee (la copia sin red)"
    assert _design(ev, client).status_code == 403
    _admin(client, factory)          # inicia sesión como admin (reemplaza la cookie del digitador)
    r = _design(ev, client, fields={"first_name": {"text_case": "upper"}})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["definition"]["form_version"] == 1
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "window.PERSON_FORM = {" in page and "person-form.js" in page and "form-render.js" in page
    assert page.count("window.regPersonForm = window.PersonForm.mount") == 1


def test_version_goes_up_only_when_the_design_changes_and_required_is_written_to_the_event(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    v1 = _design(ev, client, fields={"opcional_1": {"required": True}}).json()["definition"]
    assert v1["form_version"] == 1 and v1["fields"]["opcional_1"]["required"] is True
    assert db.query(EventFieldConfig).filter_by(event_id=ev.id, field_key="opcional_1").one().required is True, "lo obligatorio vive en los parámetros del evento (una sola fuente)"
    same = _design(ev, client, fields={"opcional_1": {"required": True}}).json()["definition"]
    assert same["form_version"] == 1, "guardar lo mismo no sube la versión"
    v2 = _design(ev, client, fields={"opcional_1": {"required": True}, "first_name": {"text_case": "upper"}}).json()["definition"]
    assert v2["form_version"] == 2
    v3 = _design(ev, client, fields={"opcional_1": {"required": False}}).json()["definition"]
    assert v3["form_version"] == 3 and db.query(EventFieldConfig).filter_by(event_id=ev.id, field_key="opcional_1").one().required is False
    assert db.get(AppSetting, f"person_form:{ev.id}") is not None, "va en app_settings: sin columna nueva"
    assert _design(ev, client, fields={"phone": {"text_case": "upper"}}).status_code == 400
    assert _design(ev, client, fields={"id": {"required": False}, "last_name": {"required": True}}).json()["definition"]["fields"]["id"]["required"] is True


def test_last_name_is_never_required_and_names_do_not_need_to_be_separated(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    d = _design(ev, client, fields={"last_name": {"required": True}}).json()["definition"]
    assert d["fields"]["last_name"]["required"] is False
    r = client.post("/api/register", data={"event_id": ev.id, "id": "5100", "first_name": "Ana María Pérez", "role": "Gerente"})
    assert r.status_code == 200 and db.query(User).filter_by(id="5100").one().last_name == ""


# ------------------------------------------------------------------------------------------------------------------ texto al escribir en el servidor
def test_text_case_is_applied_on_register_and_on_edit(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"first_name": {"text_case": "upper"}, "last_name": {"text_case": "upper"}, "entity": {"text_case": "lower"}, "opcional_1": {"text_case": "upper"}})
    r = client.post("/api/register", data={"event_id": ev.id, "id": "5200", "first_name": "ana maría", "last_name": "pérez", "role": "Gerente", "entity": "ACME SAS",
                                           "phone": "300 abc", "email": "Ana@Mail.CO", "extra_fields": json.dumps({"opcional_1": "bogotá", "opcional_2": "m"})})
    assert r.status_code == 200, r.text
    u = db.query(User).filter_by(id="5200").one()
    assert (u.first_name, u.last_name, u.entity, u.phone, u.email) == ("ANA MARÍA", "PÉREZ", "acme sas", "300 abc", "ana@mail.co")
    assert u.get_extras() == {"opcional_1": "BOGOTÁ", "opcional_2": "m"}
    r = client.patch(f"/api/users/5200?event_id={ev.id}", json={"first_name": "luis", "entity": "OTRA", "extra_fields": {"opcional_1": "cali"}})
    assert r.status_code == 200, r.text
    db.expire_all()
    u = db.query(User).filter_by(id="5200").one()
    assert (u.first_name, u.entity) == ("LUIS", "otra") and u.get_extras()["opcional_1"] == "CALI"


# ------------------------------------------------------------------------------------------------------------------ bandeja: versión, copia vieja, edición
def _op(op_id, kind="create_person", version=None, sig=None, **fields):
    op = {"op_id": op_id, "type": kind, "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "fields": fields}
    if version is not None:
        op["form_version"] = version
    if sig:
        op["form_sig"] = sig
    return op


def _sync(client, ev, *ops):
    return client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": list(ops)})


def test_outbox_create_with_the_current_version_applies_text_rules_and_reports_the_version(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    d = _design(ev, client, fields={"first_name": {"text_case": "upper"}, "opcional_1": {"text_case": "lower"}, "role": {"required": False}}).json()["definition"]
    r = _sync(client, ev, _op("o1", version=d["form_version"], sig=d["form_sig"], id="6001", first_name="nora sin red", email="N@X.CO", extra_fields={"opcional_1": "CALI"})).json()
    assert r["results"] == [{"op_id": "o1", "result": "ok"}] and r["form_version"] == d["form_version"]
    u = db.query(User).filter_by(id="6001").one()
    assert (u.first_name, u.email, u.get_extras()) == ("NORA SIN RED", "n@x.co", {"opcional_1": "cali"})


def test_outbox_create_with_an_old_version_still_saves_and_warns_about_what_is_new(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"opcional_2": {"required": True}, "first_name": {"text_case": "upper"}})
    _design(ev, client, fields={"opcional_2": {"required": True}, "first_name": {"text_case": "upper"}, "entity": {"text_case": "upper"}})      # versión 2
    old = _op("o2", version=1, id="6100", first_name="vieja copia", role="Jefe", entity="acme", extra_fields={"opcional_2": "M", "opcional_77": "ya no existe"})
    nuevo_obligatorio = _op("o3", version=1, id="6101", first_name="sin talla", role="Jefe")
    r = _sync(client, ev, old, nuevo_obligatorio).json()["results"]
    assert [x["result"] for x in r] == ["ok", "ok"], "con una copia vieja nunca se pierde la alta"
    assert any("opcional_77" in w for w in r[0]["warnings"]) and any("obligatorios" in w for w in r[1]["warnings"])
    u = db.query(User).filter_by(id="6100").one()
    assert (u.first_name, u.entity, u.get_extras()) == ("VIEJA COPIA", "ACME", {"opcional_2": "M"}), "reglas de texto vigentes y campos conocidos; el desconocido se ignoró"
    assert db.query(User).filter_by(id="6101").one() is not None
    # la MISMA falta con la versión vigente sí es un error por ítem (como siempre)
    cur = _sync(client, ev, _op("o4", version=2, sig=client.get(f"/api/events/{ev.id}/person-form").json()["definition"]["form_sig"], id="6102", first_name="x", role="Jefe")).json()["results"][0]
    assert cur["result"] == "error" and "obligatorios" in cur["detail"]


def test_outbox_without_the_feature_is_unchanged_and_ignores_versions(client, factory, db):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    r = _sync(client, ev, _op("o5", version=7, id="6200", first_name="tal cual", email="A@B.CO")).json()
    assert r["results"] == [{"op_id": "o5", "result": "ok"}] and "form_version" not in r
    u = db.query(User).filter_by(id="6200").one()
    assert (u.first_name, u.email) == ("tal cual", "A@B.CO")


def test_edit_person_op_by_cedula_applies_only_what_was_typed_and_is_idempotent(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    d = _design(ev, client, fields={"entity": {"text_case": "upper"}, "role": {"required": False}}).json()["definition"]
    u = factory.person(ev, "6300", "Ana", "Original")
    u.role, u.phone = "Jefe", "3001"
    u.set_extras({"opcional_1": "Cali"})
    db.commit()
    op = _op("e1", "edit_person", version=d["form_version"], sig=d["form_sig"], id="6300", entity="acme", extra_fields={"opcional_2": "L"})
    assert _sync(client, ev, op).json()["results"] == [{"op_id": "e1", "result": "ok"}]
    db.expire_all()
    u = db.query(User).filter_by(id="6300").one()
    assert (u.first_name, u.last_name, u.role, u.phone, u.entity) == ("Ana", "Original", "Jefe", "3001", "ACME"), "lo que va en blanco queda como estaba"
    assert u.get_extras() == {"opcional_1": "Cali", "opcional_2": "L"}
    logs = db.query(AccessLog).filter_by(event_id=ev.id, user_id="6300", client_id="e1").all()
    assert len(logs) == 1 and logs[0].record_type == "Actualizado"
    assert _sync(client, ev, op).json()["results"] == [{"op_id": "e1", "result": "replayed"}]
    assert db.query(AccessLog).filter_by(event_id=ev.id, client_id="e1").count() == 1


def test_edit_person_op_resolves_the_fingerprint_and_reports_unknown_people(client, factory, db, pf_on):
    from app.routers.api import roster_fingerprint, roster_salt

    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"role": {"required": False}})
    factory.person(ev, "6400", "Beto", "Sin Cédula")
    h = roster_fingerprint(roster_salt(ev), "6400")
    r = _sync(client, ev, _op("e2", "edit_person", h=h, phone="3009998888"), _op("e3", "edit_person", id="9999999", phone="1"), _op("e4", "edit_person", h="0" * 16, phone="1")).json()["results"]
    assert [x["result"] for x in r] == ["ok", "error", "error"] and "No se encontró" in r[1]["detail"]
    assert db.query(User).filter_by(id="6400").one().phone == "3009998888"


def test_edit_person_op_validates_email_and_required_but_only_warns_when_the_copy_is_old(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    db.add(EventFieldConfig(event_id=ev.id, field_key="role", required=True, field_type="text_short"))          # el cargo es obligatorio (parámetros del evento)
    db.add(EventFieldConfig(event_id=ev.id, field_key="email", required=False, field_type="email"))
    db.commit()
    d = _design(ev, client).json()["definition"]
    factory.person(ev, "6500", "Carla", "Vacía")
    bad = _sync(client, ev, _op("e5", "edit_person", version=d["form_version"], id="6500", role="Jefe", email="no-es-correo")).json()["results"][0]
    assert bad["result"] == "error" and "Correo" in bad["detail"]
    missing = _sync(client, ev, _op("e6", "edit_person", version=d["form_version"], id="6500", phone="3001")).json()["results"][0]
    assert missing["result"] == "error" and "obligatorios" in missing["detail"], "role sigue vacío"
    old = _sync(client, ev, _op("e7", "edit_person", version=max(d["form_version"] - 1, 1), id="6500", phone="3001")).json()["results"][0]
    assert old["result"] == "ok" and old["warnings"], "copia vieja: se guarda y avisa"
    assert db.query(User).filter_by(id="6500").one().phone == "3001"


def test_outbox_without_form_version_or_with_garbage_is_strict_about_required(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"opcional_2": {"required": True}})
    r = _sync(client, ev, _op("s1", id="6700", first_name="sin version", role="Jefe"), _op("s2", version="x", id="6701", first_name="basura", role="Jefe"), _op("s3", version=0, id="6702", first_name="cero", role="Jefe")).json()["results"]
    assert all(x["result"] == "error" and "obligatorios" in x["detail"] for x in r)
    assert db.query(User).filter(User.id.in_(["6700", "6701", "6702"])).count() == 0


def test_outbox_with_an_old_integer_version_still_saves_with_warnings(client, factory, db, pf_on):
    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"opcional_2": {"required": True}})
    _design(ev, client, fields={"opcional_2": {"required": True}, "entity": {"text_case": "upper"}})
    r = _sync(client, ev, _op("v1", version=1, id="6710", first_name="vieja", role="Jefe")).json()["results"][0]
    assert r["result"] == "ok" and any("obligatorios" in w for w in r["warnings"])
    assert db.query(User).filter_by(id="6710").one() is not None


def test_edit_person_op_rejects_a_person_of_another_event_without_revealing_it(client, factory, db, pf_on):
    from app.routers.api import roster_fingerprint, roster_salt

    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    other = factory.event()
    _design(ev, client, fields={"role": {"required": False}})
    factory.person(other, "6800", "Otro", "Evento")
    r = _sync(client, ev, _op("x1", "edit_person", id="6800", phone="3001"), _op("x2", "edit_person", h=roster_fingerprint(roster_salt(other), "6800"), phone="3001"), _op("x3", "edit_person", id="9998877", phone="3001")).json()["results"]
    assert [x["result"] for x in r] == ["error"] * 3 and len({x["detail"] for x in r}) == 1, "misma respuesta exista o no"
    assert db.query(User).filter_by(id="6800").one().phone != "3001"


def test_edit_person_op_rejects_a_suppressed_person(client, factory, db, pf_on):
    from app import consent
    from app.models import SuppressedPerson
    from app.routers.api import SUPPRESSED_MSG

    _admin(client, factory)
    ev = _event_with_labels(factory, db)
    _design(ev, client, fields={"role": {"required": False}})
    factory.person(ev, "6900", "Sup", "Primida")
    db.add(SuppressedPerson(tenant_id=ev.tenant_id, cedula_hash=consent.cedula_hash("6900")))
    db.commit()
    r = _sync(client, ev, _op("x4", "edit_person", id="6900", phone="3001")).json()["results"][0]
    assert r["result"] == "error" and r["detail"] == SUPPRESSED_MSG
    assert db.query(User).filter_by(id="6900").one().phone != "3001"
