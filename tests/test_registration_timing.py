"""Fase 1A, PR1: medición del tiempo por registro (`access_logs.took_ms` / `ui_flow`, migración 0079, `app/regtime.py`).
Se comprueba: el servidor acota y limpia lo que manda el quiosco, un cliente viejo (sin `took_ms`) sigue registrando igual, todos los caminos de registro guardan el tiempo (cédula, alta, estado, sincronización
sin red, bandeja de salida), reenviar un lote no cambia nada, y el informe de p50/p90 es solo para admin y no lleva datos personales."""
import json
from datetime import datetime

import pytest

from app import regtime as timing
from app.models import AccessLog
from app.routers import api
from tests.conftest import login


# ------------------------------------------------------------------ limpieza (app/regtime.py)
@pytest.mark.parametrize("raw,expected", [
    (1500, 1500), ("1500", 1500), (" 1500 ", 1500), (1499.6, 1500), ("1234.4", 1234), (0, 0), ("0", 0), (600000, 600000), ("600000", 600000),
    (600001, None), (-1, None), ("-5", None), ("", None), ("   ", None), (None, None), ("abc", None), ("1e3", 1000), ("nan", None), ("inf", None), (float("nan"), None),
    (float("inf"), None), (True, None), (False, None), ([1], None), ({"a": 1}, None), ("9" * 40, None), ("12 34", None),
])
def test_clean_took_ms(raw, expected):
    assert timing.clean_took_ms(raw) == expected


@pytest.mark.parametrize("raw,expected", [("v0", "v0"), ("1a", "1a"), (" 1A ", "1a"), ("v_1", "v_1"), ("", None), (None, None), ("x" * 13, None), ("a b", None), ("v0;DROP", None), (5, None), ("á", None)])
def test_clean_ui_flow(raw, expected):
    assert timing.clean_ui_flow(raw) == expected


def test_measured_drops_the_label_when_there_is_no_valid_time():
    assert timing.measured("1200", "1a") == {"took_ms": 1200, "ui_flow": "1a"}
    assert timing.measured("basura", "1a") == {"took_ms": None, "ui_flow": None}
    assert timing.measured(None, None) == {"took_ms": None, "ui_flow": None}
    assert timing.measured("900", "MALA ETIQUETA!") == {"took_ms": 900, "ui_flow": None}


def test_percentiles_and_small_sample_flag():
    assert timing.percentile([], 50) is None and timing.percentile([7], 90) == 7
    vs = [1000, 2000, 3000, 4000, 10000]
    assert timing.percentile(vs, 50) == 3000 and timing.percentile(vs, 90) == 7600 and timing.percentile(vs, 0) == 1000 and timing.percentile(vs, 100) == 10000
    s = timing.summarize([10000, 1000, 3000])
    assert s == {"n": 3, "p50_ms": 3000, "p90_ms": 8600, "small_sample": True}
    assert timing.summarize(vs)["small_sample"] is False


def test_build_report_aggregates_without_edits_or_unmeasured_rows():
    rows = [(1, "v0", 4000, "Existente"), (1, "v0", 6000, "Nuevo"), (2, "1a", 2000, "Existente"), (2, None, 3000, "Existente"), (2, "1a", None, "Existente"), (2, "1a", 9999, "Actualizado")]
    rep = timing.build_report(rows, {1: "Ana Digitadora"})
    assert rep["registrations"] == 5 and rep["measured"] == 4 and rep["coverage_pct"] == 80.0       # «Actualizado» (una edición) no es un registro
    assert {f["ui_flow"]: f["n"] for f in rep["by_flow"]} == {"v0": 2, "1a": 1, "sin_etiqueta": 1}
    staff = {s["staff_id"]: s for s in rep["by_staff"]}
    assert staff[1]["name"] == "Ana Digitadora" and staff[1]["p50_ms"] == 5000 and staff[1]["registrations"] == 2
    assert staff[2]["name"] == "Digitador 2" and staff[2]["n"] == 2 and staff[2]["registrations"] == 3
    assert timing.build_report([], {})["coverage_pct"] is None


# ------------------------------------------------------------------ caminos del servidor
def _setup(client, factory, username="dig"):
    ev = factory.event("en_proceso")
    staff = factory.staff("digitador", username)
    factory.authorize(ev, staff)
    for cedula in ("1001", "1002", "1003", "1004", "1005", "1006"):
        factory.person(ev, cedula, f"N{cedula}", "Prueba")
    login(client, username)
    return ev, staff


def _log(db, ev, user_id):
    db.expire_all()
    return db.query(AccessLog).filter_by(event_id=ev.id, user_id=user_id).one()


def _checkin(client, ev, cedula, cid, **extra):
    return client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": cedula, "client_id": cid, "confirm": "true", **extra})


