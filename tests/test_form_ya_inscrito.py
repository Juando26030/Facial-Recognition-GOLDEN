"""«Ya inscrito»: ajuste por formulario «Bloquear inscripciones repetidas» (por cédula o por otro campo identificador) y columna «Registrado en formulario» de la carga de la base."""
import threading

import pytest

from app import formlib as fl
from app import formsvc
from app.models import FormSubmission
from tests.conftest import login
from tests.test_forms import _create, _design, _event, _open, _person_values, _put, _state, _status, _submit, _url

ALREADY = formsvc.ALREADY_MSG


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _block(client, ev, f, enabled=True, field="", **settings):
    login(client, "coord1")
    r = _put(client, ev, f, settings={"block_repeats": {"enabled": enabled, "field": field}, **settings})
    assert r.status_code == 200, r.text
    return r


def _lookup(client, ev, f, cedula, key=None):
    return client.post(f"{_url(ev, f)}/lookup", json={"id": cedula, "k": key})


def _no_cedula_form(client, ev, field_id, field_type):
    """Formulario SIN campo de cédula: nombres + correo + teléfono; el identificador es `field_id`."""
    f = _create(client, ev)
    fields = [{"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
              {"id": "correo", "type": "email", "label": "Correo", "key": "email", "required": True},
              {"id": "cel", "type": "phone", "label": "Celular", "key": "phone", "required": True},
              {"id": "doc", "type": "text_short", "label": "Código de socio", "required": True}]
    assert _put(client, ev, f, design=_design(fields)).status_code == 200
    _block(client, ev, f, field=field_id)
    return f


def _id_submit(client, ev, f, values, sid="s1"):
    """Formulario con identificación por cédula: primero `lookup` (da el token), luego el envío."""
    tok = _lookup(client, ev, f, values["cedula"]).json().get("token")
    return _submit(client, ev, f, values, token=tok, sid=sid)


def _vals(n="Ana", correo="ana@example.com", cel="300 123 4567", doc="AB-12"):
    return {"nombres": n, "correo": correo, "cel": cel, "doc": doc}


# ------------------------------- ajuste y normalización
def test_setting_defaults_and_sanitize():
    assert fl.sanitize_settings({})["block_repeats"] == {"enabled": False, "field": ""}
    assert fl.sanitize_settings({"block_repeats": {"enabled": 1, "field": "x" * 99}})["block_repeats"] == {"enabled": True, "field": "x" * 40}
    assert fl.sanitize_settings({"block_repeats": "basura"})["block_repeats"] == {"enabled": False, "field": ""}


@pytest.mark.parametrize("value,ftype,want", [
    ("  Ana@Example.COM ", "email", "ana@example.com"), ("1.020 .304-050", "text_short", "1020304050"), ("AB - 12", "text_short", "ab12"),
    ("+57 (300) 123-4567", "phone", "573001234567"), ("300.123.4567", "phone", "3001234567"), (None, "email", ""),
])
def test_identifier_normalization(value, ftype, want):
    assert fl.normalize_identifier(value, ftype) == want


def test_cannot_enable_without_anything_to_compare(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _put(client, ev, f, design=_design([{"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True}])).status_code == 200
    r = _put(client, ev, f, settings={"block_repeats": {"enabled": True, "field": ""}})
    assert r.status_code == 400 and "identificador" in r.json()["detail"]


# ------------------------------- con cédula: lookup y envío
def test_lookup_stops_an_already_registered_person_and_reveals_nothing_else(client, factory, db):
    ev = _event(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    f = _create(client, ev)
    _block(client, ev, f, prefill={"mode": "cedula", "source": "event"})
    _open(client, ev, f)
    assert _lookup(client, ev, f, "1001").status_code == 200                                   # aún no se ha inscrito
    assert _id_submit(client, ev, f, _person_values()).status_code == 200
    r = _lookup(client, ev, f, "1.001")                                                          # misma cédula escrita con punto
    assert r.status_code == 409 and r.json() == {"detail": ALREADY, "already": True, "duplicate": True}      # nada más que «ya inscrito»: ni nombre, ni correo, ni token
    assert "Ana" not in r.text and "ana@" not in r.text
    assert _lookup(client, ev, f, "9999").status_code in (200, 403)                              # otra persona no se ve afectada


def test_lookup_does_not_block_when_the_switch_is_off(client, factory):
    ev = _event(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    f = _create(client, ev)
    login(client, "coord1")
    assert _put(client, ev, f, settings={"prefill": {"mode": "cedula", "source": "event"}}).status_code == 200
    _open(client, ev, f)
    assert _id_submit(client, ev, f, _person_values()).status_code == 200
    assert _lookup(client, ev, f, "1001").status_code == 200                                     # sin el ajuste, el comportamiento de siempre (el envío sí rechaza el duplicado)
    r = _id_submit(client, ev, f, _person_values(), sid="otra")
    assert r.status_code == 409 and r.json()["detail"] == ALREADY and r.json()["duplicate"] is True


def test_tests_never_count_for_lookup_or_submit(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _block(client, ev, f)
    key = client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["test_key"]
    client.post("/logout")
    assert _submit(client, ev, f, _person_values(), key=key, sid="t1").status_code == 200
    assert _lookup(client, ev, f, "1001", key=key).status_code != 409
    assert _submit(client, ev, f, _person_values(), key=key, sid="t2").status_code == 200       # las pruebas no se bloquean entre sí


def test_check_endpoint_with_cedula_and_state_flag(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _block(client, ev, f)
    _open(client, ev, f)
    assert _state(client, ev, f)["repeat_check"] == "cedula"
    chk = lambda v: client.post(f"{_url(ev, f)}/check", json={"value": v}).json()              # noqa: E731
    assert chk("1001") == {"registered": False}
    assert _submit(client, ev, f, _person_values()).status_code == 200
    assert chk(" 1.001 ") == {"registered": True} and chk("2002") == {"registered": False} and chk("") == {"registered": False}


# ------------------------------- sin cédula: campo identificador elegido
@pytest.mark.parametrize("field,ftype,first,again,other", [
    ("correo", "email", {"correo": "ana@example.com"}, {"correo": "  ANA@Example.com "}, {"correo": "otra@example.com"}),
    ("cel", "phone", {"cel": "300 123 4567"}, {"cel": "300-123-4567"}, {"cel": "311 000 0000"}),
    ("doc", "text_short", {"doc": "AB-12"}, {"doc": "ab 12"}, {"doc": "AB-13"}),
])
def test_without_cedula_the_chosen_field_blocks_normalized_repeats(client, factory, db, field, ftype, first, again, other):
    ev = _event(client, factory)
    f = _no_cedula_form(client, ev, field, ftype)
    _open(client, ev, f)
    assert _submit(client, ev, f, {**_vals(), **first}, sid="a").status_code == 200
    base_other = {"correo": "z@example.com", "cel": "322 999 9999", "doc": "ZZ-1"}                # lo demás cambia: solo el identificador elegido decide
    r = _submit(client, ev, f, {**_vals("Beto"), **base_other, **again}, sid="b")
    assert r.status_code == 409 and r.json() == {"detail": ALREADY, "duplicate": True, "already": True}
    assert _submit(client, ev, f, {**_vals("Caro"), **base_other, **other}, sid="c").status_code == 200
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 2
    assert _submit(client, ev, f, {**_vals(), **first}, sid="a").json().get("replayed") is True           # el reintento del navegador sigue siendo idempotente


def test_without_cedula_and_switch_off_nothing_is_blocked(client, factory):
    ev = _event(client, factory)
    f = _no_cedula_form(client, ev, "correo", "email")
    login(client, "coord1")
    _block(client, ev, f, enabled=False)
    _open(client, ev, f)
    assert _submit(client, ev, f, _vals(), sid="a").status_code == 200
    assert _submit(client, ev, f, _vals(), sid="b").status_code == 200


def test_check_endpoint_with_a_chosen_field(client, factory):
    ev = _event(client, factory)
    f = _no_cedula_form(client, ev, "correo", "email")
    _open(client, ev, f)
    assert _state(client, ev, f)["repeat_check"] == "correo"
    assert _submit(client, ev, f, _vals(), sid="a").status_code == 200
    assert client.post(f"{_url(ev, f)}/check", json={"value": "ANA@example.com"}).json() == {"registered": True}
    assert client.post(f"{_url(ev, f)}/check", json={"value": "nadie@example.com"}).json() == {"registered": False}


def test_double_click_and_concurrent_submissions_create_exactly_one(factory, db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "0")
    with TestClient(app, follow_redirects=False) as admin:
        ev = _event(admin, factory)
        f = _no_cedula_form(admin, ev, "correo", "email")
        _open(admin, ev, f)
    results = []

    def go(n):
        with TestClient(app, follow_redirects=False) as c:
            results.append(_submit(c, ev, f, _vals(n=f"P{n}", correo="Mismo@Example.com" if n % 2 else "mismo@example.com ", cel=f"300 000 00{n:02d}", doc=f"D{n}"), sid=f"s{n}").status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results).count(200) == 1 and all(code in (200, 409, 503) for code in results)
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1


# ------------------------------- carga de la base: «Registrado en formulario»
def _upload(client, ev, *lines):
    csv = ("\n".join(lines) + "\n").encode()
    return client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("base.csv", csv, "text/csv")})


def test_roster_column_marks_people_as_already_registered_without_using_capacity(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    login(client, "coord1")
    assert client.put(f"/api/events/{ev.id}/forms/{f['id']}/status", json={"capacity": 1}).status_code == 200
    assert _put(client, ev, f, settings={"prefill": {"mode": "cedula", "source": "event"}, "block_repeats": {"enabled": True, "field": ""}}).status_code == 200      # las marcas solo bloquean con el interruptor encendido
    r = _upload(client, ev, "Cédula,Nombres,Apellidos,Correo,Registrado en formulario",
                "1001,Ana,Mora,ana@example.com,Sí", "1002,Beto,Paz,beto@example.com,no", "1003,Caro,Gil,caro@example.com,X", "1004,Dani,Ruiz,dani@example.com,")
    assert r.status_code == 200, r.text
    rows = {s.person_id: s for s in db.query(FormSubmission).filter_by(form_id=f["id"])}
    assert set(rows) == {"1001", "1003"} and all(s.status == formsvc.PREREGISTERED and s.is_test is False for s in rows.values())
    assert formsvc.mark_preregistered(db, ev, ["1001", "1003"]) == 0          # recargar no duplica
    db.commit()
    db.expire_all()
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 2
    summary = client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()
    assert summary["submissions"] == 0 and summary["preregistered"] == 2          # no cuentan como inscripciones reales ni ocupan cupo; se muestran aparte
    _open(client, ev, f)
    r = _lookup(client, ev, f, "1001")
    assert r.status_code == 409 and r.json()["detail"] == ALREADY
    assert _lookup(client, ev, f, "1002").status_code == 200
    assert _lookup(client, ev, f, "1003").status_code == 409
    tok = _lookup(client, ev, f, "1002").json()["token"]                                         # saltándose el paso de identificación con el token de otra persona, el envío también lo rechaza
    assert _submit(client, ev, f, {**_person_values(), "cedula": "1003", "correo": "caro@example.com"}, token=tok, sid="x").status_code == 409
    assert _id_submit(client, ev, f, {**_person_values(), "cedula": "1002", "nombres": "Beto", "correo": "beto@example.com"}, sid="y").status_code == 200      # el cupo (1) seguía libre
    assert _id_submit(client, ev, f, {**_person_values(), "cedula": "1004", "correo": "dani@example.com"}, sid="z").status_code == 409                          # ahora sí se llenó


def test_roster_flag_also_blocks_by_email_when_the_form_has_no_cedula(client, factory):
    ev = _event(client, factory)
    f = _no_cedula_form(client, ev, "correo", "email")
    assert _upload(client, ev, "Cédula,Nombres,Apellidos,Correo,Registrado en formulario", "1001,Ana,Mora,Ana@Example.com,si").status_code == 200
    _open(client, ev, f)
    r = _submit(client, ev, f, _vals(correo="ana@example.com"), sid="a")
    assert r.status_code == 409 and r.json()["detail"] == ALREADY
    assert _submit(client, ev, f, _vals(correo="otra@example.com"), sid="b").status_code == 200


# ------------------------------- lista «Personas ya registradas» por formulario
def _list_up(client, ev, f, *lines, mode="add", effect="block", enable="1"):
    csv = ("\n".join(lines) + "\n").encode()
    return client.post(f"/api/events/{ev.id}/forms/{f['id']}/registered", data={"mode": mode, "effect": effect, "enable": enable}, files={"file": ("lista.csv", csv, "text/csv")})


def _summary(client, ev, f):
    return client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()


def test_form_list_blocks_turns_the_switch_on_and_does_not_use_capacity(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _status(client, ev, f, capacity=1).status_code == 200
    r = _list_up(client, ev, f, "Cédula,Registrado en formulario", "1001,sí", "1002,no", "1003,X")
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2 and r.json()["turned_on"] is True and "Se activó" in r.json()["message"]
    sm = _summary(client, ev, f)
    assert sm["preregistered"] == 2 and sm["registered_hold"] == 0 and sm["submissions"] == 0 and sm["settings"]["block_repeats"]["enabled"] is True
    assert _list_up(client, ev, f, "Cédula", "1001", "1004").json()["added"] == 1                  # agregar no quita nada y no duplica
    _open(client, ev, f)
    assert _lookup(client, ev, f, "1001").status_code == 409 and _lookup(client, ev, f, "1004").status_code == 409
    assert _lookup(client, ev, f, "1002").status_code == 200
    assert _id_submit(client, ev, f, {**_person_values(), "cedula": "1002", "correo": "b@example.com"}).status_code == 200      # el cupo (1) seguía libre


def test_form_list_replace_removes_previous_marks_and_clear_removes_all(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _list_up(client, ev, f, "Cédula", "1001", "1002").json()["added"] == 2
    r = _list_up(client, ev, f, "Cédula", "1002", "1003", mode="replace").json()
    assert r["removed"] == 2 and r["added"] == 2 and _summary(client, ev, f)["preregistered"] == 2
    _open(client, ev, f)
    assert _lookup(client, ev, f, "1001").status_code == 200 and _lookup(client, ev, f, "1003").status_code == 409
    login(client, "coord1")
    r = client.delete(f"/api/events/{ev.id}/forms/{f['id']}/registered")
    assert r.status_code == 200 and r.json()["removed"] == 2
    assert _summary(client, ev, f)["preregistered"] == 0
    _open(client, ev, f)
    assert _lookup(client, ev, f, "1003").status_code == 200


def test_form_list_hold_takes_capacity_and_clearing_frees_it(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _status(client, ev, f, capacity=2).status_code == 200
    assert _list_up(client, ev, f, "Cédula", "1001", "1002", effect="hold").json()["added"] == 2
    sm = _summary(client, ev, f)
    assert sm["registered_hold"] == 2 and sm["preregistered"] == 0
    _open(client, ev, f)
    full = _submit(client, ev, f, {**_person_values(), "cedula": "1003"}, sid="x")                # cupo 2 de 2: sin sobreventa
    assert full.status_code == 409 and full.json().get("stage") == "closed"
    dup = _submit(client, ev, f, {**_person_values(), "cedula": "1001"}, sid="y")
    assert dup.status_code == 409
    login(client, "coord1")
    assert client.delete(f"/api/events/{ev.id}/forms/{f['id']}/registered").json()["removed"] == 2
    _open(client, ev, f)
    assert _submit(client, ev, f, {**_person_values(), "cedula": "1003", "correo": "c@example.com"}, sid="z").status_code == 200


def test_form_list_add_with_hold_converts_existing_block_marks(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _list_up(client, ev, f, "Cédula", "1001").json()["added"] == 1
    r = _list_up(client, ev, f, "Cédula", "1001", "1002", effect="hold").json()
    assert r["converted"] == 1 and r["added"] == 1
    sm = _summary(client, ev, f)
    assert sm["registered_hold"] == 2 and sm["preregistered"] == 0


def test_form_list_by_email_for_a_form_without_cedula_and_switch_option(client, factory):
    ev = _event(client, factory)
    f = _no_cedula_form(client, ev, "correo", "email")
    assert _list_up(client, ev, f, "Correo", "Ana@Example.com", "otra@example.com").json()["added"] == 2
    _open(client, ev, f)
    r = _submit(client, ev, f, _vals(correo=" ana@example.COM "), sid="a")
    assert r.status_code == 409 and r.json()["detail"] == ALREADY
    assert _submit(client, ev, f, _vals(correo="nueva@example.com"), sid="b").status_code == 200


def test_form_list_with_switch_option_off_keeps_the_switch_off_and_does_not_block(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    r = _list_up(client, ev, f, "Cédula", "1001", enable="0").json()
    assert r["turned_on"] is False and "apagado" in r["message"]
    _open(client, ev, f)
    assert _lookup(client, ev, f, "1001").status_code == 200


def test_form_list_rejects_bad_files_and_modes(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _list_up(client, ev, f, "Nombre", "Ana").status_code == 400
    assert _list_up(client, ev, f, "Cédula", "1001", mode="borrar").status_code == 400
    assert _list_up(client, ev, f, "Cédula,Registrado en formulario", "1001,no").status_code == 400
