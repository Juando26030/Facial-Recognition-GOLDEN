"""Fase 3 (ajustes antes del commit 3): sincronización por huella (sin cédula en claro), ventana de 7 días tras finalizar, marcas de tiempo hasta 30 días y sonda `/api/ping-auth`."""
import time
from datetime import timedelta

import pytest

from app.models import AccessLog, EventAttendee, User
from app.routers import api
from app.timeutil import utcnow
from tests.conftest import login


@pytest.fixture(autouse=True)
def _fresh_fingerprint_maps():
    api._ROSTER_MAPS.clear()          # el mapa se cachea por id de evento y la base de las pruebas reutiliza los ids
    yield
    api._ROSTER_MAPS.clear()


def _setup(factory, people=("1001", "1002"), **event_kw):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", **event_kw)
    for uid in people:
        factory.person(ev, uid, f"N{uid}", "Prueba")
    return ev


def _h(ev, cedula):
    return api.roster_fingerprint(api.roster_salt(ev), cedula)


def _sync(client, ev, records):
    return client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": records})


def test_sync_by_fingerprint_resolves_the_person_and_stays_idempotent(client, factory, db):
    ev = _setup(factory)
    login(client, "root")
    body = [{"client_id": "k1-1", "h": _h(ev, "1001"), "timestamp": "2026-09-30T10:00:00Z", "method": "qr"}]
    first = _sync(client, ev, body).json()
    assert first["results"] == [{"client_id": "k1-1", "result": "created"}] and first["created"] == 1
    log = db.query(AccessLog).filter_by(event_id=ev.id, client_id="k1-1").one()
    assert log.user_id == "1001" and log.registration_method == "qr" and log.timestamp.isoformat().startswith("2026-09-30T10:00:00")
    again = _sync(client, ev, body).json()                                           # reintento del mismo lote: nada nuevo
    assert again["results"] == [{"client_id": "k1-1", "result": "replayed"}] and again["created"] == 0
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 1


def test_sync_by_fingerprint_flags_review_when_another_client_id_already_entered(client, factory, db):
    ev = _setup(factory)
    login(client, "root")
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "client_id": "otro-quiosco-1", "confirm": "true", "force": "true"}).json()["result"] == "SÍ"
    r = _sync(client, ev, [{"client_id": "k1-1", "h": _h(ev, "1001")}, {"client_id": "k1-2", "h": _h(ev, "1002")}, {"client_id": "k1-3", "h": _h(ev, "1002")}]).json()
    assert [(x["result"], x.get("review", False)) for x in r["results"]] == [("created", True), ("created", False), ("created", True)]      # la 1002 repetida dentro del lote también se marca
    assert r["review"] == 2


def test_sync_unknown_fingerprint_wrong_event_and_malformed(client, factory, db):
    ev = _setup(factory)
    other = factory.event("en_proceso")
    factory.person(other, "1001", "Otra", "Persona")                                  # misma cédula en OTRO evento
    login(client, "root")
    recs = [{"client_id": "u1", "h": "0123456789abcdef"},                           # huella que no existe
            {"client_id": "u2", "h": _h(other, "1001")},                             # huella calculada con la sal de OTRO evento
            {"client_id": "u3", "h": "NO-ES-HEX"},                                   # mal formada
            {"client_id": "", "h": _h(ev, "1001")},                                  # sin client_id
            {"client_id": "u5"},                                                     # sin cédula ni huella
            "basura"]
    r = _sync(client, ev, recs).json()
    assert [x["result"] for x in r["results"]] == ["unknown", "unknown", "invalid", "invalid", "invalid", "invalid"]
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == 0
    assert _sync(client, other, [{"client_id": "w1", "h": _h(other, "1001")}]).json()["created"] == 1      # en su evento sí


def test_sync_legacy_cedula_still_works_alongside_fingerprints(client, factory, db):
    ev = _setup(factory)
    login(client, "root")
    r = _sync(client, ev, [{"client_id": "a1", "cedula": "1001"}, {"client_id": "a2", "h": _h(ev, "1002")}]).json()
    assert [x["result"] for x in r["results"]] == ["created", "created"]


