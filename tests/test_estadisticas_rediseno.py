"""Rediseño de Estadísticas (26-nov-2026): registro principal → inventario principal → zonas principal → información detallada (plegada) → gráficos por variable.
Inventario por producto: entregadas «de» lo que había y lo que queda (el porcentaje es sobre ESE producto); zonas: personas sobre los registrados."""
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.conftest import login  # noqa: F401
from tests.test_stats_links import _token
from tests.test_subcategorias import _area, _deliver, _item, _move, _setup


def _registered(db, ev, *ids):
    from app.models import AccessLog
    from app.timeutil import utcnow
    for uid in ids:
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional", timestamp=utcnow()))
    db.commit()

ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL = (ROOT / "templates" / "kiosk_estadisticas.html").read_text(encoding="utf-8")
DASH = (ROOT / "static" / "js" / "analytics-dashboard.js").read_text(encoding="utf-8")
CTRL = (ROOT / "static" / "js" / "stats-control.js").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------ orden y plegable (sin base)

def test_page_order_registro_inventario_zonas_detalle_variables():
    pos = [TPL.index(x) for x in ('id="analyticsRegistro"', 'id="statsInv"', 'id="statsZones"', 'id="statsDetail"', 'id="gwStatsVarTitle"')]
    assert pos == sorted(pos)


def test_detail_is_a_closed_details_and_the_dashboard_sends_detail_there():
    m = re.search(r'<details[^>]*id="statsDetail"[^>]*>', TPL)
    assert m and " open" not in m.group(0)
    assert "Información detallada del registro" in TPL
    assert "detailHost: document.getElementById('analyticsRegistroDetail')" in TPL and "onData: GWStatsControl.render" in TPL
    assert "kpis.filter((k) => !k.detail)" in DASH and "opts.onData" in DASH


def test_inventory_and_zone_sections_start_hidden():
    assert re.search(r'id="statsInv"[^>]*hidden', TPL) and re.search(r'id="statsZones"[^>]*hidden', TPL)
    assert "stats-control.js" in TPL


def test_control_js_parses():
    if not shutil.which("node"):
        pytest.skip("sin node")
    subprocess.run(["node", "--check", str(ROOT / "static" / "js" / "stats-control.js")], check=True)
    assert "entregada(s) · quedan" in CTRL and "Personas atendidas" in CTRL and "Unidades entregadas" in CTRL


# ------------------------------------------------------------------------------------------ cifras (con base)

def test_registro_kpis_split_main_and_detail(client, factory, db):
    ev = _setup(client, factory)
    _registered(db, ev, "1001")
    d = client.get(f"/api/events/{ev.id}/analytics/registro").json()
    main = [k["label"] for k in d["kpis"] if not k.get("detail")]
    detail = [k["label"] for k in d["kpis"] if k.get("detail")]
    assert main[:3] == ["Base del evento", "Registrados", "Pendientes"]
    assert "Vienen del Excel (base)" in main                                  # el personal ve el origen de la base desde el inicio
    assert "Primer registro" not in main and all(x not in main for x in ("Hora pico", "Último registro", "Ritmo promedio"))
    assert set(detail) <= {"Primer registro", "Último registro", "Hora pico", "Ritmo promedio"}


