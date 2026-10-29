"""Impresión compartida (orden del 22-oct-2026): interruptor APAGADO por defecto; con él apagado todo es igual que hoy. Encendido: equipos que reportan su
impresora, a qué equipo imprime cada usuario (sin tope; aviso con más de 6 por impresora), cola atómica sin duplicados, caducidad de 5 minutos y permisos del mismo evento."""
import uuid
from datetime import timedelta

import pytest

from app.models import Event, PrintJob, PrintLog
from app.routers import shared_print
from app.timeutil import utcnow
from tests.conftest import login


@pytest.fixture()
def setup(client, factory, db):
    """Evento con la impresión compartida ENCENDIDA, un admin que configura, dos registradores (X1, X2) y dos equipos con impresora (Y1, Y2)."""
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso")
    ev.shared_print_enabled = True
    db.commit()
    users = {}
    for name in ("x1", "x2", "x3", "x4", "y1", "y2"):
        users[name] = factory.staff("digitador", name)
        factory.authorize(ev, users[name])
    factory.person(ev, "1001")
    factory.person(ev, "1002", first_name="Beto")
    factory.person(ev, "1003", first_name="Cata", last_name="Pendiente")                         # inscrita pero SIN registrar
    from app.models import AccessLog
    for uid in ("1001", "1002"):                                                                  # 1001 y 1002 ya se acreditaron
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional"))
    db.commit()
    return ev, users


def _as(client, username):
    client.post("/logout"); client.cookies.clear()
    login(client, username)


def _beat(client, ev, printer=True, device="dev"):
    return client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json={"device_id": device, "platform": "Android", "browser": "Chrome",
                                                                           "printer_connected": printer, "printer_name": "QL-800" if printer else None})


def _route(client, ev, x, y):
    _as(client, "adm")
    return client.put(f"/api/events/{ev.id}/shared-print/route", json={"staff_user_id": x.id, "printer_staff_id": y.id if y else None})


def _job(client, ev, user_id="1001", request_id=None):
    return client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": user_id, "request_id": request_id or str(uuid.uuid4())})


