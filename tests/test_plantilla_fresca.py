"""La plantilla que se imprime es SIEMPRE la vigente (25-oct-2026: tras cambiar la orientación en el diseñador, la primera etiqueta de un Registro ya abierto pudo salir con la anterior)."""
import pathlib
import time

from tests.test_carga_por_pasos import login

H = {"name": "P", "width_mm": 100, "height_mm": 58.9, "orientation": "horizontal", "background_type": "color", "background_value": "#ffffff",
     "elements": [{"id": "q", "type": "qr", "variables": ["id"], "x": 74, "y": 6, "width": 20, "height": 20, "rotation": 0}]}


def test_the_template_is_never_cached_and_its_version_changes_when_it_is_saved(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    assert client.put(f"/api/events/{ev.id}/badge-template", json=H).status_code == 200
    first = client.get(f"/api/events/{ev.id}/badge-template?_=1")
    assert first.headers["cache-control"] == "no-store" and first.json()["updated_at"]
    time.sleep(0.01)
    assert client.put(f"/api/events/{ev.id}/badge-template", json=dict(H, width_mm=58.9, height_mm=100, orientation="vertical")).status_code == 200
    second = client.get(f"/api/events/{ev.id}/badge-template?_=2").json()
    assert (second["width_mm"], second["height_mm"], second["orientation"]) == (58.9, 100, "vertical")         # el siguiente pedido ya trae la nueva
    assert second["updated_at"] != first.json()["updated_at"]


def test_every_print_path_asks_for_the_current_template_each_time():
    render = pathlib.Path("static/js/badge-render.js").read_text(encoding="utf-8")
    assert "function fetchTemplate" in render and "cache: 'no-store'" in render and "qs.set('_', String(Date.now()))" in render
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "BadgeRender.fetchTemplate(EID, data.template_category)" in sp                                   # USB propio y la impresora compartida (Y): en cada etiqueta
    assert "fetch(`/api/events/${EID}/badge-template" not in sp                                             # ningún otro camino con su propia copia
    assert "loadPreviewTemplate(true)" in sp                                                                 # la vista previa del panel también se renueva
    bp = pathlib.Path("templates/badge_print.html").read_text(encoding="utf-8")
    assert "BadgeRender.fetchTemplate(EVENT_ID, data.template_category)" in bp                               # la impresión del navegador
