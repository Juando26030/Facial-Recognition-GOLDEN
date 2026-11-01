"""P3: texto con formato — lista blanca, textos viejos sin cambios, XSS y límites (mismos casos en tests/js/rich_text_check.js)."""
import json
from pathlib import Path

import pytest

from app import formlib, richtext

V = json.loads((Path(__file__).parent / "rich_vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("text", V["plain"])
def test_old_plain_texts_are_not_formatted_and_stay_identical(text):
    assert not richtext.has_format(text)
    assert richtext.clean_text(text, 2000) == text.strip()


@pytest.mark.parametrize("src,out", V["clean"])
def test_sanitize_vectors(src, out):
    assert richtext.has_format(src)
    assert richtext.sanitize(src) == out
    assert richtext.sanitize(out) == out                         # idempotente: guardar, exportar, importar y volver a guardar no lo cambia


@pytest.mark.parametrize("src,out", V["basic"])
def test_basic_mode_for_field_help(src, out):
    assert richtext.sanitize(src, basic=True) == out


@pytest.mark.parametrize("src", V["attacks"])
def test_xss_payloads_leave_nothing_executable(src):
    out = richtext.sanitize(src).lower() if richtext.has_format(src) else ""
    for bad in V["forbidden"]:
        assert bad not in out, (src, out)
    if out:
        assert richtext.sanitize(out) == out


@pytest.mark.parametrize("src,out", V["plain_out"])
def test_to_plain(src, out):
    assert richtext.to_plain(src) == out


def test_too_long_formatted_text_is_rejected_and_plain_is_cut_as_before():
    with pytest.raises(ValueError):
        richtext.sanitize("<b>" + "x" * 9000 + "</b>")
    assert len(richtext.clean_text("x" * 5000, 2000)) == 2000


def test_fonts_are_only_the_hosted_ones():
    assert "Roboto" in richtext.hosted_fonts() and len(richtext.hosted_fonts()) >= 40
    assert richtext.clean_style("font-family:Arial") == ""
    assert richtext.clean_style("font-family:'Open Sans'") == "font-family:'Open Sans'"


def test_colors_only_hex_or_rgb():
    for ok in ("#fff", "#FFAA00", "rgb(0,0,0)", "rgba(1,2,3,0.5)"):
        assert richtext.clean_style(f"color:{ok}")
    for bad in ("red", "url(x)", "var(--x)", "hsl(1,2%,3%)", "currentColor", "#ggg", "rgb(1,2)", "expression(1)"):
        assert richtext.clean_style(f"color:{bad}") == ""


# ------------------------------------------------------------------ dónde se aplica en el diseño y los ajustes
def _design(fields):
    return formlib.sanitize_design({"fields": fields, "rows": []}, set())["fields"]


def test_design_content_and_help_are_sanitized():
    assert _design({"t": {"id": "t", "type": "paragraph", "content": "<b>Hola</b><script>alert(1)</script>"}})["t"]["content"] == "<b>Hola</b>"
    assert _design({"t": {"id": "t", "type": "paragraph", "content": "menores de <18 años"}})["t"]["content"] == "menores de <18 años"
    n = _design({"n": {"id": "n", "type": "text_short", "label": "Nombre", "help": "<b>ojo</b><p>x</p><img src=x>"}})["n"]
    assert n["help"] == "<b>ojo</b>x"                             # ayuda: formato básico
    assert _design({"n": {"id": "n", "type": "text_short", "label": "Nombre", "help": "Solo texto <18"}})["n"]["help"] == "Solo texto <18"


def test_variants_content_is_sanitized():
    c = {"id": "c", "type": "select", "label": "Ciudad", "options": ["Bogotá"]}
    v = {"by": "c", "items": [{"rule": {"field": "c", "op": "equals", "value": "Bogotá"}, "content": "<i>x</i><script>1</script>"}], "default": "<u>d</u><iframe></iframe>"}
    got = _design({"c": c, "t": {"id": "t", "type": "paragraph", "variants": v}})["t"]["variants"]
    assert got["items"][0]["content"] == "<i>x</i>" and got["default"] == "<u>d</u>"


def test_thanks_and_closed_texts_are_sanitized_and_titles_stay_plain():
    s = formlib.sanitize_settings({"thanks": {"text": "<b>Gracias</b><script>1</script>", "title": "<b>T</b>"}, "closed_template": {"text": "Cerrado <18"}})
    assert s["thanks"]["text"] == "<b>Gracias</b>" and s["closed_template"]["text"] == "Cerrado <18"
    assert s["thanks"]["title"] == "<b>T</b>"                    # el título sigue siendo texto plano (se pinta escapado)