# ---------------------------------------------------------------------------------------------------- apagado = igual que hoy
def test_it_is_off_by_default_and_the_registration_bar_is_still_there(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    assert ev.shared_print_enabled is False
    factory.authorize(ev, factory.staff("digitador", "dig"))
    login(client, "dig")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "window.SHARED_PRINT_ENABLED = false" in page                                           # apagada: lo compartido no se usa...
    assert "js/shared-print.js" in page and "js/ql-usb.js" in page and "html2canvas" in page and "driver-print" not in page   # ...pero la barra (touch, menú) sigue; sin modo controlador
    assert "js/badge-render.js" in page
    for method, path in (("post", f"/api/events/{ev.id}/print-devices/heartbeat"), ("post", f"/api/events/{ev.id}/print-jobs"), ("get", f"/api/events/{ev.id}/print-jobs-next")):
        body = {"device_id": "d", "user_id": "1", "request_id": "r"} if method == "post" else None
        r = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert r.status_code == 409, path                                                          # apagada: ningún trabajo ni señal
    assert db.query(PrintJob).count() == 0


def test_when_on_the_registration_page_loads_usb_printing_and_the_touch_mode(client, setup):
    ev, _u = setup
    _as(client, "x1")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "js/ql-usb.js" in page and "js/shared-print.js" in page and "html2canvas" in page


def test_only_configurators_can_switch_it_and_see_the_devices(client, setup, db):
    ev, _u = setup
    _as(client, "x1")
    assert client.put(f"/api/events/{ev.id}/shared-print", json={"enabled": False}).status_code == 403
    assert client.get(f"/api/events/{ev.id}/shared-print").status_code == 403
    _as(client, "adm")
    assert client.put(f"/api/events/{ev.id}/shared-print", json={"enabled": False}).json() == {"enabled": False}
    db.expire_all()
    assert db.get(Event, ev.id).shared_print_enabled is False


# ---------------------------------------------------------------------------------------------------- equipos y rutas
def test_devices_report_and_appear_with_last_signal_and_printer(client, setup):
    ev, u = setup
    _as(client, "y1")
    r = _beat(client, ev, printer=True)
    assert r.json() == {"enabled": True, "mode": "self", "printer_name": "", "printer_ready": False, "printer_mode": None, "printer_online": None, "my_mode": "usb", "serving": 0, "poll": False,
                        "holder": True, "waiting": 0, "claimed": 0, "serving_names": []}
    _as(client, "x1")
    _beat(client, ev, printer=False)
    _as(client, "adm")
    users = {x["username"]: x for x in client.get(f"/api/events/{ev.id}/shared-print").json()["users"]}
    assert users["y1"]["eligible_printer"] is True and users["y1"]["device"]["printer_connected"] is True and users["y1"]["device"]["online"] is True
    assert users["y1"]["device"]["platform"] == "Android" and users["y1"]["device"]["browser"] == "Chrome"
    assert users["x1"]["eligible_printer"] is False and users["x1"]["device"]["print_mode"] == "none" and "No tiene impresora" in users["x1"]["ineligible_reason"]      # activo SIN impresora ni «ventana de Chrome»: no puede ser anfitrión
    assert users["x2"]["device"] is None and users["x2"]["ineligible_reason"] and users["y1"]["ineligible_reason"] is None                                              # x2 sin señal todavía


def test_a_printer_must_be_connected_reporting_and_has_no_hard_limit_only_a_soft_warning_over_six(client, factory, setup, db):
    ev, u = setup
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 409                               # Y1 no ha reportado: no es elegible
    _as(client, "y1")
    _beat(client, ev, printer=True)
    xs = ["x1", "x2", "x3", "x4"]
    for i in range(5, 9):                                                                         # 8 usuarios en la misma impresora: sin tope duro (orden del 22-oct-2026)
        users = u.setdefault(f"x{i}", factory.staff("digitador", f"x{i}"))
        factory.authorize(ev, users)
        xs.append(f"x{i}")
    for n, x in enumerate(xs, start=1):
        r = _route(client, ev, u[x], u["y1"])
        assert r.status_code == 200, (x, r.text)
        assert r.json()["serving"] == n
        assert ("warning" in r.json()) == (n > shared_print.WARN_PER_PRINTER), n                 # aviso suave solo con más de 6
    assert "puede haber espera" in r.json()["warning"]
    cfg = client.get(f"/api/events/{ev.id}/shared-print").json()
    assert cfg["warn_per_printer"] == 6 and "max_per_printer" not in cfg
    assert {x["username"]: x["serving"] for x in cfg["users"]}["y1"] == 8
    assert _route(client, ev, u["x1"], u["x1"]).status_code == 400                               # a sí mismo: «en su propio equipo»
    _as(client, "y1")
    beat = _beat(client, ev, printer=True).json()
    assert beat["serving"] == 8 and beat["poll"] is True
    _as(client, "x1")
    beat = _beat(client, ev, printer=False).json()
    assert beat["mode"] == "shared" and beat["printer_name"] and beat["printer_ready"] is True
    from app.models import PrintDevice
    dev = db.query(PrintDevice).filter_by(event_id=ev.id, staff_user_id=u["y1"].id).one()
    dev.last_seen_at = utcnow() - timedelta(seconds=40)                                            # Y1 dejó de reportar
    db.commit()
    assert _route(client, ev, u["x4"], u["y1"]).status_code == 409


def test_staff_of_another_client_cannot_be_routed_or_use_the_queue(client, factory, setup):
    ev, u = setup
    other_ev = factory.event("en_proceso", tenant_id="otra")
    outsider = factory.staff("digitador", "otro", tenant_id="otra")
    factory.authorize(other_ev, outsider)
    _as(client, "adm")
    r = client.put(f"/api/events/{ev.id}/shared-print/route", json={"staff_user_id": outsider.id, "printer_staff_id": None})
    assert r.status_code in (403, 404)
    _as(client, "otro")
    assert _beat(client, ev).status_code in (403, 404)
    assert client.get(f"/api/events/{ev.id}/print-jobs-next").status_code in (403, 404)


# ---------------------------------------------------------------------------------------------------- la cola
def _ready(client, ev, u, x="x1", y="y1"):
    _as(client, y)
    _beat(client, ev, printer=True)
    assert _route(client, ev, u[x], u[y]).status_code == 200


def test_x_prints_on_y_once_without_duplicates_and_the_count_is_kept(client, setup, db):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    rid = str(uuid.uuid4())
    first = _job(client, ev, "1001", rid).json()
    again = _job(client, ev, "1001", rid).json()                                                   # el mismo pedido reintentado
    assert first["status"] == "queued" and first["printer_ready"] is True and again["id"] == first["id"] and again["duplicate"] is True
    assert db.query(PrintJob).count() == 1
    assert "user_id" not in first and "1001" not in str(first)                                   # a X no se le devuelve ningún dato de la persona
    _as(client, "y1")
    got = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    assert got["id"] == first["id"] and got["user_id"] == "1001"
    assert client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] is None             # reservado: no se entrega dos veces
    done = client.post(f"/api/events/{ev.id}/print-jobs/{got['id']}/result", json={"ok": True}).json()
    assert done["status"] == "printed"
    assert client.post(f"/api/events/{ev.id}/print-jobs/{got['id']}/result", json={"ok": False, "error": "x"}).json()["status"] == "printed"      # idempotente
    assert db.query(PrintLog).filter_by(event_id=ev.id, user_id="1001", printed_by_staff_id=u["x1"].id).count() == 1
    _as(client, "x1")
    assert client.get(f"/api/events/{ev.id}/print-jobs/{first['id']}").json()["status"] == "printed"
    assert client.get(f"/api/events/{ev.id}/print-jobs").json()["jobs"] == []                    # ya impresa: no está en su cola


def test_only_the_assigned_printer_receives_and_confirms_the_job(client, setup):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "y2")
    _beat(client, ev, printer=True)
    _as(client, "x1")
    job = _job(client, ev).json()
    _as(client, "y2")
    assert client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] is None
    assert client.post(f"/api/events/{ev.id}/print-jobs/{job['id']}/result", json={"ok": True}).status_code == 404
    _as(client, "x2")
    assert client.get(f"/api/events/{ev.id}/print-jobs/{job['id']}").status_code == 404           # otro registrador no ve el trabajo ajeno


