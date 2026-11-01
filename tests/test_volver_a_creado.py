"""Pedido B (pista Eventos en curso): devolver un evento «en curso» a «creado» (`POST /api/events/{id}/revert-to-created`). Solo admin y super_admin, no borra nada, queda el rastro, la purga
biométrica no corre, el registro se bloquea y se reabre al volver a «en curso», y los quioscos sin red sincronizan lo anterior al cambio durante 7 días (solo lo anterior; lo sin hora válida
queda marcado como dudoso)."""
import uuid
from datetime import timedelta

import pytest

from app import legal_texts, privacy
from app.models import AccessLog, AuditConsentLog, Event, EventAttendee, EventStatusChange, User
from app.timeutil import utcnow
from tests.conftest import accept, login
from tests.test_consent_flow import company_env  # noqa: F401  (fixture)


def _live(factory, db, **kw):
    """Evento en proceso con dos personas, una con rostro y aceptación, y dos ingresos."""
    ev = factory.event("en_proceso", facial_enabled=True, **kw)
    factory.person(ev, "1001", "Ana", "Prueba")
    factory.person(ev, "1002", "Beto", "Prueba")
    u = db.query(User).filter_by(id="1001", tenant_id=ev.tenant_id).first()
    u.face_encoding, u.face_captured_at = "[[0.1,0.2]]", utcnow()
    db.add_all([AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Nuevo", event_id=ev.id, timestamp=utcnow()), AccessLog(tenant_id=ev.tenant_id, user_id="1002", record_type="Existente", event_id=ev.id, timestamp=utcnow())])
    db.commit()
    accept(db, ev, "1001")
    return ev


def _revert(client, ev, **body):
    return client.post(f"/api/events/{ev.id}/revert-to-created", json=body)


def _counts(db, ev):
    db.expire_all()
    return (db.query(User).count(), db.query(EventAttendee).filter_by(event_id=ev.id).count(), db.query(AccessLog).filter_by(event_id=ev.id).count(), db.query(AuditConsentLog).filter_by(event_id=ev.id).count())


# ------------------------------------------------------------------------------------------------------------------------------------ permisos
@pytest.mark.parametrize("role, expected", [("digitador", 403), ("cliente", 403), ("coordinador", 403), ("comercial", 403), ("admin", 200), ("super_admin", 200)])
def test_only_admin_and_super_admin_can_revert(client, factory, db, role, expected):
    ev = _live(factory, db)
    staff = factory.staff(role, "quien")
    if role in ("digitador", "cliente"):
        factory.authorize(ev, staff)
    login(client, "quien")
    assert client.get(f"/api/events/{ev.id}/revert-to-created").status_code == expected          # la ventana de confirmación pide los mismos permisos
    assert _revert(client, ev).status_code == expected
    db.expire_all()
    assert db.get(Event, ev.id).status == ("creado" if expected == 200 else "en_proceso")


# ------------------------------------------------------------------------------------------------------------------------------------ el cambio
def test_the_state_changes_nothing_is_deleted_and_who_when_why_is_recorded(client, factory, db):
    factory.staff("admin", "root")
    ev = _live(factory, db)
    before = _counts(db, ev)
    login(client, "root")
    info = client.get(f"/api/events/{ev.id}/revert-to-created").json()
    assert (info["name"], info["status"], info["allowed"], info["attendees"], info["access_logs"], info["sync_days"]) == (ev.name, "en_proceso", True, 2, 2, 7)
    r = _revert(client, ev, reason="  Se abrió por error  ")
    assert r.status_code == 200 and r.json()["status"] == "creado" and (r.json()["attendees"], r.json()["access_logs"]) == (2, 2)
    db.expire_all()
    e = db.get(Event, ev.id)
    assert e.status == "creado" and e.finalized_at is None
    assert _counts(db, ev) == before                                                                 # ni personas, ni ingresos, ni consentimientos
    assert db.query(User).filter_by(id="1001").first().face_encoding == "[[0.1,0.2]]"                # tampoco lo biométrico
    row = db.query(EventStatusChange).filter_by(event_id=ev.id).one()
    assert (row.staff_username, row.from_status, row.to_status, row.reason, row.attendees_count, row.access_logs_count) == ("root", "en_proceso", "creado", "Se abrió por error", 2, 2)
    assert abs((utcnow() - row.at).total_seconds()) < 60
    hist = client.get(f"/api/events/{ev.id}/status-changes").json()
    assert hist["changes"][0]["by"] == "root" and hist["changes"][0]["reason"] == "Se abrió por error" and hist["doubtful"] == 0


def test_only_from_in_progress_to_created_finalized_is_not_touched(client, factory, db):
    factory.staff("admin", "root")
    login(client, "root")
    for status in ("creado", "finalizado"):
        ev = factory.event(status)
        r = _revert(client, ev)
        assert r.status_code == 409
        db.expire_all()
        assert db.get(Event, ev.id).status == status and db.query(EventStatusChange).filter_by(event_id=ev.id).count() == 0


def test_the_patch_keeps_its_block_and_the_revert_is_the_only_way(client, factory, db):
    factory.staff("coordinador", "coord")
    factory.staff("admin", "root")
    ev = _live(factory, db)
    login(client, "coord")
    r = client.patch(f"/api/events/{ev.id}", json={"status": "creado"})
    assert r.status_code == 400 and "Devolver a Creado" in r.json()["detail"]
    login(client, "root")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "creado"}).status_code == 400
    assert _revert(client, ev).status_code == 200


