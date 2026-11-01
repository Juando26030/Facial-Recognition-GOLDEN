"""P12: formulario de varias hojas — limpieza, orden, visibilidad, validación del servidor (envíos que se saltan hojas) y compatibilidad con los de una sola hoja.
La visibilidad se prueba con tests/sheet_vectors.json, que también corre tests/js/form_sheets_check.js sobre form-render.js."""
import copy
import json
from pathlib import Path

import pytest

from app import formlib as fl
from app.models import FormSubmission
from tests.test_forms import _create, _event, _open, _put, _state, _submit, _url

V = json.loads((Path(__file__).parent / "sheet_vectors.json").read_text(encoding="utf-8"))


def _field(fid, kind="text_short", **extra):
    f = {"id": fid, "type": kind, "label": fid.upper(), **extra}
    if kind in ("select", "radio", "multiselect"):
        f.setdefault("options", ["A", "B"])
    return f


def _design(fields, rows, sheets=None):
    return {"fields": {f["id"]: f for f in fields}, "rows": rows, "sheets": sheets}


def _two(rows=None, **sheet_extra):
    sheets = [{"id": "s1", "title": "Uno", "description": ""}, {"id": "s2", "title": "Dos", "description": "", **sheet_extra}]
    return _design([_field("a"), _field("b")], rows or [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}], sheets)


# ------------------------------------------------------------------ compatibilidad: una sola hoja = lo de siempre
def test_single_sheet_forms_are_untouched():
    for sheets in (None, [], [{"id": "s1", "title": "Única", "description": ""}]):
        d = fl.sanitize_design(_design([_field("a")], [{"items": ["a"], "sheet": "s1"}], sheets), set())
        assert "sheets" not in d and all("sheet" not in r for r in d["rows"])
    d = fl.sanitize_design(fl.default_design("Feria"), set())
    assert "sheets" not in d and fl.sheet_of_field(d) == {} and fl.first_error_sheet(d, {"x": "e"}) is None


def test_visible_ids_without_sheets_is_the_same_as_before():
    d = fl.sanitize_design(_design([_field("a", "select"), _field("b", show_if={"field": "a", "op": "equals", "value": "A"})], [{"items": ["a"]}, {"items": ["b"]}]), set())
    assert fl.visible_ids(d, {"a": "A"}) == {"a", "b"} and fl.visible_ids(d, {"a": "B"}) == {"a"}


# ------------------------------------------------------------------ limpieza
def test_sheets_are_sanitized_and_rows_sorted_by_sheet():
    d = fl.sanitize_design(_design([_field("a"), _field("b"), _field("c")],
                                   [{"items": ["b"], "sheet": "s2"}, {"items": ["a"], "sheet": "s1"}, {"items": ["c"], "sheet": "no_existe"}],
                                   [{"id": "s1", "title": "<b>Uno</b><script>1</script><p>x</p>", "description": "<ul><li>a</li></ul><script>1</script>"}, {"id": "s2", "title": "Dos"}]), set())
    assert [s["id"] for s in d["sheets"]] == ["s1", "s2"]
    assert d["sheets"][0]["title"] == "<b>Uno</b>x" and d["sheets"][0]["description"] == "<ul><li>a</li></ul>"      # título: formato básico; descripción: completo
    assert [(r["items"], r["sheet"]) for r in d["rows"]] == [(["a"], "s1"), (["c"], "s1"), (["b"], "s2")]           # sin hoja o inexistente = la primera; ordenadas por hoja, estable
    assert fl.sheet_of_field(d) == {"a": "s1", "c": "s1", "b": "s2"}


def test_a_field_outside_every_row_goes_to_the_last_sheet():
    d = fl.sanitize_design(_design([_field("a"), _field("b")], [{"items": ["a"], "sheet": "s1"}], [{"id": "s1"}, {"id": "s2"}]), set())
    assert fl.sheet_of_field(d)["b"] == "s2"


