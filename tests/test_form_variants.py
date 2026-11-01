"""P9: condiciones en árbol (Y/O anidados) y variantes por propiedad — limpieza en el servidor, límites, formato antiguo y regla de selección.
Los mismos casos de evaluación (tests/cond_vectors.json) los corre tests/js/form_conditions_check.js sobre form-render.js."""
import json
from pathlib import Path

import pytest

from app import formlib as fl

V = json.loads((Path(__file__).parent / "cond_vectors.json").read_text(encoding="utf-8"))
OPTS = ["Bogotá", "Apartadó", "Necoclí", "Cali", "Pasto"]


def _fields(**extra):
    base = {"c": {"id": "c", "type": "select", "label": "Ciudad", "options": OPTS},
            "t": {"id": "t", "type": "select", "label": "Tipo", "options": ["Empleado", "Invitado"]},
            "e": {"id": "e", "type": "text_short", "label": "Entidad"}}
    base.update(extra)
    return base


def _clean(**extra):
    return fl.sanitize_design({"fields": _fields(**extra), "rows": []}, set())["fields"]


def _rule(value="Bogotá", field="c", op="equals"):
    return {"field": field, "op": op, "value": value}


# ------------------------------------------------------------------ evaluación (mismos casos que el navegador)
@pytest.mark.parametrize("case", V["eval"], ids=lambda c: c["name"])
def test_condition_tree_evaluation(case):
    visible = set(case["visible"]) if "visible" in case else {"c", "t", "e"}
    assert fl.cond_tree_met(case["tree"], case["values"], lambda f: f in visible) is case["expected"]


@pytest.mark.parametrize("case", V["eval"], ids=lambda c: c["name"])
def test_sanitized_tree_evaluates_the_same(case):
    clean = _clean(x={"id": "x", "type": "paragraph", "content": "hola", "show_if": case["tree"]})
    visible = set(case["visible"]) if "visible" in case else {"c", "t", "e"}
    assert fl.cond_tree_met(clean["x"]["show_if"], case["values"], lambda f: f in visible) is case["expected"]


@pytest.mark.parametrize("tree", V["sanitize_same"])
def test_old_and_new_condition_formats_survive_sanitizing_unchanged(tree):
    assert _clean(x={"id": "x", "type": "paragraph", "content": "hola", "show_if": tree})["x"]["show_if"] == tree


# ------------------------------------------------------------------ límites y colapso
def test_single_child_groups_collapse_but_named_groups_stay():
    one = {"match": "all", "rules": [_rule()]}
    assert _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": one})["x"]["show_if"] == _rule()
    named = {"match": "all", "name": "Costa", "rules": [_rule()]}
    assert _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": named})["x"]["show_if"]["name"] == "Costa"


def _deep(levels):
    node = _rule()
    for _ in range(levels):
        node = {"match": "all", "rules": [node, _rule(field="t", value="Empleado")]}
    return node


def test_depth_limit_is_three_levels_of_groups():
    _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": _deep(3)})
    with pytest.raises(ValueError, match="niveles"):
        _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": _deep(4)})


def test_leaf_and_group_size_limits():
    many = {"match": "any", "rules": [_rule(str(i)) for i in range(40)]}
    clean = _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": many})
    assert len(clean["x"]["show_if"]["rules"]) == fl.MAX_GROUP_RULES                      # hijos directos: se recorta
    big = {"match": "all", "rules": [{"match": "any", "rules": [_rule(str(i)) for i in range(10)]} for _ in range(3)]}
    _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": big})            # 30 hojas: justo el tope
    with pytest.raises(ValueError, match="30"):
        _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": {"match": "all", "rules": big["rules"] + [{"match": "any", "rules": [_rule("z"), _rule("y")]}]}})


def test_bad_rules_are_rejected():
    with pytest.raises(ValueError):
        _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": {"match": "all", "rules": [_rule(), {"field": "no_existe", "op": "equals", "value": "x"}]}})
    with pytest.raises(ValueError):
        _clean(x={"id": "x", "type": "paragraph", "content": "a", "show_if": _rule(field="x")})            # no puede depender de sí mismo


def test_cycles_are_still_detected_through_nested_groups():
    with pytest.raises(ValueError, match="círculo"):
        _clean(a={"id": "a", "type": "text_short", "label": "A", "show_if": {"match": "all", "rules": [_rule(field="b"), _rule()]}},
               b={"id": "b", "type": "text_short", "label": "B", "show_if": {"match": "any", "rules": [{"match": "all", "rules": [_rule(field="a"), _rule()]}, _rule()]}})


