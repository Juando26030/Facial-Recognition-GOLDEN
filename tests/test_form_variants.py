"""P2: texto con variantes (título / texto informativo): limpieza en el servidor y regla de selección (mismos casos que tests/js/form_variants_check.js)."""
import pytest

from app import formlib as fl

FIELDS = {
    "c": {"id": "c", "type": "select", "label": "Ciudad", "options": ["Bogotá", "Apartadó", "Necoclí"]},
    "t": {"id": "t", "type": "paragraph", "content": "Texto fijo",
          "variants": {"by": "c", "items": [{"rule": {"field": "c", "op": "equals", "value": "Bogotá"}, "content": "Sede Bogotá"},
                                           {"rule": {"field": "c", "op": "in", "value": ["Apartadó", "Necoclí"]}, "content": "Sede Urabá"}], "default": "Sede por confirmar"}},
}


def _design(**t_extra):
    fields = {k: dict(v) for k, v in FIELDS.items()}
    fields["t"].update(t_extra)
    return fl.sanitize_design({"fields": fields, "rows": [{"items": ["c"]}, {"items": ["t"]}]}, set())


def test_variants_survive_sanitizing_and_roundtrip():
    d = _design()
    v = d["fields"]["t"]["variants"]
    assert v["by"] == "c" and len(v["items"]) == 2 and v["default"] == "Sede por confirmar"
    assert fl.sanitize_design(d, set())["fields"]["t"]["variants"] == v          # exportar/importar/duplicar: idempotente


def test_fields_without_variants_do_not_gain_keys():
    d = fl.sanitize_design({"fields": {"p": {"id": "p", "type": "paragraph", "content": "Hola"}}, "rows": []}, set())
    assert "variants" not in d["fields"]["p"] and d["fields"]["p"]["content"] == "Hola"


def test_empty_variants_are_dropped_and_bad_rules_rejected():
    assert "variants" not in _design(variants={"by": "c", "items": [], "default": ""})["fields"]["t"]
    with pytest.raises(ValueError):
        _design(variants={"items": [{"rule": {"field": "no_existe", "op": "equals", "value": "x"}, "content": "a"}]})
    with pytest.raises(ValueError):
        _design(variants={"items": [{"rule": {"field": "t", "op": "equals", "value": "x"}, "content": "a"}]})      # no puede depender de sí mismo


def test_variants_are_capped_and_text_is_cut():
    many = [{"rule": {"field": "c", "op": "equals", "value": str(i)}, "content": "x" * 5000} for i in range(50)]
    v = _design(variants={"by": "c", "items": many})["fields"]["t"]["variants"]
    assert len(v["items"]) == fl.MAX_VARIANTS and len(v["items"][0]["content"]) <= 2000


def test_pick_first_match_then_default_then_nothing():
    f = _design()["fields"]["t"]
    pick = lambda c, visible=None: fl.pick_variant(f, {"c": c}, visible)
    assert pick("Bogotá") == "Sede Bogotá"
    assert pick("bogota") == "Sede Bogotá"                 # tildes/mayúsculas no rompen
    assert pick("Necoclí") == "Sede Urabá" and pick("Apartado") == "Sede Urabá"
    assert pick("Cali") == "Sede por confirmar" and pick("") == "Sede por confirmar"
    assert pick("Bogotá", visible=set()) == "Sede por confirmar"      # el campo que decide está oculto: no cuenta
    f2 = dict(f, variants={"by": "c", "items": f["variants"]["items"]})
    assert fl.pick_variant(f2, {"c": "Cali"}) is None     # sin variante ni por defecto: no ocupa espacio


def test_first_matching_variant_wins():
    f = {"variants": {"items": [{"rule": {"field": "c", "op": "contains", "value": "a"}, "content": "uno"}, {"rule": {"field": "c", "op": "equals", "value": "Bogotá"}, "content": "dos"}]}}
    assert fl.pick_variant(f, {"c": "Bogotá"}) == "uno"


def test_plain_text_is_unchanged():
    assert fl.pick_variant({"content": "Hola"}, {}) == "Hola"
