"""Lógica pura de los Formularios Web (app/formlib.py): diseño, condiciones, validación y calendario."""
from datetime import datetime

import pytest

from app import formlib as fl


def _design(*fields, rows=None):
    fmap = {f["id"]: f for f in fields}
    return fl.sanitize_design({"fields": fmap, "rows": rows or [{"items": [f["id"]]} for f in fields]}, {"opcional_1", "opcional_2"})


def _f(fid, kind="text_short", **extra):
    return {"id": fid, "type": kind, "label": fid.upper(), **extra}


# ------------------------------- diseño -------------------------------
def test_default_design_is_valid_and_linked_to_event_fields():
    d = fl.sanitize_design(fl.default_design("Feria"), set())
    keys = {f["key"] for f in d["fields"].values()}
    assert keys == {"id", "first_name", "last_name", "email"} and d["theme"]["title"] == "Feria"
    assert len(d["rows"]) == 4


def test_slugify():
    assert fl.slugify("Inscripción Feria 2026!") == "inscripcion-feria-2026" and fl.slugify("¡¡¡") == "formulario"


def test_layout_rows_keep_side_by_side_fields_and_alignment():
    d = _design(_f("a"), _f("b"), _f("c"), rows=[{"align": "center", "items": ["a", "b"]}, {"items": ["c"]}])
    assert d["rows"] == [{"align": "center", "items": ["a", "b"]}, {"align": "left", "items": ["c"]}]
    with pytest.raises(ValueError, match="hasta 4"):
        _design(*[_f(x) for x in "abcde"], rows=[{"items": list("abcde")}])


def test_fields_missing_from_rows_are_appended_and_unknown_ones_dropped():
    d = fl.sanitize_design({"fields": {"a": _f("a"), "b": _f("b")}, "rows": [{"items": ["a", "zzz"]}]}, set())
    assert [r["items"] for r in d["rows"]] == [["a"], ["b"]]


@pytest.mark.parametrize("bad,msg", [
    ({"id": "a", "type": "inventado", "label": "x"}, "Tipo de campo"),
    ({"id": "a", "type": "text_short", "label": ""}, "nombre"),
    ({"id": "a", "type": "select", "label": "X", "options": []}, "opción"),
    ({"id": "a", "type": "select", "label": "X", "options": ["a", "a"]}, "repetirse"),
    ({"id": "a", "type": "text_short", "label": "X", "key": "opcional_9"}, "no existe"),
    ({"id": "a", "type": "file", "label": "X", "accept": ["exe"]}, "no permitido"),
])
def test_invalid_fields_are_rejected(bad, msg):
    with pytest.raises(ValueError, match=msg):
        fl.sanitize_design({"fields": {"a": bad}}, {"opcional_1"})


def test_event_field_can_only_be_used_once_and_theme_is_validated():
    with pytest.raises(ValueError, match="dos veces"):
        _design(_f("a", key="id"), _f("b", key="id"))
    with pytest.raises(ValueError, match="color"):
        fl.sanitize_design({"fields": {}, "theme": {"accent": "rojo"}}, set())
    with pytest.raises(ValueError, match="Fuente"):
        fl.sanitize_design({"fields": {}, "theme": {"font": "Comic Inventada"}}, set())


def test_conditions_must_point_to_existing_fields_without_cycles():
    with pytest.raises(ValueError, match="no existe"):
        _design(_f("a", show_if={"field": "zzz", "op": "equals", "value": "x"}))
    with pytest.raises(ValueError, match="círculo"):
        _design(_f("a", show_if={"field": "b", "value": "x"}), _f("b", show_if={"field": "a", "value": "x"}))