def test_a_failure_and_an_offline_printer_leave_a_visible_queue_to_reprint(client, setup, db):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    job = _job(client, ev, "1001").json()
    _as(client, "y1")
    got = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    client.post(f"/api/events/{ev.id}/print-jobs/{got['id']}/result", json={"ok": False, "error": "sin etiquetas"})
    from app.models import PrintDevice
    dev = db.query(PrintDevice).filter_by(event_id=ev.id, staff_user_id=u["y1"].id).one()
    dev.printer_connected = False                                                                  # Y1 perdió la impresora
    db.commit()
    _as(client, "x1")
    offline = _job(client, ev, "1002").json()
    assert offline["status"] == "queued" and offline["printer_ready"] is False and "no está conectado" in offline["warning"]
    queue = {j["id"]: j for j in client.get(f"/api/events/{ev.id}/print-jobs").json()["jobs"]}
    assert queue[job["id"]]["status"] == "failed" and queue[job["id"]]["error"] == "sin etiquetas" and queue[job["id"]]["user_id"] == "1001"
    assert queue[offline["id"]]["status"] == "queued"


def test_a_job_not_printed_in_five_minutes_expires_and_is_never_printed_later(client, setup, db):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    job = _job(client, ev).json()
    row = db.get(PrintJob, job["id"])
    row.created_at = utcnow() - shared_print.PRINT_JOB_TTL - timedelta(seconds=1)
    db.commit()
    _as(client, "y1")
    assert client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] is None
    db.expire_all()
    assert db.get(PrintJob, job["id"]).status == "expired"
    _as(client, "x1")
    assert client.get(f"/api/events/{ev.id}/print-jobs").json()["jobs"][0]["status"] == "expired"


def test_a_user_who_prints_on_their_own_device_cannot_create_shared_jobs(client, setup):
    ev, _u = setup
    _as(client, "x1")
    r = _job(client, ev)
    assert r.status_code == 409 and "propio equipo" in r.json()["detail"]


def test_a_person_from_outside_the_event_cannot_be_queued(client, setup):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    assert _job(client, ev, "9999999").status_code == 404


def test_the_logs_never_carry_the_person(client, setup, caplog):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    with caplog.at_level("INFO", logger="golden.shared_print"):
        job = _job(client, ev, "1001").json()
        _as(client, "y1")
        got = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
        client.post(f"/api/events/{ev.id}/print-jobs/{got['id']}/result", json={"ok": True})
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "golden.shared_print")
    assert f"trabajo {job['id']}" in text and "1001" not in text and "Ana" not in text


# ---------------------------------------------------------------------------------------------------- una sola pestaña dueña de la impresora
def test_a_tab_that_does_not_own_the_printer_reports_null_and_does_not_overwrite_the_owner(client, setup, db):
    """Dos pestañas del Registro en el mismo equipo: la que NO tiene la impresora (otra pestaña la tomó) manda printer_connected=null y no apaga a la dueña."""
    ev, u = setup
    _as(client, "y1")
    _beat(client, ev, printer=True)
    r = client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json={"device_id": "dev", "platform": "Android", "browser": "Chrome", "printer_connected": None})
    assert r.status_code == 200
    _as(client, "adm")
    y1 = {x["username"]: x for x in client.get(f"/api/events/{ev.id}/shared-print").json()["users"]}["y1"]
    assert y1["eligible_printer"] is True and y1["device"]["printer_connected"] is True and y1["device"]["printer_name"] == "QL-800"
    _as(client, "x1")                                                                              # un equipo nuevo que llega con null queda «sin impresora»
    client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json={"device_id": "x", "printer_connected": None})
    _as(client, "adm")
    x1 = {x["username"]: x for x in client.get(f"/api/events/{ev.id}/shared-print").json()["users"]}["x1"]
    assert x1["device"]["printer_connected"] is False and x1["eligible_printer"] is False       # sin impresora declarada: no es anfitrión posible


def test_the_registration_label_uses_the_same_calibration_as_the_usb_test_page_and_the_test_page_lets_the_printer_go():
    import pathlib
    import re
    page = pathlib.Path("templates/impresion_usb.html").read_text(encoding="utf-8")
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    ql = pathlib.Path("static/js/ql-usb.js").read_text(encoding="utf-8")
    # /impresion-usb guarda mirror|invert|cut como "1"/"0" con las MISMAS claves que el Registro (QLUsb.PREF_KEYS; «Espejo» versionado desde el 24-oct-2026: ql_mirror_v2)
    assert 'localStorage.getItem(QLUsb.PREF_KEYS[key])' in page and 'localStorage.setItem(QLUsb.PREF_KEYS[key], val ? "1" : "0")' in page
    assert 'pref("mirror", false)' in page and 'pref("invert", false)' in page and 'pref("cut", true)' in page
    assert "QLUsb.resolvePrefs(storage(), eventPrefs)" in sp and 'QLUsb.readPrefs(storage()).feedMm' in page                  # el Registro y la página leen las preferencias con la MISMA función (ql-usb.js)
    assert all(f'"{k}"' in ql for k in ("ql_cut", "ql_mirror_v2", "ql_invert", "ql_feed_mm", "ql_length_mm")) and "function resolvePrefs" in ql      # las mismas claves de siempre, ahora en PREF_KEYS
    lc = pathlib.Path("static/js/label-compose.js").read_text(encoding="utf-8")                                        # la composición vive en un módulo compartido por el USB y la ventana de impresión
    assert re.search(r"bitmapFromRGBA\(ctx\.getImageData\(0, 0, w, h\)\.data, w, h, 140, false\)", lc) and re.search(r"bitmapFromRGBA\(rgba, DOTS, t\.height, 140,", page)
    assert "mirror: p.mirror, autoCut: p.cut" in sp and "feedDots: QLUsb.mmToDots(p.feedMm)" in sp and 'mirror: $("optMirror").checked, autoCut: $("optCut").checked' in page
    # la página de prueba suelta la impresora al terminar y al ocultarse o cerrarse; el cierre hace releaseInterface y suelta el candado entre pestañas
    assert "finally { await QLUsb.close(); }" in page and '"visibilitychange"' in page and '"pagehide"' in page
    assert "releaseInterface" in ql and "navigator.locks.request(LOCK_NAME, { ifAvailable: true }" in ql
    assert "busy" in sp and "BUSY_RETRY_MS" in sp and "printer_connected: usb.busy ? null : usb.ok" in sp


