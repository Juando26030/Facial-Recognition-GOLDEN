"""Impresión compartida con los parámetros del equipo que pide y «Espejo» con el significado corregido (orden del 24-oct-2026)."""
import json
import uuid

from app.models import PrintJob
from app.routers import print_settings
from tests.test_impresion_compartida import _as, _beat, _route, setup  # noqa: F401 — `setup` es la misma fixture (evento con dos registradores y dos impresoras)

X1_PREFS = {"cut": False, "feedMm": 4, "lengthMm": None, "mirror": True, "invert": False, "tapeWidth": 62, "tapeType": "continuous", "rotation": 270, "crop": True, "cropMarginMm": 2}
X2_PREFS = {"cut": True, "feedMm": 1, "lengthMm": None, "mirror": False, "invert": True, "tapeWidth": 62, "tapeType": "continuous", "rotation": "auto", "crop": False, "cropMarginMm": 3}


def _job(client, ev, user_id, prefs=None):
    body = {"user_id": user_id, "request_id": str(uuid.uuid4())}
    if prefs is not None:
        body["prefs"] = prefs
    return client.post(f"/api/events/{ev.id}/print-jobs", json=body)


def test_two_devices_with_different_settings_print_on_the_same_shared_printer_each_with_its_own(client, setup, db):  # noqa: F811
    ev, u = setup
    _as(client, "y1"); _beat(client, ev, printer=True, device="Y")
    _route(client, ev, u["x1"], u["y1"]); _route(client, ev, u["x2"], u["y1"])
    _as(client, "x1"); assert _job(client, ev, "1001", X1_PREFS).status_code == 200
    _as(client, "x2"); assert _job(client, ev, "1002", X2_PREFS).status_code == 200
    _as(client, "y1")
    first = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    second = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    assert first["user_id"] == "1001" and second["user_id"] == "1002"
    for key in ("cut", "feedMm", "mirror", "rotation", "cropMarginMm"):
        assert first["prefs"][key] == X1_PREFS[key], key                                           # Y no los cambia por los suyos
    assert second["prefs"]["invert"] is True and second["prefs"]["crop"] is False and second["prefs"]["rotation"] == "auto"
    assert "lengthMm" not in first["prefs"]                                                        # vacío = el de la plantilla (no se guarda)


def test_a_reprint_from_the_queue_also_carries_the_requesting_device_settings(client, setup, db):  # noqa: F811
    ev, u = setup
    _as(client, "y1"); _beat(client, ev, printer=True, device="Y")
    _route(client, ev, u["x1"], u["y1"])
    _as(client, "x1")
    assert _job(client, ev, "1001", X1_PREFS).status_code == 200
    r = client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": "1001", "request_id": str(uuid.uuid4()), "reprint": True, "prefs": dict(X1_PREFS, feedMm=6)})
    assert r.status_code == 200 and r.json()["duplicate"] is False
    stored = [json.loads(j.prefs_json)["feedMm"] for j in db.query(PrintJob).order_by(PrintJob.id)]
    assert stored == [4, 6]


def test_an_old_job_without_settings_or_with_bad_ones_prints_with_the_event_values(client, setup, db):  # noqa: F811
    ev, u = setup
    _as(client, "y1"); _beat(client, ev, printer=True, device="Y")
    _route(client, ev, u["x1"], u["y1"])
    _as(client, "x1")
    assert _job(client, ev, "1001").status_code == 200                                              # como lo manda una pantalla vieja: sin «prefs»
    assert _job(client, ev, "1002", {"rotation": 45, "tapeWidth": 99}).status_code == 200          # no válidos: el pedido sigue, sin parámetros
    _as(client, "y1")
    jobs = [client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] for _ in range(2)]
    assert [j["prefs"] for j in jobs] == [None, None]                                              # None = la pantalla usa los del EVENTO (no los locales de Y)


def test_the_old_mirror_value_of_an_event_is_not_inherited_and_new_values_are_versioned(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    ev.print_settings_json = json.dumps({"mirror": True, "cut": False, "rotation": 90})               # guardado ANTES del arreglo: «mirror» compensaba el error
    db.commit()
    _as(client, "coord1")
    got = client.get(f"/api/events/{ev.id}/print-settings").json()["settings"]
    assert got == {"cut": False, "rotation": 90}                                                     # el espejo viejo se ignora; lo demás se conserva
    assert json.loads(print_settings.settings_json(ev)) == {"cut": False, "rotation": 90}           # lo mismo en la pantalla de Registro
    r = client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {"mirror": True, "cut": False}})
    assert r.status_code == 200
    db.refresh(ev)
    assert json.loads(ev.print_settings_json) == {"v": 2, "mirror": True, "cut": False}             # con versión: este «mirror» ya es el corregido
    assert client.get(f"/api/events/{ev.id}/print-settings").json()["settings"] == {"mirror": True, "cut": False}
    assert client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {}}).status_code == 200
    db.refresh(ev)
    assert ev.print_settings_json is None


def test_the_registration_page_gets_the_current_event_values_without_the_old_mirror(client, setup, db):  # noqa: F811
    ev, _u = setup
    ev.print_settings_json = json.dumps({"mirror": True, "feedMm": 2})
    db.commit()
    _as(client, "x1")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert 'name="gw-print-settings" content="{&#34;feedMm&#34;: 2}"' in page or 'content="{&quot;feedMm&quot;: 2}"' in page, page[page.find("gw-print-settings") - 10: page.find("gw-print-settings") + 80]