def test_sheet_limits_and_ids():
    many = [{"id": f"s{i}"} for i in range(fl.MAX_SHEETS)]
    fl.sanitize_design(_design([_field("a")], [{"items": ["a"]}], many), set())
    with pytest.raises(ValueError, match="20"):
        fl.sanitize_design(_design([_field("a")], [{"items": ["a"]}], many + [{"id": "extra"}]), set())
    with pytest.raises(ValueError, match="repetido"):
        fl.sanitize_design(_two() | {"sheets": [{"id": "s1"}, {"id": "s1"}]}, set())
    with pytest.raises(ValueError):
        fl.sanitize_design(_two() | {"sheets": [{"id": "s 1"}, {"id": "s2"}]}, set())


def test_first_and_last_sheet_are_never_conditional():
    cond = {"field": "a", "op": "filled", "value": ""}
    d = fl.sanitize_design(_design([_field("a"), _field("b"), _field("c")], [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}, {"items": ["c"], "sheet": "s3"}],
                                   [{"id": "s1", "show_if": cond}, {"id": "s2", "show_if": cond}, {"id": "s3", "show_if": cond}]), set())
    assert [("show_if" in s) for s in d["sheets"]] == [False, True, False]


# ------------------------------------------------------------------ referencias entre hojas
def test_sheet_conditions_only_use_fields_of_earlier_sheets():
    fields = [_field("a", "select"), _field("b", "select"), _field("c")]
    rows = [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}, {"items": ["c"], "sheet": "s3"}]
    ok = [{"id": "s1"}, {"id": "s2", "show_if": {"field": "a", "op": "equals", "value": "A"}}, {"id": "s3"}]
    fl.sanitize_design(_design(fields, rows, ok), set())
    for bad_field in ("b", "c"):                                   # de su propia hoja o de una posterior
        bad = [{"id": "s1"}, {"id": "s2", "show_if": {"field": bad_field, "op": "equals", "value": "A"}}, {"id": "s3"}]
        with pytest.raises(ValueError, match="hojas anteriores"):
            fl.sanitize_design(_design(fields, rows, bad), set())


def test_field_rules_and_variants_may_use_the_same_or_an_earlier_sheet_but_not_a_later_one():
    sheets = [{"id": "s1"}, {"id": "s2"}]
    same = _design([_field("a", "select"), _field("b", show_if={"field": "a", "op": "equals", "value": "A"})], [{"items": ["a", "b"], "sheet": "s1"}], sheets)
    fl.sanitize_design(same, set())
    earlier = _design([_field("a", "select"), _field("b", show_if={"field": "a", "op": "equals", "value": "A"})], [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}], sheets)
    fl.sanitize_design(earlier, set())
    later = _design([_field("a", "select", show_if={"field": "b", "op": "filled", "value": ""}), _field("b")], [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}], sheets)
    with pytest.raises(ValueError, match="hoja posterior"):
        fl.sanitize_design(later, set())
    variant = {"help": {"items": [{"when": {"field": "b", "op": "filled", "value": ""}, "value": "x"}]}}
    later_variant = _design([_field("a", variants=variant), _field("b")], [{"items": ["a"], "sheet": "s1"}, {"items": ["b"], "sheet": "s2"}], sheets)
    with pytest.raises(ValueError, match="hoja posterior"):
        fl.sanitize_design(later_variant, set())


def test_payment_and_companions_must_be_in_the_last_sheet():
    pay = {"id": "pay", "type": "payment", "label": "Pago", "pay": {"mode": "fixed", "amount": 2000}}
    sheets = [{"id": "s1"}, {"id": "s2"}]
    fl.sanitize_design(_design([_field("a"), pay], [{"items": ["a"], "sheet": "s1"}, {"items": ["pay"], "sheet": "s2"}], sheets), set())
    with pytest.raises(ValueError, match="última hoja"):
        fl.sanitize_design(_design([_field("a"), pay], [{"items": ["pay"], "sheet": "s1"}, {"items": ["a"], "sheet": "s2"}], sheets), set())
    comp = {"id": "k", "type": "companions", "label": "Acomp", "max": 2, "min": 0, "person_fields": [{"id": "nombre", "label": "Nombre", "type": "text_short"}]}
    with pytest.raises(ValueError, match="última hoja"):
        fl.sanitize_design(_design([_field("a"), comp], [{"items": ["k"], "sheet": "s1"}, {"items": ["a"], "sheet": "s2"}], sheets), set())