# ------------------------------------------------------------------ variantes por propiedad
def _variants(prop="content", n=2, default="por defecto"):
    return {prop: {"items": [{"when": _rule(OPTS[i % 5]), "value": f"texto {i}"} for i in range(n)], "default": default}}


def test_variants_exist_for_every_kind_of_element():
    got = _clean(
        p={"id": "p", "type": "paragraph", "content": "x", "variants": _variants("content")},
        h={"id": "h", "type": "heading", "content": "x", "variants": _variants("content")},
        i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": "acme/b.png"}], "default": "acme/c.png"}}},
        n={"id": "n", "type": "text_short", "label": "N", "variants": {**_variants("display_label"), **_variants("help"), **_variants("placeholder")}},
        pay={"id": "pay", "type": "payment", "label": "Pago", "pay": {"mode": "fixed", "amount": 2000}, "variants": _variants("display_label")},
        k={"id": "k", "type": "companions", "label": "Acomp", "max": 2, "min": 0, "person_fields": [{"id": "nombre", "label": "Nombre", "type": "text_short"}], "variants": _variants("help")},
    )
    for fid in ("p", "h", "n", "pay", "k"):
        assert got[fid]["variants"], fid
    assert set(got["n"]["variants"]) == {"display_label", "help", "placeholder"}
    assert got["i"]["variants"]["src"]["default"] == "acme/c.png"


def test_properties_that_do_not_belong_to_the_kind_are_dropped():
    assert "variants" not in _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": _variants("help")})["p"]
    assert "variants" not in _clean(n={"id": "n", "type": "text_short", "label": "N", "variants": _variants("content")})["n"]


def test_elements_without_variants_gain_no_keys():
    got = _clean(p={"id": "p", "type": "paragraph", "content": "x"}, n={"id": "n", "type": "text_short", "label": "N"})
    assert "variants" not in got["p"] and "variants" not in got["n"]


def test_values_are_sanitized_per_property():
    got = _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": {"content": {"items": [{"when": _rule(), "value": "<b>a</b><script>1</script>"}], "default": "<i>d</i><iframe></iframe>"}}},
                 n={"id": "n", "type": "text_short", "label": "N", "variants": {"placeholder": {"items": [{"when": _rule(), "value": "<b>x</b>"}]}, "help": {"items": [{"when": _rule(), "value": "<u>y</u><img src=x>"}]}}})
    assert got["p"]["variants"]["content"]["items"][0]["value"] == "<b>a</b>" and got["p"]["variants"]["content"]["default"] == "<i>d</i>"
    assert got["n"]["variants"]["placeholder"]["items"][0]["value"] == "<b>x</b>"          # el texto de ejemplo es texto plano: no se interpreta
    assert got["n"]["variants"]["help"]["items"][0]["value"] == "<u>y</u>"


