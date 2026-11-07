"""Enlace de la Fase 2: plantilla -> Nuevo evento -> calendario (tarjeta diseñada) -> Editar evento. Camino de datos (API) y cableado de las pantallas (fuentes)."""
import copy
import re
from pathlib import Path

import pytest

from tests.conftest import login
from tests.test_event_template import _body, _custom, _make_template, _payload

ROOT = Path(__file__).resolve().parent.parent
read = lambda *p: (ROOT.joinpath(*p)).read_text(encoding="utf-8")


@pytest.fixture()
def admin(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    return client


# ------------------------------------------------------------------ datos: lo que el calendario necesita para pintar la tarjeta
def test_calendar_api_returns_extra_switches_and_names_for_the_card(admin, factory):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    _make_template(admin, _custom(), _custom(key="c_valor", type_="money", title="Valor"), _custom(key="c_pais", type_="country", title="País sede"), place=["c_tipo", "c_valor", "c_pais"])
    r = admin.post("/api/events", json={**_payload(coord.id, commercial_staff_id=com.id), "inventory_enabled": True, "facial_enabled": False,
                                        "extra": {"c_tipo": "Feria", "c_valor": "2500000", "c_pais": "México"}})
    assert r.status_code == 200, r.text
    rows = admin.get("/api/events/calendar?start=2026-11-01&end=2026-11-30").json()
    ev = [e for e in rows if e["id"] == r.json()["id"]][0]
    assert ev["extra"] == {"c_tipo": "Feria", "c_valor": 2500000, "c_pais": "México"}
    assert ev["switches"]["inventory_enabled"] is True and ev["switches"]["facial_enabled"] is False          # misma fuente que Parámetros
    assert ev["coordinator_name"] and ev["commercial_name"] and ev["tenant_name"] and ev["city"] == "Bogotá"


@pytest.mark.parametrize("role,ok", [("coordinador", True), ("comercial", True), ("admin", True), ("digitador", False), ("cliente", False)])
def test_calendar_roles_can_read_the_template_they_need(client, factory, role, ok):
    """Quien ve el calendario puede pedir la plantilla (si no, la tarjeta cae al diseño de siempre)."""
    factory.tenant("acme")
    factory.staff(role, "actor1")
    login(client, "actor1")
    assert (client.get("/api/event-template").status_code == 200) is ok


def test_card_data_follows_edit_and_retired_fields(admin, factory):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    _make_template(admin, _custom(), _custom(key="c_nota", type_="text_short", title="Nota"), place=["c_tipo", "c_nota"])
    ev = admin.post("/api/events", json={**_payload(coord.id, commercial_staff_id=com.id), "extra": {"c_tipo": "Feria", "c_nota": "hola"}}).json()
    assert admin.patch(f"/api/events/{ev['id']}", json={"extra": {"c_nota": "otra"}}).status_code == 200          # lo que hace «Editar evento»
    tpl = admin.get("/api/event-template").json()
    body = _body(tpl)
    body["fields"] = [f for f in body["fields"] if f["key"] != "c_nota"]          # el admin retira el campo
    assert admin.put("/api/event-template", json=body).status_code == 200
    row = [e for e in admin.get("/api/events/calendar?start=2026-11-01&end=2026-11-30").json() if e["id"] == ev["id"]][0]
    assert row["extra"]["c_nota"] == "otra"                           # el dato se conserva; la tarjeta lo omite porque el campo está retirado
    retired = [f for f in admin.get("/api/event-template").json()["fields"] if f["key"] == "c_nota"][0]
    assert retired["retired"] is True


# ------------------------------------------------------------------ cableado de las pantallas
def test_calendar_page_loads_template_once_with_fallback():
    page = read("templates", "calendario.html")
    assert page.count("fetch('/api/event-template'") == 1 and "EventFields.calendarLayout(" in page          # una sola petición
    assert "cardLayoutPromise" in page and "CARD_LAYOUT = null" in page                                       # caché y respaldo
    assert "renderCalendarCard(e, CARD_LAYOUT)" in page
    assert "loadCardLayout()" in page


def test_new_event_page_passes_geo_data_and_scripts():
    page = read("templates", "nuevo_evento.html")
    assert "data-geo-url=\"{{ url_for('static', path='data/geo.json') }}\"" in page
    for s in ("js/gw-geo.js", "js/gw-combobox.js", "js/event-field-render.js", "js/color-library.js"):
        assert f"path='{s}'" in page
    js = read("static", "js", "nuevo-evento.js")
    assert "geoUrl: root.dataset.geoUrl" in js


def test_edit_modal_shows_and_saves_template_fields():
    m = read("templates", "_event_edit_modal.html")
    assert 'id="eeExtraBody"' in m and "/api/event-template" in m
    assert "EF.diffExtra(" in m and "payload.extra = got.extra" in m
    assert "EF.geoPair(form.country, form.city" in m
    for s in ("js/event-field-render.js", "js/gw-geo.js", "js/gw-combobox.js", "css/gw-event-fields.css"):
        assert f"path='{s}'" in m
    assert "name=\"coordinator_label\"" in m and "name=\"bandana_color\"" in m          # los campos base siguen donde estaban
    assert "onclick=" not in m and "confirm(" not in re.sub(r"showConfirm\(", "", m)


def test_hooks_for_map_and_inventory_widgets_are_conditional():
    js = read("static", "js", "event-field-render.js")
    assert "if (root.GWMap) root.GWMap.enhance(el, opts)" in js and "if (root.GWInventory) root.GWInventory.enhance(el, opts)" in js


def test_calendar_card_has_one_contract():
    js = read("static", "js", "calendar-card.js")
    assert "CONTRATO ÚNICO" in js and "EventFields.calendarLayout" in js and "cardModel" in js