def test_sync_finds_someone_added_after_the_fingerprint_map_was_cached(client, factory, db, monkeypatch):
    ev = _setup(factory)
    login(client, "root")
    assert _sync(client, ev, [{"client_id": "m1", "h": _h(ev, "1001")}]).json()["created"] == 1          # arma y cachea el mapa
    factory.person(ev, "1003", "Nuevo", "Despues")
    monkeypatch.setattr(api, "ROSTER_MAP_MIN_REBUILD", 0.0)
    assert _sync(client, ev, [{"client_id": "m2", "h": _h(ev, "1003")}]).json()["results"][0]["result"] == "created"
    monkeypatch.setattr(api, "ROSTER_MAP_MIN_REBUILD", 3600.0)                         # huellas inventadas NO reconstruyen el mapa en cada lote
    calls = []
    real = api._roster_map
    monkeypatch.setattr(api, "_roster_map", lambda *a, **k: calls.append(k.get("force")) or real(*a, **k))
    assert _sync(client, ev, [{"client_id": "m3", "h": "f" * 16}]).json()["results"][0]["result"] == "unknown"
    assert calls == [None, True]


def test_sync_batch_of_500_is_complete_idempotent_and_fast(client, factory, db):
    n = 500
    ev = _setup(factory, people=())
    ids = [f"{2000000000 + i}" for i in range(n)]
    db.bulk_save_objects([User(id=i, tenant_id=ev.tenant_id, first_name="N", last_name="P") for i in ids])
    db.commit()
    db.bulk_save_objects([EventAttendee(event_id=ev.id, user_id=i, tenant_id=ev.tenant_id) for i in ids])
    db.commit()
    login(client, "root")
    recs = [{"client_id": f"b-{i}", "h": _h(ev, ids[i]), "timestamp": (utcnow() - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")} for i in range(n)]
    t = time.perf_counter()
    r = _sync(client, ev, recs)
    elapsed = time.perf_counter() - t
    print(f"sync 500: {elapsed * 1000:.0f} ms")
    assert r.status_code == 200 and r.json()["created"] == n and r.json()["review"] == 0
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == n and elapsed < 15
    again = _sync(client, ev, recs).json()                                            # reintento del lote completo
    assert again["created"] == 0 and {x["result"] for x in again["results"]} == {"replayed"}
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == n
    assert _sync(client, ev, recs + [{"client_id": "x", "h": _h(ev, ids[0])}]).status_code == 400          # 501 registros


def test_sync_timestamps_up_to_30_days_old_are_kept_and_older_use_server_time(client, factory, db):
    ev = _setup(factory)
    login(client, "root")
    old_ok, too_old = (utcnow() - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ"), (utcnow() - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _sync(client, ev, [{"client_id": "t1", "h": _h(ev, "1001"), "timestamp": old_ok}, {"client_id": "t2", "h": _h(ev, "1002"), "timestamp": too_old}])
    t1 = db.query(AccessLog).filter_by(client_id="t1").one().timestamp
    t2 = db.query(AccessLog).filter_by(client_id="t2").one().timestamp
    assert utcnow() - t1 > timedelta(days=28) and utcnow() - t2 < timedelta(minutes=5)


def test_digitador_can_sync_for_7_days_after_the_event_finished_but_not_later(client, factory, db):
    ev = _setup(factory)
    dig = factory.staff("digitador", "dig")
    factory.authorize(ev, dig)
    other = factory.staff("digitador", "dig2")
    login(client, "dig")
    rec = [{"client_id": "f1", "h": _h(ev, "1001")}]
    assert _sync(client, ev, rec).status_code == 200                                  # en proceso
    ev.status = "finalizado"
    db.commit()
    ev.finalized_at = utcnow() - timedelta(days=6, hours=23)
    db.commit()
    assert _sync(client, ev, [{"client_id": "f2", "h": _h(ev, "1002")}]).json()["created"] == 1          # 6 días 23 h después de finalizar: se acepta
    ev.finalized_at = utcnow() - timedelta(days=7, hours=1)
    db.commit()
    r = _sync(client, ev, [{"client_id": "f3", "h": _h(ev, "1001")}])
    assert r.status_code == 403 and "7 días" in r.json()["detail"]
    login(client, other.username)
    assert _sync(client, ev, rec).status_code == 403                                  # sin autorización para este evento
    ev.finalized_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert _sync(client, ev, rec).status_code == 403                                  # el permiso por evento sigue siendo obligatorio


def test_ping_auth_is_light_and_tells_session_state(client, factory):
    factory.staff("admin", "root")
    assert client.get("/api/ping-auth").status_code == 401                            # sesión vencida / sin sesión
    login(client, "root")
    r = client.get("/api/ping-auth")
    assert r.status_code == 200 and r.json() == {"ok": True} and r.headers["cache-control"] == "no-store"