def test_checkin_saves_the_time_and_the_screen_label(client, factory, db):
    ev, _ = _setup(client, factory)
    r = _checkin(client, ev, "1001", "c-1", took_ms="2345", ui_flow="1a")
    assert r.status_code == 200 and r.json()["result"] == "SÍ"
    log = _log(db, ev, "1001")
    assert (log.took_ms, log.ui_flow) == (2345, "1a")


def test_an_old_client_without_the_fields_registers_exactly_as_before(client, factory, db):
    ev, _ = _setup(client, factory)
    assert _checkin(client, ev, "1001", "c-old").json()["result"] == "SÍ"
    log = _log(db, ev, "1001")
    assert (log.took_ms, log.ui_flow) == (None, None)


@pytest.mark.parametrize("raw", ["abc", "-10", "600001", "99999999999999999999", "", "NaN", "1;DROP TABLE access_logs"])
def test_absurd_values_are_ignored_but_the_registration_still_happens(client, factory, db, raw):
    ev, _ = _setup(client, factory)
    r = _checkin(client, ev, "1001", "c-bad", took_ms=raw, ui_flow="1a")
    assert r.status_code == 200 and r.json()["result"] == "SÍ"
    log = _log(db, ev, "1001")
    assert (log.took_ms, log.ui_flow) == (None, None)


def test_the_boundaries_are_kept_and_a_bad_label_is_dropped_alone(client, factory, db):
    ev, _ = _setup(client, factory)
    _checkin(client, ev, "1001", "c-max", took_ms="600000", ui_flow="v0")
    _checkin(client, ev, "1002", "c-zero", took_ms="0", ui_flow="Etiqueta muy larga!!")
    assert (_log(db, ev, "1001").took_ms, _log(db, ev, "1001").ui_flow) == (600000, "v0")
    assert (_log(db, ev, "1002").took_ms, _log(db, ev, "1002").ui_flow) == (0, None)


def test_a_replayed_checkin_does_not_rewrite_the_time(client, factory, db):
    ev, _ = _setup(client, factory)
    _checkin(client, ev, "1001", "c-same", took_ms="1000", ui_flow="v0")
    again = _checkin(client, ev, "1001", "c-same", took_ms="9999", ui_flow="1a")
    assert again.status_code == 200
    log = _log(db, ev, "1001")
    assert (log.took_ms, log.ui_flow) == (1000, "v0")


def test_new_person_register_saves_the_time(client, factory, db):
    ev, _ = _setup(client, factory)
    r = client.post("/api/register", data={"event_id": ev.id, "id": "7001", "first_name": "Nora", "last_name": "Nueva", "took_ms": "8100", "ui_flow": "v0"})
    assert r.status_code == 200, r.text
    assert (_log(db, ev, "7001").took_ms, _log(db, ev, "7001").ui_flow) == (8100, "v0")
    r2 = client.post("/api/register", data={"event_id": ev.id, "id": "7002", "first_name": "Viejo", "last_name": "Cliente"})          # sin los campos
    assert r2.status_code == 200 and _log(db, ev, "7002").took_ms is None


def test_register_of_an_existing_person_saves_the_time(client, factory, db):
    ev, _ = _setup(client, factory)
    r = client.post("/api/register", data={"event_id": ev.id, "id": "1003", "first_name": "N1003", "last_name": "Prueba", "took_ms": "3300", "ui_flow": "v0"})
    assert r.status_code == 200, r.text
    assert _log(db, ev, "1003").took_ms == 3300


def test_status_change_to_registered_saves_the_time(client, factory, db):
    ev, _ = _setup(client, factory)
    r = client.patch(f"/api/events/{ev.id}/users/1004/status", json={"status": "registrado", "took_ms": 5200, "ui_flow": "v0"})
    assert r.status_code == 200, r.text
    assert (_log(db, ev, "1004").took_ms, _log(db, ev, "1004").ui_flow) == (5200, "v0")
    r2 = client.patch(f"/api/events/{ev.id}/users/1005/status", json={"status": "registrado", "took_ms": "no"})
    assert r2.status_code == 200 and _log(db, ev, "1005").took_ms is None