# ------------------------------------------------------------------------------------------------------------------------------------ la purga biométrica
def test_returning_the_event_does_not_start_the_seven_day_count_only_finalizing_does(client, factory, db):
    factory.staff("admin", "root")
    ev = _live(factory, db)
    login(client, "root")
    assert _revert(client, ev).status_code == 200
    db.expire_all()
    assert db.get(Event, ev.id).finalized_at is None                                                  # el reloj de los 7 días NO arrancó
    privacy.purge_expired(db, now=utcnow() + timedelta(days=20))                                      # aunque pasen 20 días en «creado»
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().face_encoding == "[[0.1,0.2]]"
    # contraste: finalizado hace 8 días SÍ se purga (la prueba mide algo)
    db.query(Event).filter_by(id=ev.id).update({"status": "finalizado", "finalized_at": utcnow() - timedelta(days=8)})
    db.commit()
    assert privacy.purge_expired(db)["people"] >= 1
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().face_encoding is None


# ------------------------------------------------------------------------------------------------------------------------------------ registro y reconocimiento
def test_registering_is_blocked_while_created_and_reopens_when_back_in_progress(client, factory, db):
    factory.staff("admin", "root")
    ev = _live(factory, db)
    login(client, "root")
    ok = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1002", "force": "true"})
    assert ok.status_code == 200
    assert _revert(client, ev).status_code == 200
    for path, data in (("/api/checkin-cedula", {"event_id": ev.id, "cedula": "1002", "force": "true"}), ("/api/register", {"event_id": ev.id, "id": "5000", "first_name": "N", "last_name": "N"})):
        r = client.post(path, data=data)
        assert r.status_code == 403 and "No se puede registrar" in r.json()["detail"], (path, r.status_code)
    db.expire_all()
    assert db.query(User).filter_by(id="5000").count() == 0
    assert client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso"}).status_code == 200                # de «creado» a «en curso» sigue siendo el PATCH de siempre
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1002", "force": "true"}).status_code == 200
    assert client.post("/api/register", data={"event_id": ev.id, "id": "5000", "first_name": "N", "last_name": "N"}).status_code == 200


def test_the_face_gate_is_closed_while_created(client, factory, db):
    from app import event_rules
    factory.staff("admin", "root")
    ev = _live(factory, db)
    login(client, "root")
    assert event_rules.allowed(db.get(Event, ev.id), "registration")
    _revert(client, ev)
    db.expire_all()
    e = db.get(Event, ev.id)
    assert not event_rules.allowed(e, "registration") and not event_rules.allowed(e, "temp_digitadores_enter")
    r = client.post("/api/recognize", data={"event_id": ev.id}, files={"file": ("f.jpg", b"x", "image/jpeg")})
    assert r.status_code == 403 and "No se puede registrar" in r.json()["detail"]


# ------------------------------------------------------------------------------------------------------------------------------------ sincronización sin red
def _reverted_hours_ago(client, factory, db, hours=2):
    """Evento devuelto a «creado» hace `hours` horas, con un digitador autorizado. Devuelve (evento, momento del retroceso)."""
    factory.staff("admin", "root")
    ev = _live(factory, db)
    login(client, "root")
    assert _revert(client, ev).status_code == 200
    when = utcnow() - timedelta(hours=hours)
    db.query(EventStatusChange).filter_by(event_id=ev.id).update({"at": when})
    dig = factory.staff("digitador", "dig1")
    factory.authorize(ev, dig)
    db.commit()
    login(client, "dig1")
    return ev, when


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_offline_ingresses_made_before_the_change_sync_later_ones_are_refused_and_no_hour_is_marked_doubtful(client, factory, db):
    from app.routers import api
    api._ROSTER_MAPS.clear()
    ev, when = _reverted_hours_ago(client, factory, db)
    h = api.roster_fingerprint(api.roster_salt(ev), "1002")
    records = [{"client_id": "antes", "h": h, "timestamp": _iso(when - timedelta(minutes=30))},
               {"client_id": "despues", "h": h, "timestamp": _iso(when + timedelta(minutes=30))},
               {"client_id": "sinhora", "h": h},
               {"client_id": "horamala", "h": h, "timestamp": "no es una hora"}]
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": records})
    assert r.status_code == 200, r.text
    res = {x["client_id"]: x for x in r.json()["results"]}
    assert res["antes"]["result"] == "created" and "doubtful" not in res["antes"]                       # anterior al retroceso: se guarda
    assert res["despues"] == {"client_id": "despues", "result": "unknown", "reason": "after_revert"}   # posterior: no se guarda
    assert res["sinhora"]["result"] == "created" and res["sinhora"]["doubtful"] is True and res["horamala"]["doubtful"] is True
    assert (r.json()["doubtful"], r.json()["after_revert"]) == (2, 1)
    db.expire_all()
    logs = {x.client_id: x for x in db.query(AccessLog).filter(AccessLog.event_id == ev.id, AccessLog.client_id.isnot(None))}
    assert set(logs) == {"antes", "sinhora", "horamala"} and logs["antes"].doubtful_reason is None
    assert logs["sinhora"].doubtful_reason == logs["horamala"].doubtful_reason == "sin_hora_valida"
    login(client, "root")
    assert client.get(f"/api/events/{ev.id}/status-changes").json()["doubtful"] == 2                  # consultable y contado para revisarlos
    login(client, "dig1")
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": records}).json()["created"] == 0          # idempotente