# ------------------------------- condiciones / visibilidad -------------------------------
def test_condition_operators():
    met = fl.condition_met
    assert met({"field": "t", "op": "equals", "value": "Pasaporte"}, {"t": "pasaporte"})            # sin importar mayúsculas
    assert not met({"field": "t", "op": "equals", "value": "pasaporte"}, {"t": "cedula"})
    assert met({"field": "t", "op": "not_equals", "value": "pasaporte"}, {"t": "cedula"})
    assert met({"field": "t", "op": "contains", "value": "vuelo"}, {"t": "mi vuelo 12"})
    assert met({"field": "t", "op": "in", "value": ["a", "b"]}, {"t": "b"}) and not met({"field": "t", "op": "in", "value": ["a"]}, {"t": "z"})
    assert met({"field": "t", "op": "equals", "value": "b"}, {"t": ["a", "b"]})                     # multiselección
    assert met({"field": "t", "op": "filled"}, {"t": "x"}) and not met({"field": "t", "op": "filled"}, {"t": ""})
    assert met(None, {})


def test_passport_example_from_the_brief():
    d = _design(
        _f("doc", "select", options=["Cédula", "Pasaporte"]),
        _f("vuelo", show_if={"field": "doc", "op": "equals", "value": "Pasaporte"}, required=True),
        {"id": "foto", "type": "image", "src": "x/y.png", "show_if": {"field": "doc", "op": "equals", "value": "Pasaporte"}},
    )
    assert fl.visible_ids(d, {"doc": "Pasaporte"}) == {"doc", "vuelo", "foto"}
    assert fl.visible_ids(d, {"doc": "Cédula"}) == {"doc"}


def test_a_child_of_a_hidden_field_is_hidden_too():
    d = _design(_f("a", "checkbox"), _f("b", show_if={"field": "a", "op": "equals", "value": "true"}), _f("c", show_if={"field": "b", "op": "filled"}))
    assert fl.visible_ids(d, {"a": "false", "b": "x"}) == {"a"}
    assert fl.visible_ids(d, {"a": "true", "b": "x"}) == {"a", "b", "c"}


# ------------------------------- validación de respuestas -------------------------------
def test_required_and_types():
    d = _design(_f("n", required=True), _f("e", "email", required=True), _f("t", "phone"), _f("k", "number"), _f("d", "date"),
                _f("s", "select", options=["A", "B"]), _f("m", "multiselect", options=["X", "Y", "Z"]), _f("ok", "checkbox", required=True))
    stub = lambda email: (email.endswith("@example.com"), "el dominio no existe")
    clean, err = fl.validate_submission(d, {}, {}, stub)
    assert set(err) == {"n", "e", "ok"}
    clean, err = fl.validate_submission(d, {"n": " Ana ", "e": "ANA@example.com", "t": "+57 300 1234567", "k": "3,5", "d": "2026-10-01", "s": "B", "m": ["X", "Z"], "ok": "true"}, {}, stub)
    assert err == {} and clean["n"] == "Ana" and clean["e"] == "ana@example.com" and clean["m"] == ["X", "Z"] and clean["ok"] is True
    _, err = fl.validate_submission(d, {"n": "a", "e": "ana@dominio-falso.com", "ok": "true"}, {}, stub)
    assert "dominio" in err["e"]
    _, err = fl.validate_submission(d, {"n": "a", "e": "no-es-correo", "ok": "on", "t": "abc", "k": "x", "d": "31/12/2026", "s": "Q", "m": ["W"]}, {}, stub)
    assert set(err) == {"e", "t", "k", "d", "s", "m"}


def test_hidden_fields_are_neither_required_nor_saved():
    d = _design(_f("doc", "select", options=["Cédula", "Pasaporte"], required=True), _f("vuelo", required=True, show_if={"field": "doc", "op": "equals", "value": "Pasaporte"}))
    clean, err = fl.validate_submission(d, {"doc": "Cédula", "vuelo": "AV123 (manipulado)"}, {})
    assert err == {} and "vuelo" not in clean                                     # el navegador mandó un valor de un campo oculto: se ignora
    _, err = fl.validate_submission(d, {"doc": "Pasaporte"}, {})
    assert "vuelo" in err


