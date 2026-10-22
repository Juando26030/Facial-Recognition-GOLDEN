"""Impresión compartida (orden del 22-oct-2026): interruptor APAGADO por defecto; con él apagado todo es igual que hoy. Encendido: equipos que reportan su
impresora, a qué equipo imprime cada usuario (hasta 3 por impresora), cola atómica sin duplicados, caducidad de 5 minutos y permisos del mismo evento."""
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
    return ev, users


def _as(client, username):
    client.cookies.clear()
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
def test_it_is_off_by_default_and_the_registration_page_is_unchanged(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    assert ev.shared_print_enabled is False
    factory.authorize(ev, factory.staff("digitador", "dig"))
    login(client, "dig")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "shared-print.js" not in page and "ql-usb.js" not in page and "html2canvas" not in page and "sharedPrintBar" not in page
    assert "js/badge-render.js" in page                                                            # la impresión de siempre sigue ahí
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
    assert r.json() == {"enabled": True, "mode": "self", "printer_name": "", "printer_ready": False, "serving": 0, "poll": False}
    _as(client, "x1")
    _beat(client, ev, printer=False)
    _as(client, "adm")
    users = {x["username"]: x for x in client.get(f"/api/events/{ev.id}/shared-print").json()["users"]}
    assert users["y1"]["eligible_printer"] is True and users["y1"]["device"]["printer_connected"] is True and users["y1"]["device"]["online"] is True
    assert users["y1"]["device"]["platform"] == "Android" and users["y1"]["device"]["browser"] == "Chrome"
    assert users["x1"]["eligible_printer"] is False and users["x2"]["device"] is None                # sin señal todavía


def test_a_printer_must_be_connected_reporting_and_serves_at_most_three(client, setup, db):
    ev, u = setup
    assert _route(client, ev, u["x1"], u["y1"]).status_code == 409                               # Y1 no ha reportado: no es elegible
    _as(client, "y1")
    _beat(client, ev, printer=True)
    for x in ("x1", "x2", "x3"):
        assert _route(client, ev, u[x], u["y1"]).status_code == 200, x
    r = _route(client, ev, u["x4"], u["y1"])
    assert r.status_code == 409 and "3 usuarios" in r.json()["detail"]
    assert _route(client, ev, u["x1"], u["x1"]).status_code == 400                               # a sí mismo: «en su propio equipo»
    _as(client, "y1")
    beat = _beat(client, ev, printer=True).json()
    assert beat["serving"] == 3 and beat["poll"] is True
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