def test_sanitizing_is_idempotent_for_export_import_and_duplicate():
    d = fl.sanitize_design(copy.deepcopy(V["design"]), set())
    assert fl.sanitize_design(d, set()) == d
    assert json.loads(json.dumps(d)) == d


# ------------------------------------------------------------------ visibilidad (mismos casos que el navegador)
@pytest.mark.parametrize("case", V["cases"], ids=lambda c: c["name"])
def test_visible_ids_with_sheets(case):
    d = fl.sanitize_design(copy.deepcopy(V["design"]), set())
    assert fl.visible_ids(d, case["values"]) == set(case["visible"])


# ------------------------------------------------------------------ el servidor revalida todo
def test_validation_ignores_hidden_sheets_and_discards_what_was_typed_there():
    d = fl.sanitize_design(copy.deepcopy(V["design"]), set())
    values = {"c": "Cali", "t": "Invitado", "a": "Chapinero", "b": "Gerente", "d": "x", "z": "hola"}          # llenó las hojas 2 y 3 y luego cambió y se ocultaron
    clean, errors = fl.validate_submission(d, values, {})
    assert errors == {} and clean == {"c": "Cali", "t": "Invitado", "z": "hola"}                           # obligatorios de hojas ocultas no estorban; lo escrito allí se descarta


def test_validation_requires_every_visible_sheet_even_if_the_browser_skipped_them():
    d = fl.sanitize_design(copy.deepcopy(V["design"]), set())
    clean, errors = fl.validate_submission(d, {"c": "Bogotá", "t": "Empleado"}, {})                       # saltó las hojas 2 y 3
    assert set(errors) == {"a", "b"} and "c" in clean
    assert fl.first_error_sheet(d, errors) == "s2"
    assert fl.first_error_sheet(d, {"b": "x"}) == "s3" and fl.first_error_sheet(d, {"z": "x", "a__tipo": "y"}) == "s2"


# ------------------------------------------------------------------ de punta a punta por la página pública
@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _sheets_form(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    design = copy.deepcopy(V["design"])
    design["rows"] = [{"align": "left", "items": [fid], "sheet": r["sheet"]} for r in V["design"]["rows"] for fid in r["items"]]
    assert _put(client, ev, f, design=design).status_code == 200
    _open(client, ev, f)
    return ev, f


def test_public_submit_skipping_sheets_is_rejected_with_the_sheet_to_go_back_to(client, factory):
    ev, f = _sheets_form(client, factory)
    assert _state(client, ev, f)["design"]["sheets"][1]["id"] == "s2"
    r = _submit(client, ev, f, {"c": "Bogotá", "t": "Empleado"})
    assert r.status_code == 422 and set(r.json()["errors"]) == {"a", "b"} and r.json()["error_sheet"] == "s2"


def test_public_submit_stores_only_visible_sheets(client, factory, db):
    ev, f = _sheets_form(client, factory)
    r = _submit(client, ev, f, {"c": "Cali", "t": "Invitado", "a": "Chapinero", "b": "Gerente", "z": "ok"})        # llenó y luego se ocultaron las hojas 2 y 3
    assert r.status_code == 200, r.text
    stored = json.loads(db.query(FormSubmission).filter_by(form_id=f["id"]).one().data_json)
    assert stored == {"c": "Cali", "t": "Invitado", "z": "ok"}
    assert "Chapinero" not in json.dumps(stored) and "Gerente" not in json.dumps(stored)


def test_single_sheet_public_form_keeps_working_and_exposes_no_sheets(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    assert "sheets" not in _state(client, ev, f)["design"]
    assert _submit(client, ev, f, {"cedula": "1001", "nombres": "Ana", "apellidos": "Mora", "correo": "ana@example.com"}).status_code == 200
    assert _url(ev, f).startswith("/f/")
