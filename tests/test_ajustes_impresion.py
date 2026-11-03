"""Ajustes de impresión (orden B, 23-oct-2026): una sola impresión por persona (servidor), valores de impresión por evento (cinta, giro, recorte) y el diseñador de escarapelas.
Ninguna prueba depende del orden ni de la colación de la base: las listas se comparan en Python."""
import json
import pathlib
import re
import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import AccessLog, EventAttendee, PrintJob, StaffUser
from app.routers import print_settings, shared_print
from app.timeutil import utcnow
from tests.conftest import PASSWORD, login

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
def setup(client, factory, db):
    """Evento con la impresión compartida ENCENDIDA: un admin, un registrador X (imprime en Y) y un equipo Y con impresora, con tres personas ya registradas."""
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso")
    ev.shared_print_enabled = True
    db.commit()
    users = {n: factory.staff("digitador", n) for n in ("x1", "x2", "y1")}
    for u in users.values():
        factory.authorize(ev, u)
    for uid in ("1001", "1002", "1003"):
        factory.person(ev, uid, first_name=f"P{uid}")
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional"))
    db.commit()
    login(client, "y1")
    client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json={"device_id": "y", "platform": "Android", "browser": "Chrome", "printer_connected": True, "printer_name": "QL-800"})
    client.post("/logout"); client.cookies.clear()
    login(client, "adm")
    for x in ("x1", "x2"):
        r = client.put(f"/api/events/{ev.id}/shared-print/route", json={"staff_user_id": users[x].id, "printer_staff_id": users["y1"].id})
        assert r.status_code == 200, r.text
    client.post("/logout"); client.cookies.clear()
    login(client, "x1")
    return ev, users


def _job(client, ev, uid="1001", **extra):
    return client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": uid, "request_id": str(uuid.uuid4()), **extra})


# ---------------------------------------------------------------------------------------------------- UNA impresión por persona (servidor)
def test_a_second_request_for_the_same_person_in_the_window_returns_the_same_job(client, setup, db):
    ev, _ = setup
    first = _job(client, ev).json()
    again = _job(client, ev)                                                    # otro request_id: doble clic, refresco, otro camino de registro
    assert again.status_code == 200 and again.json()["duplicate"] is True and again.json()["id"] == first["id"]
    assert db.query(PrintJob).filter_by(event_id=ev.id).count() == 1
    assert _job(client, ev, "1002").json()["id"] != first["id"]                 # otra persona: otro trabajo


def test_two_devices_asking_at_once_for_the_same_person_get_one_job(client, setup, db, monkeypatch):
    monkeypatch.setenv("SINGLE_SESSION", "0")                       # esta prueba simula DOS dispositivos de la misma cuenta a la vez (con sesión única el primero se cerraría)
    ev, users = setup
    from app.main import app
    clients = []
    for name in ("x1", "x2", "x1", "x2"):
        c = TestClient(app)
        r = c.post("/login", data={"username": name, "password": PASSWORD}, follow_redirects=False)
        assert r.status_code in (200, 302, 303), r.text
        clients.append(c)
    results, barrier = [], threading.Barrier(len(clients))

    def go(c):
        barrier.wait()
        results.append(_job(c, ev, "1003"))
    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.status_code for r in results] == [200] * 4
    ids = {r.json()["id"] for r in results}
    assert len(ids) == 1 and sum(1 for r in results if not r.json()["duplicate"]) == 1            # uno lo creó, los demás recibieron el mismo
    db.expire_all()
    assert db.query(PrintJob).filter_by(event_id=ev.id).count() == 1


def test_an_explicit_reprint_creates_another_job_and_leaves_a_trace(client, setup, db, caplog):
    ev, _ = setup
    first = _job(client, ev).json()
    with caplog.at_level("INFO", logger="golden.shared_print"):
        second = _job(client, ev, reprint=True).json()
    assert second["id"] != first["id"] and second["duplicate"] is False
    assert any("REIMPRESIÓN explícita" in r.getMessage() for r in caplog.records)
    assert "1001" not in " ".join(r.getMessage() for r in caplog.records)                         # sin datos personales en el log