def test_the_window_closes_after_seven_days_and_the_digitador_gets_the_usual_403(client, factory, db):
    from app.routers import api
    api._ROSTER_MAPS.clear()
    ev, when = _reverted_hours_ago(client, factory, db, hours=24 * 8)
    h = api.roster_fingerprint(api.roster_salt(ev), "1002")
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "x", "h": h, "timestamp": _iso(when - timedelta(hours=1))}]})
    assert r.status_code == 403 and "todavía no ha comenzado" in r.json()["detail"]


def test_a_created_event_that_was_never_reverted_still_refuses_the_digitador(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("creado")
    dig = factory.staff("digitador", "dig1")
    factory.authorize(ev, dig)
    login(client, "dig1")
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "x", "cedula": "1"}]}).status_code == 403


def test_offline_signups_follow_the_same_rule(client, factory, db):
    ev, when = _reverted_hours_ago(client, factory, db)

    def op(op_id, cedula, ts=...):
        o = {"op_id": op_id, "type": "create_person", "fields": {"id": cedula, "first_name": "Nora", "last_name": "Sin Red"}}
        if ts is not ...:
            o["timestamp"] = ts
        return o
    r = client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [op("a", "7001", _iso(when - timedelta(minutes=20))), op("b", "7002", _iso(when + timedelta(minutes=20))), op("c", "7003")]})
    assert r.status_code == 200, r.text
    res = {x["op_id"]: x for x in r.json()["results"]}
    assert res["a"] == {"op_id": "a", "result": "ok"}
    assert res["b"]["result"] == "error" and res["b"]["reason"] == "after_revert"
    assert res["c"]["result"] == "ok" and res["c"]["doubtful"] is True
    db.expire_all()
    assert db.query(User).filter(User.id.in_(["7001", "7003"])).count() == 2 and db.query(User).filter_by(id="7002").count() == 0
    assert db.query(AccessLog).filter_by(client_id="c").one().doubtful_reason == "sin_hora_valida" and db.query(AccessLog).filter_by(client_id="a").one().doubtful_reason is None
    assert r.json()["doubtful"] == 1 and r.json()["after_revert"] == 1


def test_consents_are_always_kept_inside_the_window_and_only_counted(client, factory, db, company_env):  # noqa: F811
    ev, when = _reverted_hours_ago(client, factory, db)
    t = legal_texts.render(ev)

    def entry(uid, at=...):
        e = {"id": str(uuid.uuid4()), "user_id": uid, "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "device": "tablet-1"}
        if at is not ...:
            e["at"] = at
        return e
    body = {"entries": [entry("1001", _iso(when - timedelta(minutes=5))), entry("1002", _iso(when + timedelta(minutes=45))), entry("1001")]}
    r = client.post(f"/api/events/{ev.id}/consents", json=body)
    assert r.status_code == 200, r.text
    assert (r.json()["inserted"], r.json()["doubtful"], r.json()["after_revert"]) == (3, 1, 1)         # los tres se guardan (prueba legal de la persona)
    db.expire_all()
    assert db.query(AuditConsentLog).filter_by(event_id=ev.id).count() == 1 + 3                        # la aceptación del arranque + estas tres


def test_sync_is_unchanged_for_an_event_in_progress(client, factory, db):
    from app.routers import api
    api._ROSTER_MAPS.clear()
    ev = _live(factory, db)
    factory.person(ev, "1003", "Carla", "Prueba")                                                    # sin ingreso previo: la respuesta de siempre, sin «review»
    dig = factory.staff("digitador", "dig1")
    factory.authorize(ev, dig)
    login(client, "dig1")
    h = api.roster_fingerprint(api.roster_salt(ev), "1003")
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "k", "h": h}]}).json()
    assert r["results"] == [{"client_id": "k", "result": "created"}] and "doubtful" not in r          # sin retroceso: la respuesta de siempre
    db.expire_all()
    assert db.query(AccessLog).filter_by(client_id="k").one().doubtful_reason is None
