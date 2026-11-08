"""Color de marca por evento (0098): validación del hex, nulo = general de Golden, aplicación en las páginas públicas y contraste."""
import pytest

from app import brandcolor
from app.models import AuditAction
from tests.conftest import login


@pytest.mark.parametrize("raw,expected", [("#1E2A6E", "#1e2a6e"), ("1e2a6e", "#1e2a6e"), ("#a3f", "#aa33ff"), ("  #C0392B ", "#c0392b")])
def test_normalize_acepta_formas_validas(raw, expected):
    assert brandcolor.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "rojo", "#12345", "#gggggg", "#1234567", "red;}</style><script>"])
def test_normalize_rechaza_basura(raw):
    with pytest.raises(ValueError):
        brandcolor.normalize(raw)


def test_contraste_elige_texto_y_rechaza_lo_ilegible():
    assert brandcolor.text_on("#1e2a6e") == brandcolor.LIGHT_TEXT          # fondo oscuro, texto blanco
    assert brandcolor.text_on("#e8c25a") == brandcolor.DARK_TEXT           # dorado claro, texto marino
    assert brandcolor.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert brandcolor.validate("#1E2A6E") == "#1e2a6e"
    with pytest.raises(ValueError):
        brandcolor.validate("#808080")                                      # gris medio: ni blanco (3,95) ni marino (4,08) llegan a 4,5:1


def test_css_nulo_o_invalido_es_el_general_de_golden():
    assert brandcolor.css(None) == "" and brandcolor.css("") == "" and brandcolor.css("#808080") == ""
    out = brandcolor.css("#1e2a6e")
    assert "--gw-gold-grad:#1e2a6e" in out and "--gw-on-gold:#ffffff" in out and "--gold:#1e2a6e" in out


def test_endpoint_guarda_audita_y_vuelve_al_general(client, factory, db):
    factory.staff("admin", username="adm")
    ev = factory.event("en_proceso")
    login(client, "adm")
    url = f"/api/events/{ev.id}/brand-color"
    assert client.put(url, json={"color": "#C0392B"}).json() == {"brand_color": "#c0392b"}
    assert db.query(AuditAction).filter_by(entity="event_brand_color", entity_id=str(ev.id)).count() == 1
    assert client.put(url, json={"color": "azul"}).status_code == 400
    assert client.put(url, json={"color": "#808080"}).status_code == 400
    db.refresh(ev)
    assert ev.brand_color == "#c0392b"
    assert client.put(url, json={"color": None}).json() == {"brand_color": None}
    db.refresh(ev)
    assert ev.brand_color is None


def test_pagina_publica_aplica_la_variable(client, factory, db):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, brand_color="#1e2a6e")
    html = client.get(f"/aceptar/{ev.event_code}").text
    assert "--gold:#1e2a6e" in html and "--on-gold:#ffffff" in html


def test_pagina_publica_sin_color_no_agrega_estilo(client, factory):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True)
    assert "--on-gold:#" not in client.get(f"/aceptar/{ev.event_code}").text