def test_offline_sync_carries_the_time_and_a_resend_changes_nothing(client, factory, db):
    api._ROSTER_MAPS.clear()
    ev, _ = _setup(client, factory)
    body = {"records": [
        {"client_id": "s-1", "cedula": "1001", "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "method": "cedula", "took_ms": 4100, "ui_flow": "v0"},
        {"client_id": "s-2", "cedula": "1002", "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "method": "qr"},                                    # dispositivo viejo
        {"client_id": "s-3", "cedula": "1003", "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "took_ms": -3, "ui_flow": "1a"},                     # valor inválido
    ]}
    first = client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).json()
    assert first["created"] == 3
    assert [(_log(db, ev, u).took_ms, _log(db, ev, u).ui_flow) for u in ("1001", "1002", "1003")] == [(4100, "v0"), (None, None), (None, None)]
    body["records"][0]["took_ms"] = 77
    again = client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).json()
    assert again["created"] == 0 and all(r["result"] == "replayed" for r in again["results"])
    assert _log(db, ev, "1001").took_ms == 4100


def test_outbox_create_person_carries_the_time(client, factory, db):
    ev, _ = _setup(client, factory)
    op = {"op_id": "o-1", "type": "create_person", "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
          "fields": {"id": "8001", "first_name": "Sin", "last_name": "Red", "took_ms": 9100, "ui_flow": "v0"}}
    r = client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [op]})
    assert r.status_code == 200 and r.json()["results"][0]["result"] == "ok"
    assert (_log(db, ev, "8001").took_ms, _log(db, ev, "8001").ui_flow) == (9100, "v0")
    again = client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [{**op, "fields": {**op["fields"], "took_ms": 5}}]})
    assert again.json()["results"][0]["result"] == "replayed" and _log(db, ev, "8001").took_ms == 9100


# ------------------------------------------------------------------ informe (admin, solo agregados)
def _seed_timed(db, ev, staff, values, flow="v0"):
    for i, ms in enumerate(values):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=f"55500{i:02d}", event_id=ev.id, record_type="Nuevo", registered_by_staff_id=staff.id, took_ms=ms, ui_flow=flow, registration_method="tradicional"))
    db.commit()


def _seed_people(db, ev, n):
    from app.models import User
    for i in range(n):
        db.add(User(id=f"55500{i:02d}", tenant_id=ev.tenant_id, first_name="X", last_name="Y"))
    db.commit()


def test_timing_report_is_admin_only_and_gives_p50_p90_by_flow_and_staff(client, factory, db):
    ev, dig = _setup(client, factory, username="55512345")
    other = factory.staff("digitador", "55598765")
    factory.authorize(ev, other)
    _seed_people(db, ev, 12)
    _seed_timed(db, ev, dig, [2000, 3000, 4000, 5000, 6000, 7000])
    for i, ms in enumerate([1000, 1500]):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=f"55500{6 + i:02d}", event_id=ev.id, record_type="Existente", registered_by_staff_id=other.id, took_ms=ms, ui_flow="1a"))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="5550010", event_id=ev.id, record_type="Existente", registered_by_staff_id=other.id))           # registro sin medir (antes de esta medición)
    db.commit()
    url = f"/api/events/{ev.id}/timing-report"
    assert client.get(url).status_code == 403                                                  # el digitador no ve el informe
    factory.staff("admin", "root")
    login(client, "root")
    r = client.get(url)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["registrations"] == 9 and d["measured"] == 8 and d["coverage_pct"] == 88.9
    assert d["overall"]["n"] == 8 and d["overall"]["p50_ms"] == 3500
    flows = {f["ui_flow"]: f for f in d["by_flow"]}
    assert flows["v0"]["n"] == 6 and flows["v0"]["p50_ms"] == 4500 and flows["v0"]["p90_ms"] == 6500 and flows["v0"]["small_sample"] is False
    assert flows["1a"]["n"] == 2 and flows["1a"]["small_sample"] is True
    by_staff = {s["staff_id"]: s for s in d["by_staff"]}
    assert by_staff[dig.id]["n"] == 6 and by_staff[dig.id]["registrations"] == 6 and by_staff[other.id]["n"] == 2 and by_staff[other.id]["registrations"] == 3
    blob = json.dumps(d, ensure_ascii=False)
    assert "55512345" not in blob and "55598765" not in blob, "el usuario del digitador es su cédula: no sale en el informe"
    assert not any(f"55500{i:02d}" in blob for i in range(12)), "ninguna cédula de asistente sale en el informe"


def test_timing_report_for_an_event_without_registrations(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    login(client, "root")
    d = client.get(f"/api/events/{ev.id}/timing-report").json()
    assert d["registrations"] == 0 and d["measured"] == 0 and d["coverage_pct"] is None and d["overall"]["p50_ms"] is None and d["by_staff"] == []


def test_the_stats_page_shows_the_timing_section_only_to_admins(client, factory):
    coord = factory.staff("coordinador", "coord9")
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", coordinator=coord)
    login(client, "coord9")
    page = client.get(f"/kiosk/{ev.id}/estadisticas")
    assert page.status_code == 200 and "timing-report" not in page.text
    login(client, "root")
    assert "timing-report" in client.get(f"/kiosk/{ev.id}/estadisticas").text


def test_the_kiosk_page_loads_the_timer_before_the_directory_script(client, factory):
    ev, _ = _setup(client, factory)
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert "js/timing.js" in page and page.index("js/timing.js") < page.index("js/directory.js")