# ---------------------------------------------------------------------------------------------------- solo se imprime a quien está Registrado
def test_a_person_who_is_not_registered_gets_no_shared_job_and_the_screen_is_told_why(client, setup, db):
    ev, u = setup
    _as(client, "y1")
    _beat(client, ev, printer=True)
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 200
    _as(client, "x1")
    r = _job(client, ev, "1003")
    assert r.status_code == 409 and r.json()["detail"] == "No se puede imprimir: Cata Pendiente aún no está registrado. Acredítalo o guarda su registro primero."
    assert db.query(PrintJob).count() == 0                                                         # ni trabajo ni cola
    chk = client.get(f"/api/events/{ev.id}/print-check/1003").json()
    assert chk["registered"] is False and "Cata Pendiente" in chk["detail"]
    assert client.get(f"/api/events/{ev.id}/print-check/1001").json() == {"registered": True}
    assert client.get(f"/api/events/{ev.id}/print-check/9999").status_code == 404                # fuera del evento
    from app.models import AccessLog                                                               # una EDICIÓN de perfil no es un registro
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1003", event_id=ev.id, record_type="Actualizado"))
    db.commit()
    assert _job(client, ev, "1003").status_code == 409
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1003", event_id=ev.id, record_type="Existente", registration_method="tradicional"))   # ahora sí se acreditó
    db.commit()
    assert _job(client, ev, "1003").status_code == 200 and client.get(f"/api/events/{ev.id}/print-check/1003").json() == {"registered": True}


def test_the_check_is_also_used_by_a_device_that_prints_on_its_own_printer(client, setup):
    ev, u = setup
    _as(client, "y1")                                                                             # Y imprime en su propio equipo: la pantalla también consulta
    _beat(client, ev, printer=True)
    assert client.get(f"/api/events/{ev.id}/print-check/1003").json()["registered"] is False
    assert client.get(f"/api/events/{ev.id}/print-check/1002").json()["registered"] is True


def test_the_print_check_is_closed_when_the_switch_is_off(client, factory, db):
    factory.staff("digitador", "dig0")
    ev = factory.event("en_proceso")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).filter_by(username="dig0").one())
    login(client, "dig0")
    assert client.get(f"/api/events/{ev.id}/print-check/1001").status_code == 409


def test_the_queue_shows_the_parameters_applied_to_each_job_and_a_phone_job_keeps_only_physical_ones(client, setup):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    celular = {"rotation": 0, "crop": False, "cut": False, "feedMm": 4, "mirror": True}              # lo que traería un celular con valores de prueba
    job = client.post(f"/api/events/{ev.id}/print-jobs", json={"user_id": "1001", "request_id": str(uuid.uuid4()), "prefs": celular}).json()
    _as(client, "y1")
    got = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    assert got["prefs"]["rotation"] == 0 and got["prefs"]["mirror"] is True                         # el pedido viaja tal cual; QUIEN IMPRIME decide la forma (shared-print.js prefsForJob)
    applied = "Cinta 62 mm continua · giro automático (90°) · recorte simétrico (mín. 3 mm) · corte no · margen 4 mm · el pedido traía otra forma (rotation, crop): se usó la de este equipo"
    client.post(f"/api/events/{ev.id}/print-jobs/{job['id']}/result", json={"ok": False, "error": "sin papel", "applied": applied})
    _as(client, "x1")
    row = [j for j in client.get(f"/api/events/{ev.id}/print-jobs").json()["jobs"] if j["id"] == job["id"]][0]
    assert row["applied"] == applied and row["status"] == "failed"
    assert client.get(f"/api/events/{ev.id}/print-jobs/{job['id']}").json()["applied"] == applied


def test_the_pending_button_is_big_with_its_counter_and_there_is_no_launcher_nor_driver_mode():
    import pathlib
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "#sharedPrintBar #spPending{min-height:64px" in sp and "Imprimir pendientes (${waitingCount()})" in sp          # grande y con el contador
    for gone in ("DriverPrint", "driver-print", "kioskFromUrl", "launcher", "spHostNote", "driverOn", "impresion=kiosk"):
        assert gone not in sp, gone


def test_the_driver_print_bar_loads_with_and_without_shared_print_but_not_for_clients(client, factory, db):
    factory.staff("coordinador", "coord")
    on = factory.event("en_proceso"); on.shared_print_enabled = True
    off = factory.event("en_proceso")
    db.commit()
    dig = factory.staff("digitador", "dig2")
    factory.authorize(on, dig); factory.authorize(off, dig)
    login(client, "dig2")
    assert "window.SHARED_PRINT_ENABLED = true" in client.get(f"/kiosk/{on.id}/registro").text
    page = client.get(f"/kiosk/{off.id}/registro").text
    assert "window.SHARED_PRINT_ENABLED = false" in page and "gw-print-settings" in page