def test_files_required_and_recorded():
    d = _design(_f("cv", "file", required=True))
    _, err = fl.validate_submission(d, {}, {})
    assert "cv" in err
    clean, err = fl.validate_submission(d, {}, {"cv": {"filename": "cv.pdf", "stored": "1_cv.pdf", "size": 10}})
    assert err == {} and clean["cv"]["filename"] == "cv.pdf"


def test_length_limits():
    d = _design(_f("a"), _f("b", "text_long"))
    _, err = fl.validate_submission(d, {"a": "x" * 301, "b": "y" * 5001}, {})
    assert set(err) == {"a", "b"}


# ------------------------------- configuración -------------------------------
def test_settings_defaults_and_validation():
    s = fl.sanitize_settings({})
    assert s["feed"] == "manual" and s["prefill"]["mode"] == "none" and s["thanks"]["mode"] == "template"
    with pytest.raises(ValueError, match="código"):
        fl.sanitize_settings({"security": {"enabled": True, "type": "code", "code": ""}})
    assert fl.sanitize_settings({"security": {"enabled": True, "type": "cedula"}})["security"]["type"] == "cedula"    # la cédula no necesita código
    with pytest.raises(ValueError, match="http"):
        fl.sanitize_settings({"thanks": {"mode": "redirect", "url": "javascript:alert(1)"}})
    with pytest.raises(ValueError, match="Fuente"):
        fl.sanitize_settings({"prefill": {"mode": "cedula", "source": "otra-cosa"}})
    assert fl.sanitize_settings({"prefill": {"mode": "invite", "source": "event:7"}})["prefill"]["source"] == "event:7"
    assert fl.sanitize_settings({"feed": "raro"})["feed"] == "manual"


# ------------------------------- estados y calendario -------------------------------
def test_manual_status_when_no_schedule():
    now = datetime(2026, 10, 1, 12)
    assert fl.effective_status("activo", False, [], now) == "activo"
    assert fl.effective_status("pruebas", False, [{"status": "activo", "from": "2026-10-01T00:00", "to": "2026-10-02T00:00"}], now) == "pruebas"


def test_schedule_ranges_and_default_closed_outside():
    sch = fl.parse_schedule([
        {"status": "pruebas", "from": "2026-10-01T08:00", "to": "2026-10-06T00:00"},
        {"status": "activo", "from": "2026-10-06T00:00", "to": "2026-10-21T00:00"},
        {"status": "cerrado", "from": "2026-10-21T00:00", "to": "2026-10-25T00:00"},
    ])
    at = lambda s: fl.effective_status("activo", True, sch, datetime.fromisoformat(s))
    assert at("2026-10-03T10:00") == "pruebas" and at("2026-10-06T00:00") == "activo" and at("2026-10-20T23:59") == "activo"
    assert at("2026-10-22T00:00") == "cerrado"
    assert at("2026-09-30T10:00") == "cerrado" and at("2027-01-01T00:00") == "cerrado"          # fuera de todo rango: cerrado por defecto


def test_schedule_validation():
    with pytest.raises(ValueError, match="traslapar"):
        fl.parse_schedule([{"status": "activo", "from": "2026-10-01T00:00", "to": "2026-10-05T00:00"}, {"status": "cerrado", "from": "2026-10-04T00:00", "to": "2026-10-06T00:00"}])
    with pytest.raises(ValueError, match="posterior"):
        fl.parse_schedule([{"status": "activo", "from": "2026-10-05T00:00", "to": "2026-10-01T00:00"}])
    with pytest.raises(ValueError, match="Estado"):
        fl.parse_schedule([{"status": "raro", "from": "2026-10-01T00:00", "to": "2026-10-02T00:00"}])
    with pytest.raises(ValueError, match="fecha"):
        fl.parse_schedule([{"status": "activo"}])
