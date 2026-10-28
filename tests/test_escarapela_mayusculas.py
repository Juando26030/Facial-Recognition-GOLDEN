"""Mayúsculas / minúsculas por texto (25-oct-2026): `text_case` se guarda en cada elemento de la plantilla, viaja con «Guardar como plantilla» e «Importar», y una
plantilla vieja (sin el campo) no cambia. Solo presentación: los datos de la persona no se tocan."""
import pathlib

from app.models import User
from tests.test_carga_por_pasos import login

TXT = {"type": "text_variable", "variable": "first_name", "x": 4, "y": 6, "width": 50, "height": 10, "font_family": "Roboto", "font_size": 14, "font_color": "#000000", "font_weight": "bold", "align": "center", "rotation": 0}


def _tpl(elements):
    return {"name": "P", "width_mm": 58.9, "height_mm": 100, "orientation": "vertical", "background_type": "color", "background_value": "#ffffff", "elements": elements}


def test_text_case_is_kept_on_save_save_as_and_import_and_old_templates_do_not_change(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev, other = factory.event("creado"), factory.event("creado")
    login(client, "coord1")
    vieja = dict(TXT, id="v")                                                                       # sin el campo: «como está en la base»
    els = [vieja, dict(TXT, id="u", text_case="upper", y=20), dict(TXT, id="t", type="text_static", content="feria de la ciudad", text_case="title", y=34)]
    assert client.put(f"/api/events/{ev.id}/badge-template", json=_tpl(els)).status_code == 200
    got = {e["id"]: e for e in client.get(f"/api/events/{ev.id}/badge-template").json()["elements"]}
    assert "text_case" not in got["v"] and got["u"]["text_case"] == "upper" and got["t"]["text_case"] == "title"
    assert got["v"] == vieja                                                                         # la plantilla vieja queda idéntica
    assert client.post(f"/api/events/{ev.id}/badge-template/save-as", json={"name": "Con mayúsculas"}).status_code == 200
    saved = [s for s in client.get(f"/api/events/{ev.id}/saved-badge-templates").json() if s["name"] == "Con mayúsculas"][0]
    assert client.post(f"/api/events/{other.id}/badge-template/import/{saved['id']}").status_code == 200
    imported = {e["id"]: e for e in client.get(f"/api/events/{other.id}/badge-template").json()["elements"]}
    assert imported["u"]["text_case"] == "upper" and imported["t"]["text_case"] == "title" and "text_case" not in imported["v"]


def test_it_is_only_presentation_the_person_data_is_not_changed(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    factory.person(ev, "1001", "maría josé", "de la torre")
    login(client, "coord1")
    assert client.put(f"/api/events/{ev.id}/badge-template", json=_tpl([dict(TXT, id="u", text_case="upper")])).status_code == 200
    db.expire_all()
    u = db.query(User).filter_by(id="1001", tenant_id=ev.tenant_id).one()
    assert (u.first_name, u.last_name) == ("maría josé", "de la torre")


def test_every_place_that_draws_a_template_uses_the_same_transformation():
    render = pathlib.Path("static/js/badge-render.js").read_text(encoding="utf-8")
    assert "const content = textContent(el, data);" in render and "function applyTextCase" in render
    for page in ("badge_editor", "badge_print", "kiosk_registro", "digital_badge", "certificate_public", "kiosk_certificados"):
        assert "js/badge-render.js" in pathlib.Path(f"templates/{page}.html").read_text(encoding="utf-8"), page     # todos dibujan con BadgeRender
    editor = pathlib.Path("templates/badge_editor.html").read_text(encoding="utf-8")
    assert 'id="p_case"' in editor and 'id="p_case_all"' in editor and "['as_is', 'Como está'" in editor
