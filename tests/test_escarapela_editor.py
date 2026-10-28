"""Diseñador de escarapelas (orden del 24-oct-2026): giro guardado y leído, plantillas viejas sin ángulo, scripts nuevos servidos y fuentes cargadas antes de imprimir."""
import pathlib

from tests.test_carga_por_pasos import login

TEXT = {"type": "text_static", "content": "Hola", "font_family": "Lato", "font_size": 12, "font_color": "#000000", "font_weight": "normal", "align": "left", "z_index": 1}


def _put(client, ev, elements, w=62, h=100, orientation="vertical"):
    return client.put(f"/api/events/{ev.id}/badge-template", json={"name": "Prueba", "width_mm": w, "height_mm": h, "orientation": orientation, "background_type": "color", "background_value": "#ffffff", "elements": elements})


def test_rotation_is_saved_and_read_back_and_an_old_template_without_angle_still_reads(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    old = dict(TEXT, id="vieja", x=5, y=5, width=30, height=8)                                  # plantilla de antes: sin «rotation»
    turned = dict(TEXT, id="girada", x=10, y=30, width=40, height=10, rotation=90)
    free = dict(TEXT, id="libre", x=10, y=60, width=40, height=10, rotation=37.5)
    assert _put(client, ev, [old, turned, free]).status_code == 200
    back = {e["id"]: e for e in client.get(f"/api/events/{ev.id}/badge-template").json()["elements"]}
    assert "rotation" not in back["vieja"] or back["vieja"]["rotation"] in (0, None)            # se lee como 0°: el dibujo usa `rotation || 0`
    assert back["girada"]["rotation"] == 90 and back["libre"]["rotation"] == 37.5


def test_the_size_and_orientation_the_editor_sends_are_stored_together(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    assert _put(client, ev, [dict(TEXT, id="a", x=8, y=5, width=12, height=50)], w=100, h=62, orientation="horizontal").status_code == 200
    t = client.get(f"/api/events/{ev.id}/badge-template").json()
    assert (t["width_mm"], t["height_mm"], t["orientation"]) == (100, 62, "horizontal")
    assert (t["elements"][0]["x"], t["elements"][0]["width"], t["elements"][0]["height"]) == (8, 12, 50)


def test_the_editor_page_loads_the_new_scripts_and_they_are_served(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}/escarapela")
    assert page.status_code == 200
    for name in ("js/badge-geometry.js", "js/font-picker.js", "js/fonts-propias.js"):
        assert name in page.text and client.get(f"/static/{name}").status_code == 200, name
    for marker in ('id="magnetBtn"', 'id="selOverlay"', 'id="orientNotice"', "BadgeGeometry"):
        assert marker in page.text, marker


def test_every_print_path_waits_for_the_chosen_fonts_before_drawing():
    assert "loadFonts" in pathlib.Path("static/js/badge-render.js").read_text(encoding="utf-8")
    assert "await BadgeRender.loadFonts(template)" in pathlib.Path("static/js/label-compose.js").read_text(encoding="utf-8")        # QL-800 por USB y ventana de impresión (html2canvas): composición compartida
    assert "await BadgeRender.loadFonts(template)" in pathlib.Path("templates/badge_print.html").read_text(encoding="utf-8")        # impresión del navegador
    assert "BadgeRender.loadFonts(template)" in pathlib.Path("templates/badge_editor.html").read_text(encoding="utf-8")