def test_inventory_summary_per_product_over_its_own_stock(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Alimentación", qty=0)
    maz = _item(client, ev, "Mazorcada", parent_id=comida["id"], qty=10)
    _item(client, ev, "Lechona", parent_id=comida["id"], qty=5)
    muffin = _item(client, ev, "Muffin", qty=4)
    assert _deliver(client, ev, "1001", (maz["id"], 1), (muffin["id"], 1)).status_code == 200
    assert _deliver(client, ev, "1002", (maz["id"], 1)).status_code == 200
    inv = client.get(f"/api/events/{ev.id}/analytics/registro").json()["control"]["inventory"]
    assert inv["units"] == 3 and inv["people"] == 2 and inv["initial"] == 19 and inv["remaining"] == 16
    g = inv["groups"][0]
    assert g["name"] == "Alimentación" and g["units"] == 2 and g["people"] == 2 and g["initial"] == 15 and g["remaining"] == 13
    rows = {r["name"]: r for r in g["items"]}
    assert rows["Mazorcada"] == {"name": "Mazorcada", "delivered": 2, "initial": 10, "remaining": 8, "pct": 20.0}
    assert rows["Lechona"]["delivered"] == 0 and rows["Lechona"]["pct"] == 0.0
    assert inv["items"][0]["name"] == "Muffin" and inv["items"][0]["delivered"] == 1 and inv["items"][0]["remaining"] == 3 and inv["items"][0]["pct"] == 25.0


def test_inventory_summary_hidden_when_module_off_and_respects_the_stats_toggle(client, factory):
    ev = _setup(client, factory)
    _item(client, ev, "Visible", qty=2)
    _item(client, ev, "Oculto", qty=2, stats_enabled=False)
    inv = client.get(f"/api/events/{ev.id}/analytics/registro").json()["control"]["inventory"]
    assert [r["name"] for r in inv["items"]] == ["Visible"]
    client.put(f"/api/events/{ev.id}/modules", json={"inventory_enabled": False, "areas_enabled": False})
    c = client.get(f"/api/events/{ev.id}/analytics/registro").json()["control"]
    assert c == {"inventory": None, "zones": None}


def test_zones_summary_people_over_registered(client, factory, db):
    ev = _setup(client, factory)
    _registered(db, ev, "1001", "1002")
    salon = _area(client, ev, "Salón")
    a = _area(client, ev, "Puerta A", parent_id=salon["id"])
    vip = _area(client, ev, "VIP")
    assert _move(client, ev, a["id"], "1001")["result"] == "OK"
    assert _move(client, ev, vip["id"], "1002")["result"] == "OK"
    assert _move(client, ev, vip["id"], "1002", "out")["result"] == "OK"
    d = client.get(f"/api/events/{ev.id}/analytics/registro").json()
    registered = next(k["value"] for k in d["kpis"] if k["label"] == "Registrados")
    zs = d["control"]["zones"]
    assert registered == 2 and zs["registered"] == 2 and zs["people"] == 2 and zs["inside"] == 1 and zs["entries"] == 2 and zs["exits"] == 1
    z = {x["name"]: x for x in zs["zones"]}
    assert z["Salón"]["people"] == 1 and z["Salón"]["inside"] == 1 and z["Salón"]["children"][0]["name"] == "Puerta A"
    assert z["VIP"]["inside"] == 0 and z["VIP"]["exits"] == 1


def test_inventory_and_zone_variables_are_no_longer_added_by_themselves(client, factory):
    ev = _setup(client, factory)
    _item(client, ev, "Muffin", qty=4)
    _area(client, ev, "VIP")
    vs = [v for v in client.get(f"/api/events/{ev.id}/stats/variables").json() if v["key"].startswith(("inv:", "zona:"))]
    assert vs and all(v["default_stat_enabled"] is False for v in vs)          # siguen en la lista para elegirlas


def test_public_link_gets_the_control_summary_but_not_the_origin(client, factory):
    ev = _setup(client, factory)
    _item(client, ev, "Muffin", qty=4)
    r = client.post(f"/api/events/{ev.id}/stats-links", json={"scope": "event"})
    assert r.status_code == 200, r.text
    token = _token(r.json()["url"])
    d = client.get(f"/api/ver/{token}/analytics/registro").json()
    assert d["control"]["inventory"]["items"][0]["name"] == "Muffin"
    assert not any(k["label"].startswith("Vienen del Excel") for k in d["kpis"])


# ------------------------------------------------------------------------------------------ hotfix 26-nov-2026: motivos reales al entregar

def test_limit_message_says_what_the_person_already_received(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Alimentación", qty=0, max_per_person=1)
    maz = _item(client, ev, "Mazorcada", parent_id=comida["id"], qty=10, max_per_person=1)
    lech = _item(client, ev, "Lechona", parent_id=comida["id"], qty=10, max_per_person=1)
    muffin = _item(client, ev, "Muffin", qty=10, max_per_person=1)
    assert _deliver(client, ev, "1001", (maz["id"], 1), (muffin["id"], 1)).status_code == 200
    for again in (maz, lech):                                                       # la misma u otra opción del grupo: el motivo es el grupo y dice cuál recibió
        r = _deliver(client, ev, "1001", (again["id"], 1))
        assert r.status_code == 409 and r.json()["detail"] == "Esta persona ya recibió «Alimentación»: Mazorcada. Solo se permite 1 por persona.", r.json()
    r = _deliver(client, ev, "1001", (muffin["id"], 1))
    assert r.status_code == 409 and r.json()["detail"] == "Esta persona ya recibió «Muffin». Solo se permite 1 por persona."


def test_code_only_event_still_delivers_to_the_picked_person_and_gives_the_real_reason(client, factory, db):
    from app.models import EventAttendee
    ev = _setup(client, factory)
    client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_search_only": True})
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").first().code = "2020"
    db.commit()
    muffin = _item(client, ev, "Muffin", qty=10, max_per_person=1)
    assert _deliver(client, ev, "1001", (muffin["id"], 1)).status_code == 200          # la pantalla manda la cédula de la persona elegida por su código
    r = _deliver(client, ev, "1001", (muffin["id"], 1))
    assert r.status_code == 409 and "ya recibió «Muffin»" in r.json()["detail"]        # antes: 404 «no está en la base de este evento»
    assert _deliver(client, ev, "999999", (muffin["id"], 1)).status_code == 404        # quien no está inscrito sigue sin estar


# ------------------------------------------------------------------------------------------ 26-nov-2026: historial por persona y pantalla de entrega

def test_person_history_is_only_for_coordinators_and_returns_everything(client, factory):
    ev = _setup(client, factory)
    muffin = _item(client, ev, "Muffin", qty=10)
    agua = _item(client, ev, "Agua", qty=10)
    assert _deliver(client, ev, "1001", (muffin["id"], 1), (agua["id"], 1)).status_code == 200
    assert _deliver(client, ev, "1002", (agua["id"], 1)).status_code == 200
    r = client.get(f"/api/events/{ev.id}/inventory/deliveries/person", params={"cedula": "1001"})
    assert r.status_code == 200 and r.json()["person"]["id"] == "1001"
    assert sorted(d["item"] for d in r.json()["deliveries"]) == ["Agua", "Muffin"] and all(d["user_id"] == "1001" for d in r.json()["deliveries"])
    assert client.get(f"/api/events/{ev.id}/inventory/deliveries/person", params={"cedula": "999999"}).status_code == 404
    dig = factory.staff("digitador", "9990001")
    factory.authorize(ev, dig)
    client.post("/logout")
    login(client, "9990001")
    assert client.get(f"/api/events/{ev.id}/inventory/deliveries/person", params={"cedula": "1001"}).status_code == 403


def test_inventory_screen_pieces():
    tpl = (ROOT / "templates" / "kiosk_inventario.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "inventario.js").read_text(encoding="utf-8")
    assert '{% if staff_role not in ["digitador", "cliente"] %}' in tpl and 'id="histInput"' in tpl and 'id="histScanBtn"' in tpl
    assert "Estás entregando:" in js and "Se le entrega:" not in js
    assert "function delTable" in js and "<th scope=\"col\">Fecha y hora</th>" in js
    assert "onTyping:" in js and "function clearPerson" in js