def test_shared_print_js_never_calls_shared_routes_when_the_event_has_it_off():
    import pathlib
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "window.SHARED_PRINT_ENABLED !== false" in sp
    assert "if (!SHARED && !usb.ok) return auto ? original.maybeAutoPrint(userId) : original.openPrintWindow(userId);" in sp       # sin compartida y sin impresora: la ventana de siempre
    assert "if (sessionDead || !SHARED) { render(); return; }" in sp and "if (!SHARED || sessionDead || polling" in sp


def test_the_last_resort_print_page_declares_the_rotated_page_so_nothing_is_cut():
    import pathlib
    html = pathlib.Path("templates/badge_print.html").read_text(encoding="utf-8")
    assert "template.width_mm > template.height_mm" in html and "@page { size: ${pw}mm ${ph}mm; margin: 0; }" in html and "rotate(90deg)" in html


# ---------------------------------------------------------------------------------------------------- reclamo: solo quien imprime sola (25-oct-2026, bloque 1.1)
def _beat_as(client, ev, device, printer, name=None, dialog=False):
    body = {"device_id": device, "platform": "x", "browser": "Chrome", "printer_connected": printer, "printer_name": name}
    if dialog:
        body["print_mode"] = "dialog"                                                                # el equipo declara que imprime con la ventana de Chrome
    return client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json=body).json()


def test_another_session_of_the_station_account_never_overwrites_the_station_or_claims_its_jobs(client, setup, db):
    ev, u = setup
    _as(client, "y1")
    _beat_as(client, ev, "pc", True, "QL-800")
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 200
    _as(client, "x1")
    job = _job(client, ev, "1001").json()
    _as(client, "y1")
    phone = _beat_as(client, ev, "celular", False)                                                 # el admin consulta desde el celular con la MISMA cuenta
    assert phone["holder"] is False and phone["poll"] is False and phone["waiting"] == 1
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=celular").json()["job"] is None        # el celular no reclama
    pc = _beat_as(client, ev, "pc", True, "QL-800")
    assert pc["holder"] is True and pc["poll"] is True                                              # y el puesto sigue siendo el computador
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=pc").json()["job"]["id"] == job["id"]
    _as(client, "x1")
    assert client.get(f"/api/events/{ev.id}/print-jobs/{job['id']}").json()["status"] == "sent"


def test_a_window_with_a_print_dialog_never_claims_by_polling_but_the_click_claims(client, setup):
    ev, u = setup
    _as(client, "y1")
    _beat_as(client, ev, "pc", False, "QL-800 (sin USB)", dialog=True)        # imprime por controlador pero Chrome pide confirmar cada hoja: lo declara (print_mode dialog)
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 200
    _as(client, "x1")
    job = _job(client, ev, "1002").json()
    _as(client, "y1")
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=pc").json()["job"] is None     # el sondeo no reclama: el trabajo sigue en el servidor
    hb = _beat_as(client, ev, "pc", False, "QL-800 (sin USB)", dialog=True)
    assert hb["waiting"] == 1 and hb["claimed"] == 0 and hb["poll"] is False
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=pc&manual=1").json()["job"]["id"] == job["id"]      # «Imprimir pendientes»: la persona está ahí
    assert _beat_as(client, ev, "pc", False)["claimed"] == 1


def test_a_claimed_job_that_does_not_finish_in_60_seconds_goes_back_to_the_queue_and_a_late_result_is_still_accepted(client, setup, db):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    job = _job(client, ev, "1001").json()
    _as(client, "y1")
    got = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]
    assert got["id"] == job["id"] and client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] is None        # reclamado
    row = db.get(PrintJob, job["id"]); row.sent_at = utcnow() - timedelta(seconds=61); db.commit()
    again = client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"]                         # arrendamiento vencido: vuelve y otra ventana lo puede reclamar
    assert again and again["id"] == job["id"]
    db.expire_all()
    assert client.post(f"/api/events/{ev.id}/print-jobs/{job['id']}/result", json={"ok": True}).json()["status"] == "printed"
    assert client.get(f"/api/events/{ev.id}/print-jobs-next").json()["job"] is None


def test_the_station_queue_shows_pending_and_claimed_jobs_with_their_state(client, setup):
    ev, u = setup
    _ready(client, ev, u)
    _as(client, "x1")
    _job(client, ev, "1001"); _job(client, ev, "1002")
    _as(client, "y1")
    client.get(f"/api/events/{ev.id}/print-jobs-next")
    rows = client.get(f"/api/events/{ev.id}/print-jobs?scope=station").json()["jobs"]
    assert sorted(r["status"] for r in rows) == ["queued", "sent"] and all(r["requested_by"] for r in rows)


