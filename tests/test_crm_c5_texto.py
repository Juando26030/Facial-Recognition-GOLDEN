"""Reglas del frontend del diseñador del PDF (texto, sin navegador)."""
import pathlib
import re

R = pathlib.Path(__file__).resolve().parent.parent
JS = (R / "static/js/crm_plantilla.js").read_text(encoding="utf-8")
HOJA = (R / "static/js/crm_plantilla_hoja.js").read_text(encoding="utf-8")
CSS = (R / "static/css/p-crm-c5.css").read_text(encoding="utf-8")
PROD = (R / "static/js/crm_productos.js").read_text(encoding="utf-8")
HTML = (R / "templates/crm_plantilla.html").read_text(encoding="utf-8")


def test_sin_apis_prohibidas():
    for src in (JS, PROD, HOJA):
        assert not re.search(r"\b(alert|confirm|prompt)\(", src.replace("showConfirm(", ""))
        assert "innerHTML" not in src and "setTimeout" not in src and "setInterval" not in src and "onclick" not in src


def test_css_solo_tokens():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert "--gw-" in CSS


def test_pagina_y_enlaces():
    assert "js/crm_plantilla.js" in HTML and "css/p-crm-c5.css" in HTML
    assert "/disenar" in PROD and "/image" in PROD
    assert "debounce" in JS and "/preview" in JS and "doc-layout/starter" in JS