def test_after_the_window_or_after_a_failure_the_person_can_print_again(client, setup, db):
    ev, users = setup
    first = _job(client, ev).json()
    job = db.get(PrintJob, first["id"])
    job.created_at = utcnow() - shared_print.DEDUPE_WINDOW - timedelta(seconds=5)                 # pasó la ventana
    db.commit()
    again = _job(client, ev).json()
    assert again["id"] != first["id"] and again["duplicate"] is False
    row = db.get(PrintJob, again["id"])
    row.status = "failed"                                                                          # un fallo no bloquea el reintento
    db.commit()
    third = _job(client, ev).json()
    assert third["id"] not in (first["id"], again["id"])
    row = db.get(PrintJob, third["id"])
    row.status = "expired"
    db.commit()
    assert _job(client, ev).json()["id"] not in (first["id"], again["id"], third["id"])


def test_a_network_retry_with_the_same_request_id_is_still_the_same_job(client, setup, db):
    ev, _ = setup
    rid = str(uuid.uuid4())
    a = client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": "1001", "request_id": rid}).json()
    b = client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": "1001", "request_id": rid}).json()
    assert a["id"] == b["id"] and b["duplicate"] is True
    assert db.query(PrintJob).filter_by(event_id=ev.id).count() == 1


def test_the_claimed_job_is_delivered_once_even_if_two_tabs_of_the_printer_poll(client, setup, db):
    """El equipo Y con dos pestañas abiertas pregunta por trabajos en las dos: el trabajo reservado solo llega a UNA."""
    ev, users = setup
    _job(client, ev, "1001")
    client.post("/logout"); client.cookies.clear()
    login(client, "y1")
    got = [client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] for _ in range(3)]
    assert [g is not None for g in got].count(True) == 1


# ---------------------------------------------------------------------------------------------------- valores de impresión por evento
def test_print_settings_default_to_nothing_and_roundtrip_with_a_clear_validation(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    r = client.get(f"/api/events/{ev.id}/print-settings")
    assert r.status_code == 200 and r.json()["settings"] == {} and r.json()["supported_tapes"] == [62] and r.json()["defaults"]["tapeWidth"] == 62
    r = client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {"rotation": 90, "crop": True, "cropMarginMm": 4, "feedMm": 2, "cut": False, "tapeWidth": 62, "tapeType": "continuous", "lengthMm": None, "mirror": None}})
    assert r.status_code == 200 and r.json()["settings"] == {"rotation": 90, "crop": True, "cropMarginMm": 4, "feedMm": 2, "cut": False, "tapeWidth": 62, "tapeType": "continuous"}
    db.expire_all()
    assert json.loads(db.get(type(ev), ev.id).print_settings_json)["cropMarginMm"] == 4
    assert client.get(f"/api/events/{ev.id}/print-settings").json()["settings"]["rotation"] == 90
    assert client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {"cropMarginMm": 4, "desconocido": 1}}).json()["settings"] == {"cropMarginMm": 4}        # lo desconocido se ignora
    r = client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {}})              # restablecer
    db.expire_all()
    assert r.status_code == 200 and r.json()["settings"] == {} and db.get(type(ev), ev.id).print_settings_json is None


@pytest.mark.parametrize("bad, msg", [
    ({"rotation": 45}, "giro"), ({"rotation": "raro"}, "número"), ({"feedMm": -1}, "margen de avance"), ({"cropMarginMm": 99}, "margen del recorte"),
    ({"tapeWidth": 50}, "no está soportado"), ({"tapeType": "rara"}, "tipo de cinta"), ({"tapeType": "diecut"}, "necesita el largo"), ({"lengthMm": 3}, "largo de la etiqueta"),
    ({"cut": "si"}, "sí o no"),
])
def test_invalid_print_settings_are_refused_with_a_clear_message_and_nothing_is_saved(client, factory, db, bad, msg):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    r = client.put(f"/api/events/{ev.id}/print-settings", json={"settings": bad})
    assert r.status_code == 400 and msg in r.json()["detail"], r.text
    assert db.get(type(ev), ev.id).print_settings_json is None


def test_a_die_cut_tape_needs_its_length_and_is_stored_with_it(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    r = client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {"tapeType": "diecut", "lengthMm": 80}})
    assert r.status_code == 200 and r.json()["settings"] == {"tapeType": "diecut", "lengthMm": 80}