# ---------------------------------------------------------------------------------------------------- 27-oct-2026: arreglos de impresión
def test_the_browser_print_page_uses_the_same_composed_label_as_usb_and_keeps_the_fallback_and_the_horizontal_turn():
    import pathlib
    page = pathlib.Path("templates/badge_print.html").read_text(encoding="utf-8")
    assert "js/label-compose.js" in page and "js/ql-usb.js" in page and "html2canvas" in page and 'name="gw-print-settings"' in page
    assert "LabelCompose.renderShot" in page and "LabelCompose.composeBitmap" in page and "LabelCompose.pageSpec(out)" in page and "QLUsb.resolvePrefs(storage, printSettings())" in page
    assert "margin: 0" in pathlib.Path("static/js/label-compose.js").read_text(encoding="utf-8")
    assert "No se pudo armar la etiqueta con el recorte y el margen de Parámetros: se imprime la hoja de la plantilla." in page          # si la composición falla: la hoja de siempre, y avisa
    assert "const rotate = template.width_mm > template.height_mm;" in page and "@page { size: ${pw}mm ${ph}mm; margin: 0; }" in page and "rotate(90deg)" in page      # giro de la horizontal (a50a284) en la hoja de siempre
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "LabelCompose.composeBitmap(shot, tplW, tplH, p)" in sp and "LabelCompose.renderShot(stage, template, data, EID, holderScale)" in sp
    reg = pathlib.Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert reg.index("js/ql-usb.js") < reg.index("js/label-compose.js") < reg.index("js/shared-print.js")


def test_usb_works_with_shared_print_off_and_never_touches_the_shared_routes():
    import pathlib
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "if (!SHARED) return { kind" not in sp.replace("if (!SHARED) return usb.ok", "")                                   # la barra no depende de la compartida para el USB
    assert "if (!SHARED) { render(); return; }" not in sp                                                                     # connectUsb ya no se corta sin la compartida
    assert "if (window.QLUsb && QLUsb.supported()) {\n    navigator.usb.addEventListener('connect'" in sp                       # connect / disconnect de WebUSB también sin la compartida
    assert "if (!SHARED && !usb.ok) return auto ? original.maybeAutoPrint(userId) : original.openPrintWindow(userId);" in sp
    assert "if (SHARED && !(await registeredOrSay(userId))) return;" in sp and "if (sessionDead || !SHARED) { render(); return; }" in sp   # ninguna ruta compartida
    assert "Sin impresora: se usa la ventana de impresión del navegador." in sp and "Impresora conectada (" in sp
    assert "Windows usa su propio controlador" in sp and "gw_denied_notice" in sp and "if (!ask && usb.denied)" in sp


def test_normal_print_window_uses_the_62mm_paper_width_of_the_driver():
    from pathlib import Path
    html = Path("templates/badge_print.html").read_text(encoding="utf-8")                          # probado en hardware: con 58,93 mm (o menos de 99,8 mm de alto) Chrome ignora margin:0 y pone fecha, ruta y «1/1»
    assert "const PAGE_W = 62, PAGE_LEFT_MM = 0.5, PAGE_H = 99.8, MAX_IMG_H = 96;" in html and "@page { size: ${PAGE_W}mm ${pageH}mm; margin: 0 }" in html and "margin-left:${imgLeft}mm" in html and "endMark" in html


def test_denied_bar_explains_and_hides_the_useless_connect_button():
    from pathlib import Path
    sp = Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert sp.count("Este computador no puede abrir la impresora directamente") == 2 and "usb.busy || usb.denied ||" in sp


# ------------------------------------------------------------------------------------------------ 29-oct-2026, problema B: estado explícito de impresión de cada equipo
def _beat_mode(client, ev, mode, device="dev"):
    body = {"device_id": device, "platform": "Windows", "browser": "Chrome", "printer_connected": mode == "usb", "printer_name": "QL-800" if mode == "usb" else None}
    if mode == "dialog":
        body["print_mode"] = "dialog"
    return client.post(f"/api/events/{ev.id}/print-devices/heartbeat", json=body)


def test_only_usb_or_dialog_computers_can_host_and_none_is_refused_with_the_reason(client, setup):
    ev, u = setup
    for name, mode in (("y1", "usb"), ("x2", "dialog"), ("x3", "none")):
        _as(client, name)
        assert _beat_mode(client, ev, mode).json()["my_mode"] == mode
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 200                              # usb: sí
    assert _route(client, ev, u["x4"], u["x2"]).status_code == 200                              # dialog (computador que imprime con la ventana de Chrome): sí
    r = _route(client, ev, u["x4"], u["x3"])                                                    # none: no, y dice por qué
    assert r.status_code == 409 and "No tiene impresora" in r.json()["detail"] and "ventana de Chrome" in r.json()["detail"]
    _as(client, "adm")
    users = {x["username"]: x for x in client.get(f"/api/events/{ev.id}/shared-print").json()["users"]}
    assert [users[n]["eligible_printer"] for n in ("y1", "x2", "x3")] == [True, True, False] and users["x3"]["ineligible_reason"] and users["y1"]["ineligible_reason"] is None
    assert [users[n]["device"]["print_mode"] for n in ("y1", "x2", "x3")] == ["usb", "dialog", "none"]


def test_a_host_that_loses_its_printer_tells_it_and_the_requester_sees_the_mode_of_the_host(client, setup):
    ev, u = setup
    _as(client, "x2")
    _beat_mode(client, ev, "dialog")
    assert _route(client, ev, u["x1"], u["x2"]).status_code == 200
    _as(client, "x1")
    r = _beat_mode(client, ev, "none", "x1dev").json()
    assert r["mode"] == "shared" and r["printer_mode"] == "dialog" and r["printer_ready"] is False and r["printer_online"] is True          # quien pide ve que el anfitrión imprime con la ventana
    _as(client, "x2")
    r = _beat_mode(client, ev, "none").json()                                                    # el anfitrión declara que ya no imprime: se entera (serving > 0 y my_mode none)
    assert r["serving"] == 1 and r["my_mode"] == "none"
    _as(client, "x1")
    r = _beat_mode(client, ev, "none", "x1dev").json()
    assert r["printer_mode"] == "none" and r["printer_online"] is True                           # y quien pide también se entera