@pytest.mark.parametrize("path", ["javascript:alert(1)", "../x.png", "https://evil.com/x.png", "a/b.svg", "x.png", ".h/x.png"])
def test_image_variants_only_accept_uploaded_image_paths(path):
    got = _clean(i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": path}], "default": path}}})
    assert "variants" not in got["i"]                       # ni la variante ni el valor por defecto quedan: la ruta se descarta


def test_variant_without_condition_is_dropped_and_names_are_kept():
    got = _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": {"content": {"items": [{"when": None, "value": "a"}, {"when": _rule(), "value": "b", "name": "Capital"}]}}})
    assert [i["value"] for i in got["p"]["variants"]["content"]["items"]] == ["b"] and got["p"]["variants"]["content"]["items"][0]["name"] == "Capital"


def test_variant_limits():
    ok = _variants("content", n=200)
    assert len(_clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": ok})["p"]["variants"]["content"]["items"]) == 200
    with pytest.raises(ValueError, match="200"):
        _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": _variants("content", n=201)})
    many = {f"p{i}": {"id": f"p{i}", "type": "paragraph", "content": "x", "variants": _variants("content", n=200)} for i in range(16)}      # 3200 en total
    with pytest.raises(ValueError, match="3000"):
        _clean(**many)


# ------------------------------------------------------------------ selección
def test_pick_first_match_then_default_then_nothing():
    f = _clean(p={"id": "p", "type": "paragraph", "content": "fijo", "variants": {"content": {"items": [
        {"when": _rule("Bogotá"), "value": "Sede Bogotá"}, {"when": _rule(["Apartadó", "Necoclí"], op="in"), "value": "Sede Urabá"}], "default": "Por confirmar"}}})["p"]
    pick = lambda c, visible=None: fl.pick_variant(f, "content", {"c": c}, visible)
    assert pick("bogota") == "Sede Bogotá" and pick("Necoclí") == "Sede Urabá" and pick("Cali") == "Por confirmar"
    assert pick("Bogotá", visible=set()) == "Por confirmar"
    f["variants"]["content"].pop("default")
    assert pick("Cali") is None                              # content sin variante ni valor por defecto: no ocupa espacio


def test_first_matching_variant_wins_and_empty_match_hides_content():
    f = {"variants": {"content": {"items": [{"when": _rule("Bogotá"), "value": ""}, {"when": _rule("Bogotá"), "value": "otra"}], "default": "d"}}, "content": "base"}
    assert fl.pick_variant(f, "content", {"c": "Bogotá"}) is None


@pytest.mark.parametrize("prop", ["display_label", "help", "placeholder"])
def test_non_hideable_properties_fall_back_to_their_own_value(prop):
    f = {prop: "propio", "variants": {prop: {"items": [{"when": _rule("Bogotá"), "value": "variante"}]}}}
    assert fl.pick_variant(f, prop, {"c": "Bogotá"}) == "variante"
    assert fl.pick_variant(f, prop, {"c": "Cali"}) == "propio"


def test_plain_element_without_variants_returns_its_own_value():
    assert fl.pick_variant({"content": "Hola"}, "content", {}) == "Hola"


# ------------------------------------------------------------------ formato de P2 (normalizador de una versión)
def test_p2_format_is_read_and_rewritten_to_the_new_one():
    legacy = {"by": "c", "items": [{"rule": _rule("Bogotá"), "content": "<b>Sede</b><script>1</script>"}], "default": "d"}
    got = _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": legacy})["p"]["variants"]
    assert got == {"content": {"items": [{"when": _rule("Bogotá"), "value": "<b>Sede</b>"}], "default": "d"}}
    f = {"variants": legacy}
    assert fl.pick_variant(f, "content", {"c": "bogota"}) == "<b>Sede</b><script>1</script>"             # leído sin reescribir: mismo resultado
    assert _clean(p={"id": "p", "type": "paragraph", "content": "x", "variants": got})["p"]["variants"] == got      # y es estable


# ------------------------------------------------------------------ imágenes: referencias vivas
def test_image_refs_count_variant_images_as_live_references():
    d = fl.sanitize_design({"fields": _fields(i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": "acme/b.png"}, {"when": _rule("Cali"), "value": "acme/c.png"}], "default": "acme/d.png"}}}), "rows": []}, set())
    paths = sorted(str(o[k]) for o, k in fl.image_refs(d))
    assert paths == ["acme/a.png", "acme/b.png", "acme/c.png", "acme/d.png"]


def test_image_refs_can_rewrite_paths_in_place():
    d = fl.sanitize_design({"fields": _fields(i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": "acme/b.png"}], "default": "acme/d.png"}}}), "rows": []}, set())
    for owner, key in fl.image_refs(d):
        owner[key] = "nuevo/" + owner[key].split("/")[-1]
    assert d["fields"]["i"]["src"] == "nuevo/a.png" and d["fields"]["i"]["variants"]["src"]["items"][0]["value"] == "nuevo/b.png" and d["fields"]["i"]["variants"]["src"]["default"] == "nuevo/d.png"


def test_form_export_and_event_export_both_find_variant_images():
    from app import event_transfer
    from app.routers import form_transfer
    d = fl.sanitize_design({"fields": _fields(i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": "acme/b.jpg"}], "default": "acme/d.webp"}}}), "rows": []}, set())
    s = fl.sanitize_settings({})
    owners = sorted(str(o[k]) for o, k in form_transfer._image_refs(d, s) if str(o[k]).startswith("acme/"))
    assert owners == ["acme/a.png", "acme/b.jpg", "acme/d.webp"]                              # exportar un formulario: viajan en el zip
    names = {m.group("name") for m in event_transfer._asset_re("acme").finditer(json.dumps(d))}
    assert names == {"a.png", "b.jpg", "d.webp"}                                             # exportar un evento: se leen del JSON del diseño


def test_duplicate_keeps_variant_images_because_it_copies_the_design_json():
    d = fl.sanitize_design({"fields": _fields(i={"id": "i", "type": "image", "src": "acme/a.png", "variants": {"src": {"items": [{"when": _rule(), "value": "acme/b.jpg"}]}}}), "rows": []}, set())
    copy = json.loads(json.dumps(d))                                                         # duplicar_form copia design_json tal cual (las rutas se comparten, no se duplican archivos)
    assert copy == d and "acme/b.jpg" in json.dumps(copy)