def test_only_coordinators_and_up_can_read_or_change_print_settings_and_only_for_their_own_client(client, factory, db):
    ev = factory.event("creado")
    other = factory.event("creado", tenant_id="otra")
    for role, name in (("digitador", "dig"), ("cliente", "cli")):
        u = factory.staff(role, name)
        factory.authorize(ev, u)
        client.post("/logout"); client.cookies.clear()
        login(client, name)
        assert client.get(f"/api/events/{ev.id}/print-settings").status_code == 403, role
        assert client.put(f"/api/events/{ev.id}/print-settings", json={"settings": {"cut": False}}).status_code == 403, role
    outsider = factory.staff("digitador", "otro", tenant_id="otra")                              # de otro cliente (y sin rol para esto): ni leer ni cambiar
    factory.authorize(other, outsider)
    client.post("/logout"); client.cookies.clear()
    login(client, "otro")
    assert client.get(f"/api/events/{other.id}/print-settings").status_code == 403
    assert client.put(f"/api/events/{other.id}/print-settings", json={"settings": {"cut": False}}).status_code == 403
    db.expire_all()
    assert db.get(type(ev), other.id).print_settings_json is None


def test_the_tapes_the_server_accepts_are_exactly_the_ones_qlusb_can_print():
    js = (ROOT / "static/js/ql-usb.js").read_text(encoding="utf-8")
    block = re.search(r"var MEDIA = \{(.*?)\n  \};", js, re.S).group(1)
    assert sorted(int(n) for n in re.findall(r"^\s*(\d+):\s*\{", block, re.M)) == sorted(print_settings.SUPPORTED_TAPES)
    assert print_settings.DEFAULTS == json.loads(json.dumps(print_settings.DEFAULTS))
    defaults = re.search(r"var PREF_DEFAULTS = \{(.*?)\};", js, re.S).group(1)
    for key, val in print_settings.DEFAULTS.items():
        assert re.search(rf"\b{key}:\s*{re.escape(json.dumps(val))}", defaults), key               # los valores de fábrica son los mismos en el servidor y en el navegador


def test_the_registration_page_carries_the_event_values_with_or_without_shared_print(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    ev.print_settings_json = json.dumps({"cropMarginMm": 5})
    db.commit()
    login(client, "coord")
    for shared in (False, True):                                                                  # el modo por controlador y los valores del evento no dependen del interruptor compartido
        ev.shared_print_enabled = shared
        db.commit()
        page = client.get(f"/kiosk/{ev.id}/registro").text
        m = re.search(r'<meta name="gw-print-settings" content="([^"]*)">', page)
        assert m and json.loads(m.group(1).replace("&#34;", '"').replace("&quot;", '"')) == {"cropMarginMm": 5}
        assert "shared-print.js" in page and "ql-usb.js" in page


def test_parameters_page_has_the_event_print_values_card_with_the_62mm_continuous_default(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert 'id="printSettingsCard"' in page and "continua de 62 mm (DK-22205)" in page and 'id="ps_tapeWidth"' in page and 'id="psReset"' in page


# ---------------------------------------------------------------------------------------------------- diseñador de escarapelas
def test_the_editor_page_has_the_three_zones_zoom_controls_and_the_mobile_tabs(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    page = client.get(f"/kiosk/{ev.id}/escarapela").text
    for marker in ('id="toolsCol"', 'id="badgeCanvas"', 'id="propsPanel"',                           # herramientas · lienzo · propiedades
                   'id="zoomFit"', 'id="zoomReal"', 'id="zoomIn"', 'id="zoomOut"', 'id="zoomLabel"',  # ajustar a pantalla, tamaño real, zoom manual
                   'id="editorTabs"', 'id="mobileTopBar"', 'id="nudgeBar"',                            # móvil: pestañas Lienzo/Propiedades, barra superior y ajuste fino
                   'id="editorWarn"', 'id="printInfo"', "js/ql-usb.js"):                               # avisos de medida y de cinta
        assert marker in page, marker
    assert "let editorScale" in page and "EDITOR_SCALE" not in page                                      # el zoom ya no es una constante
    assert "MIN_ZOOM = 0.25" in page                                                                     # mínimo 25 %
    assert "pointerdown" in page and "mousedown" not in page                                             # arrastre con mouse Y con el dedo
    assert "addEventListener('input'" in page and "tplOrientation" in page and "updateWarnings(true)" in page   # la orientación redibuja y avisa de lo que queda fuera
    assert "--editor-h" in page and "window.innerHeight" in page                                         # el cuerpo ocupa lo que queda de la ventana
    assert "body.editor-page { overflow:hidden; }" in page                                               # sin scroll de página en escritorio


def test_the_certificate_editor_shares_the_layout_without_the_tape_warning(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("creado")
    login(client, "coord")
    page = client.get(f"/kiosk/{ev.id}/certificado").text
    assert 'id="zoomFit"' in page and "KIND === 'badge' && window.QLUsb" in page                          # la advertencia de la cinta solo aplica a escarapelas