def test_a_dialog_host_job_warns_that_it_prints_when_the_host_taps_print_pending(client, setup):
    ev, u = setup
    _as(client, "x2")
    _beat_mode(client, ev, "dialog")
    assert _route(client, ev, u["x1"], u["x2"]).status_code == 200
    _as(client, "x1")
    out = _job(client, ev, "1001", str(uuid.uuid4())).json()
    assert out["printer_ready"] is False and out["printer_mode"] == "dialog" and "Imprimir pendientes" in out["warning"]


def test_a_none_beat_from_another_session_does_not_overwrite_a_dialog_or_usb_host(client, setup, db):
    ev, u = setup
    _as(client, "x2")
    _beat_mode(client, ev, "dialog", "pc")
    r = _beat_mode(client, ev, "none", "celular").json()                                         # el celular de la misma cuenta, sin impresora, no pisa al computador
    assert r["holder"] is False and r["my_mode"] == "dialog"
    from app.models import PrintDevice
    assert db.query(PrintDevice).filter_by(staff_user_id=u["x2"].id).one().device_id == "pc"


def test_the_bar_messages_depend_on_the_explicit_print_mode_without_the_false_disconnected_notice():
    import pathlib
    import subprocess
    r = subprocess.run(["node", "tests/js/shared_print_host_mode_check.js"], capture_output=True, text=True, encoding="utf8", timeout=60)
    assert r.returncode == 0 and "host_mode OK" in r.stdout, r.stdout + r.stderr
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "DESCONECTADA" not in sp and "print_mode: usb.ok ? 'usb' : (dialogDeclared ? 'dialog' : 'none')" in sp and "gw_print_dialog" in sp


# ------------------------------------------------------------------------------------------------ 29-oct-2026, problema D: «Imprimir pendientes» reclama por TANDA (una sola ventana)
def _dialog_host_with_jobs(client, ev, u, db, n, factory):
    """y1 imprime con la ventana de Chrome (dialog) y x1 le pidió n escarapelas de n personas registradas."""
    from app.models import AccessLog
    _as(client, "y1")
    _beat_mode(client, ev, "dialog")
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 200
    for i in range(n):
        uid = f"7{i:03d}"
        factory.person(ev, uid, first_name=f"P{i}")
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional"))
    db.commit()
    _as(client, "x1")
    for i in range(n):
        assert _job(client, ev, f"7{i:03d}").status_code == 200
    _as(client, "y1")


def test_a_batch_claim_returns_the_pending_jobs_once_in_order_and_polling_never_claims_a_batch(client, setup, db, factory):
    ev, u = setup
    _dialog_host_with_jobs(client, ev, u, db, 5, factory)
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&batch=50").json() == {"jobs": []}                     # sin toque de la persona (manual) no reclama
    got = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    assert [j["user_id"] for j in got] == [f"7{i:03d}" for i in range(5)] and all(j["requested_by"] and "prefs" in j for j in got)
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"] == []                # entregados UNA vez: no se duplican
    assert {j.status for j in db.query(PrintJob).filter(PrintJob.printer_staff_id == u["y1"].id)} == {"sent"}


def test_more_than_fifty_pending_come_in_a_second_batch_and_a_single_claim_still_works(client, setup, db, factory):
    ev, u = setup
    _dialog_host_with_jobs(client, ev, u, db, 55, factory)
    first = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=200").json()["jobs"]                # el servidor nunca entrega más de 50
    second = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    assert len(first) == 50 and len(second) == 5 and not {j["id"] for j in first} & {j["id"] for j in second}
    assert client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1").json()["job"] is None                      # y el reclamo de a uno sigue igual


def test_batch_results_confirm_each_job_after_the_window_and_the_count_is_kept(client, setup, db, factory):
    ev, u = setup
    _dialog_host_with_jobs(client, ev, u, db, 3, factory)
    jobs = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    r = client.post(f"/api/events/{ev.id}/print-jobs/result-batch", json={"results": [{"id": jobs[0]["id"], "ok": True}, {"id": jobs[1]["id"], "ok": True}, {"id": jobs[2]["id"], "ok": False, "error": "sin papel"}, {"id": 99999, "ok": True}]})
    assert r.status_code == 200 and r.json() == {"confirmed": 3}                                                                 # el id ajeno se ignora
    st = {j.id: j.status for j in db.query(PrintJob)}
    assert [st[jobs[0]["id"]], st[jobs[1]["id"]], st[jobs[2]["id"]]] == ["printed", "printed", "failed"]
    from app.models import PrintLog
    assert db.query(PrintLog).count() == 2                                                                                       # el conteo de impresiones de siempre: solo los que salieron
    again = client.post(f"/api/events/{ev.id}/print-jobs/result-batch", json={"results": [{"id": jobs[0]["id"], "ok": False}]}).json()
    assert again == {"confirmed": 1} and db.get(PrintJob, jobs[0]["id"]).status == "printed"                                     # idempotente: no cambia lo ya confirmado


