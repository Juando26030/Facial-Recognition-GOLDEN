"""Formulario de persona POR CATEGORÍA (19-nov-2026): obligatorios y campos ocultos distintos según la categoría, sin tocar el formulario general."""
import pytest

from app import personform as pf

CFGS = [
    {"key": "id", "label": "Cédula", "field_type": "text_short", "required": True},
    {"key": "first_name", "label": "Nombres", "field_type": "text_short", "required": True},
    {"key": "email", "label": "Correo", "field_type": "email", "required": False},
    {"key": "role", "label": "Cargo", "field_type": "text_short", "required": True},
    {"key": "categories", "label": "Categoría", "field_type": "categories", "required": False},
]


def _variant(**fields):
    return {"sheets": [], "rows": [], "fields": fields}


def test_obligatorio_propio_de_la_categoria():
    e = pf.effective_variant(_variant(email={"required": True}, role={"required": False}), CFGS)
    assert e["fields"]["email"]["required"] is True
    assert e["fields"]["role"]["required"] is False          # el general lo exige; esta categoría no
    assert e["fields"]["id"]["required"] and e["fields"]["first_name"]["required"]


def test_lo_que_la_categoria_no_dice_hereda_el_evento():
    e = pf.effective_variant(_variant(), CFGS)
    assert e["fields"]["role"]["required"] is True and e["fields"]["email"]["required"] is False


def test_campo_oculto_no_se_exige_ni_se_ve():
    e = pf.effective_variant(_variant(role={"hidden": True}), CFGS)
    assert e["fields"]["role"]["hidden"] is True and e["fields"]["role"]["required"] is False


def test_cedula_nombre_y_categoria_nunca_se_ocultan():
    e = pf.effective_variant(_variant(id={"hidden": True}, first_name={"hidden": True}, categories={"hidden": True}), CFGS)
    assert not any(e["fields"][k].get("hidden") for k in ("id", "first_name", "categories"))
    assert e["fields"]["id"]["required"] and e["fields"]["first_name"]["required"]


def test_un_obligatorio_no_puede_depender_de_otro_campo():
    v = _variant(email={"required": True, "show_if": {"field": "role", "op": "equals", "value": "x"}})
    assert pf.effective_variant(v, CFGS) is None or "show_if" not in pf.effective_variant(v, CFGS)["fields"]["email"]


def test_sanitize_general_ignora_hidden():
    clean = pf.sanitize({"fields": {"role": {"hidden": True}}}, CFGS)
    assert "hidden" not in clean["fields"].get("role", {})


def test_variantes_solo_de_categorias_del_evento():
    out = pf.sanitize_variants({"variants": {"VIP": _variant(), "Fantasma": _variant()}}, CFGS, ["VIP", "General"])
    assert list(out) == ["VIP"]


def test_for_category():
    base = {"enabled": True, "form_version": 4, "fields": {}, "variants": {"VIP": pf.effective_variant(_variant(email={"required": True}), CFGS)}}
    vip = pf.for_category(base, "VIP")
    assert vip["category"] == "VIP" and vip["form_version"] == 4 and vip["fields"]["email"]["required"] is True
    assert pf.for_category(base, "Otra") is base and pf.for_category(base, None) is base


def test_person_configs(monkeypatch):
    monkeypatch.setattr(pf, "env_enabled", lambda: True)
    stored = {"enabled": True, "variants": {"VIP": _variant(email={"required": True}, role={"hidden": True})}}
    out = {c["key"]: c for c in pf.person_configs(None, None, CFGS, ["VIP"], stored=stored)}
    assert out["email"]["required"] is True and out["role"]["required"] is False and out["role"]["hidden"] is True
    assert pf.person_configs(None, None, CFGS, ["Otra"], stored=stored) is CFGS          # sin formulario propio: el general
    assert pf.person_configs(None, None, CFGS, [], stored=stored) is CFGS
    assert pf.person_configs(None, None, CFGS, ["VIP"], stored={"enabled": False, "variants": stored["variants"]}) is CFGS


def test_person_configs_con_entorno_apagado(monkeypatch):
    monkeypatch.setattr(pf, "env_enabled", lambda: False)
    assert pf.person_configs(None, None, CFGS, ["VIP"], stored={"enabled": True, "variants": {"VIP": _variant()}}) is CFGS


@pytest.mark.parametrize("raw", [None, "x", []])
def test_sanitize_variants_tolera_basura(raw):
    assert pf.sanitize_variants({"variants": raw}, CFGS, ["VIP"]) == {}