def test_a_closed_window_returns_the_claimed_jobs_to_the_queue_and_nothing_is_lost_or_reprinted(client, setup, db, factory):
    ev, u = setup
    _dialog_host_with_jobs(client, ev, u, db, 4, factory)
    jobs = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    client.post(f"/api/events/{ev.id}/print-jobs/result-batch", json={"results": [{"id": jobs[0]["id"], "ok": True}]})           # una sí salió
    rel = client.post(f"/api/events/{ev.id}/print-jobs/release", json={"ids": [j["id"] for j in jobs]}).json()                     # cerró la ventana: devolver todo lo que seguía enviado
    assert rel == {"released": 3} and db.get(PrintJob, jobs[0]["id"]).status == "printed"                                      # la que salió NO vuelve a la cola
    again = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    assert [j["id"] for j in again] == [j["id"] for j in jobs[1:]]                                                                # las otras 3 siguen pendientes, en orden
    _as(client, "y2")
    assert client.post(f"/api/events/{ev.id}/print-jobs/release", json={"ids": [j["id"] for j in jobs]}).json() == {"released": 0}   # otro puesto no puede soltar trabajos ajenos


def test_a_claimed_batch_keeps_its_lease_longer_than_a_single_job_and_then_returns_to_the_queue(client, setup, db, factory):
    from datetime import timedelta
    from app.timeutil import utcnow
    ev, u = setup
    _dialog_host_with_jobs(client, ev, u, db, 2, factory)
    jobs = client.get(f"/api/events/{ev.id}/print-jobs-next?device_id=dev&manual=1&batch=50").json()["jobs"]
    rows = db.query(PrintJob).filter(PrintJob.id.in_([j["id"] for j in jobs])).all()
    assert all(r.sent_at > utcnow() + timedelta(minutes=2) for r in rows)                                                         # el lote tiene 4 min de arrendamiento (uno solo, 60 s)
    client.get(f"/api/events/{ev.id}/print-jobs?scope=station")                                                                   # el barrido de vencidos no lo toca mientras la ventana está abierta
    assert {r.status for r in db.query(PrintJob).filter(PrintJob.id.in_([j["id"] for j in jobs]))} == {"sent"}
    for r in db.query(PrintJob).filter(PrintJob.id.in_([j["id"] for j in jobs])):
        r.sent_at = utcnow() - timedelta(seconds=61)                                                                              # nunca confirmó: vence
    db.commit()
    client.get(f"/api/events/{ev.id}/print-jobs?scope=station")
    assert {r.status for r in db.query(PrintJob).filter(PrintJob.id.in_([j["id"] for j in jobs]))} == {"queued"}


# ------------------------------------------------------------------------------------------------ 29-oct-2026, problemas D y E: una ventana por tanda y ventanas que no se acumulan
def test_the_print_page_accepts_several_people_one_sheet_each_with_the_same_fixed_parameters(client, setup):
    import pathlib
    ev, u = setup
    _as(client, "x1")
    html = client.get(f"/kiosk/{ev.id}/escarapela/imprimir/1001?users=1001,1002,1003").text
    assert 'const USER_IDS = ["1001", "1002", "1003"];' in html and "labelPage" in html and "break-after:page" in html
    assert 'const USER_IDS = ["1001"];' in client.get(f"/kiosk/{ev.id}/escarapela/imprimir/1001").text                      # una sola persona: como siempre
    src = pathlib.Path("templates/badge_print.html").read_text(encoding="utf-8")
    assert src.count("const PAGE_W = 62, PAGE_LEFT_MM = 0.5, PAGE_H = 99.8, MAX_IMG_H = 96;") == 1                           # los parámetros inamovibles siguen en UN solo lugar (las hojas los reutilizan)
    assert "addEventListener('afterprint', finish)" in src and "window.close()" in src                                       # la ventana se cierra sola al terminar (y por tiempo de respaldo)


def test_print_windows_have_a_fixed_name_close_the_previous_one_and_never_use_noopener():
    import pathlib
    br = pathlib.Path("static/js/badge-render.js").read_text(encoding="utf-8")
    assert "const PRINT_WINDOW = 'goldenweb_print';" in br and "window.open(url, PRINT_WINDOW, 'width=480,height=720')" in br and "printWin.close()" in br
    assert "noopener" not in br.replace("SIN `noopener`", "").replace("con él el navegador", "")                              # con noopener el nombre se ignora y no se puede cerrar la anterior
    rostro = pathlib.Path("templates/kiosk_rostro.html").read_text(encoding="utf-8")
    assert "'goldenweb_print'" in rostro and "noopener" not in rostro.split("goldenweb_print")[1][:120]
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "claimBatch" in sp and "batch=50" in sp and "print-jobs/release" in sp and "print-jobs/result-batch" in sp


def test_both_print_paths_give_the_same_label_geometry_vertical_and_horizontal_and_the_usb_uses_the_same_96mm_cap():
    import pathlib
    import subprocess
    r = subprocess.run(["node", "tests/js/label_paths_check.js"], capture_output=True, text=True, encoding="utf8", timeout=60)
    assert r.returncode == 0 and "label_paths_check OK" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "LabelCompose.fitToPaper(composed)" in sp                                         # el USB aplica el mismo largo máximo que la ventana de impresión (parámetro inamovible)
