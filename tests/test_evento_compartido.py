"""Evento COMPARTIDO entre varios servidores locales con la nube como puente (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md).

Nube: varios servidores pueden tener el mismo evento si está marcado «compartido»; cada uno sube lo suyo y baja lo de los demás (/changes con cursor).
Servidor local: lo bajado se aplica sin duplicar, se marca `from_peer` y nunca se vuelve a subir; los identificadores que sube llevan el prefijo del servidor.
"""
import json
import pathlib

import pytest

from app import event_lease, node_auth, node_sync, peer_changes, versioning
from app.models import AccessLog, Event, EventAttendee, LocalNode, PrintLog, User
from app.timeutil import utcnow
from tests.conftest import login

SRC = pathlib.Path(__file__).resolve().parent.parent
HEAD = versioning.schema_head()


def _hdr(token):
    return {"X-Node-Token": token, "X-Node-Schema": HEAD, "X-Node-Version": f"abc|{HEAD}"}


def _nodes(db, factory, *names):
    admin = factory.staff("admin", "adm_comp")
    out = []
    for n in names:
        token, digest = node_auth.generate_token()
        db.add(LocalNode(name=n, token_hash=digest, created_by_id=admin.id))
        out.append(token)
    db.commit()
    return out


# ------------------------------------------------------------------ puro
def test_cursor_is_cleaned_and_tag_is_unique_per_installation(monkeypatch):
    assert peer_changes.clean_cursor('{"l": "5", "a": -3, "p": "x"}') == {k: (5 if k == "l" else 0) for k in peer_changes.KEYS}
    assert peer_changes.clean_cursor(None) == dict.fromkeys(peer_changes.KEYS, 0)
    monkeypatch.setattr("app.local_env.refresh", lambda: None)
    monkeypatch.setenv("INSTALLATION_ID", "ab" * 16)
    assert peer_changes.node_tag() == "s" + ("ab" * 5)
    monkeypatch.setenv("INSTALLATION_ID", "")
    monkeypatch.setenv("NODE_NAME", "Portátil Norte 2")
    assert peer_changes.node_tag() == "sporttilnor"


def test_migration_0160_shape():
    src = (SRC / "alembic" / "versions" / "0160_shared_local_events.py").read_text(encoding="utf-8")
    assert 'revision = "0160_shared_local_events"' in src and len("0160_shared_local_events") <= 32 and 'down_revision = "0159_node_disabled_at"' in src
    for col in ("local_shared", "peer_cursor", "from_peer", "event_local_nodes"):
        assert col in src


# ------------------------------------------------------------------ nube
def test_not_shared_keeps_one_writer(client, factory, db):
    a, b = _nodes(db, factory, "Puerta A", "Puerta B")
    ev = factory.event("en_proceso")
    assert client.post(f"/api/node/events/{ev.id}/lease", headers=_hdr(a)).status_code == 200
    r = client.post(f"/api/node/events/{ev.id}/lease", headers=_hdr(b))
    assert r.status_code == 409 and "compartido" in r.json()["detail"]
    assert client.get(f"/api/node/events/{ev.id}/changes", headers=_hdr(a)).status_code == 409


def test_shared_event_two_servers_see_each_other_and_leave_one_by_one(client, factory, db):
    a, b = _nodes(db, factory, "Puerta A", "Puerta B")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    factory.person(ev, "2002", "Beto", "Dos")
    ev_id = ev.id
    factory.staff("coordinador", "coord_comp")
    login(client, "coord_comp")
    r = client.post(f"/api/events/{ev_id}/lease/shared", json={"enabled": True})
    assert r.status_code == 200 and r.json()["shared"] is True
    client.get("/logout")
    la = client.post(f"/api/node/events/{ev_id}/lease", headers=_hdr(a)).json()
    lb = client.post(f"/api/node/events/{ev_id}/lease", headers=_hdr(b)).json()
    assert la["shared"] and la["peer_cursor"] is not None and lb["joined"] is True and lb["nodes"] == ["Puerta A", "Puerta B"]
    assert client.get(f"/api/node/events/{ev_id}/package", headers=_hdr(b)).status_code == 200          # el segundo también baja el paquete
    cur_b = lb["peer_cursor"]
    # la puerta A registra a 1001 y crea a 3003; la puerta B lo ve en /changes
    assert client.post(f"/api/node/events/{ev_id}/access-logs", headers=_hdr(a), json={"records": [{"client_id": "sA-1-l1", "cedula": "1001", "method": "cedula"}]}).json()["results"][0]["result"] == "created"
    op = {"op_id": "sA-1-p9", "type": "create_person", "timestamp": utcnow().isoformat(), "fields": {"id": "3003", "first_name": "Carla", "last_name": "Tres"}}
    assert client.post(f"/api/node/events/{ev_id}/outbox", headers=_hdr(a), json={"ops": [op]}).json()["results"][0]["result"] == "ok"
    ch = client.get(f"/api/node/events/{ev_id}/changes", params=cur_b, headers=_hdr(b)).json()
    assert {p["cedula"] for p in ch["persons"]} == {"3003"}
    assert {(r["cedula"], r["record_type"]) for r in ch["access_logs"]} == {("1001", "Existente"), ("3003", "Nuevo")}
    assert ch["more"] is False and ch["cursor"]["l"] > cur_b["l"]
    again = client.get(f"/api/node/events/{ev_id}/changes", params=ch["cursor"], headers=_hdr(b)).json()
    assert again["persons"] == [] and again["access_logs"] == []
    far = {k: 10**9 for k in peer_changes.KEYS}                       # la nube lee TODOS los cursores (no solo l/a/p/c): ninguno vuelve a 0
    assert client.get(f"/api/node/events/{ev_id}/changes", params=far, headers=_hdr(b)).json()["cursor"] == far
    # la nube sigue en solo lectura; B sale primero y el evento sigue en A
    assert client.post(f"/api/node/events/{ev_id}/release", json={"pending": 0}, headers=_hdr(b)).json()["leased"] is True
    db.expire_all()
    e = db.get(Event, ev_id)
    assert event_lease.writers(e) == ["Puerta A"]
    login(client, "coord_comp")
    assert client.post(f"/api/events/{ev_id}/lease/shared", json={"enabled": False}).status_code == 200          # con uno solo ya se puede dejar de compartir
    client.get("/logout")
    assert client.post(f"/api/node/events/{ev_id}/release", json={"pending": 0}, headers=_hdr(a)).json()["leased"] is False


def test_cannot_stop_sharing_with_two_servers_and_ping_lists_shared(client, factory, db):
    a, b = _nodes(db, factory, "Puerta A", "Puerta B")
    ev = factory.event("en_proceso", local_shared=True)
    client.post(f"/api/node/events/{ev.id}/lease", headers=_hdr(a))
    client.post(f"/api/node/events/{ev.id}/lease", headers=_hdr(b))
    assert client.get("/api/node/ping", headers=_hdr(b)).json()["shared_events"] == [ev.id]
    factory.staff("admin", "adm_comp2")
    login(client, "adm_comp2")
    assert client.post(f"/api/events/{ev.id}/lease/shared", json={"enabled": False}).status_code == 409


# ------------------------------------------------------------------ servidor local: aplicar lo bajado
def test_apply_changes_is_idempotent_skips_own_echo_and_marks_from_peer(db, factory):
    ev = factory.event("en_proceso", cloud_event_id=77, local_shared=True)
    factory.person(ev, "1001")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id, client_id="smio-1-l1", timestamp=utcnow()))
    db.commit()
    data = {"persons": [{"cedula": "3003", "first_name": "Carla", "last_name": "Tres", "categories": [], "origin": "manual", "code": None},
                        {"cedula": "1001", "first_name": "OTRO NOMBRE"}],
            "access_logs": [{"client_id": "smio-1-l1", "cedula": "1001", "record_type": "Existente"},          # vuelve el propio: no se repite
                            {"client_id": "smio-1-l99", "cedula": "1001", "record_type": "Existente"},         # propio (prefijo de este servidor): no se aplica
                            {"client_id": "sotro-4-l7", "cedula": "3003", "record_type": "Nuevo", "timestamp": utcnow().isoformat()}],
            "print_logs": [{"cedula": "3003", "printed_at": utcnow().replace(microsecond=0).isoformat(), "kind": "normal"}],
            "person_changes": []}
    added = peer_changes.apply_changes(db, ev, data, tag="smio")
    db.commit()
    assert added == {"persons": 1, "access_logs": 1, "print_logs": 1, "person_changes": 0}
    assert peer_changes.apply_changes(db, ev, data, tag="smio") == {"persons": 0, "access_logs": 0, "print_logs": 0, "person_changes": 0}
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().first_name == "Ana"          # no se pisan los datos de quien ya estaba
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="3003").one()
    assert att.from_peer is True
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="3003").one().from_peer is True
    assert db.query(PrintLog).filter_by(event_id=ev.id, user_id="3003").one().from_peer is True


@pytest.fixture()
def local_env(monkeypatch):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("PRODUCTION_URL", "https://nube.example")
    monkeypatch.setenv("NODE_TOKEN", "gwn_test")
    monkeypatch.setattr(peer_changes, "node_tag", lambda: "smio")
    calls = []
    state = {"changes": {"cursor": {"l": 10, "a": 5, "p": 0, "c": 0}, "persons": [{"cedula": "4004", "first_name": "Dani"}],
                         "access_logs": [{"client_id": "sotro-1-l3", "cedula": "4004", "record_type": "Nuevo"}], "print_logs": [], "person_changes": [], "more": False}}

    def fake(method, path, body=None):
        calls.append((method, path, body))
        if "/changes?" in path:
            return state["changes"]
        if path.endswith("/outbox"):
            return {"results": [{"op_id": o["op_id"], "result": "ok"} for o in body["ops"]]}
        if path.endswith("/access-logs"):
            return {"results": [{"client_id": r["client_id"], "result": "created"} for r in body["records"]]}
        if path.endswith("/records"):
            return {"ok": True}
        return {}
    monkeypatch.setattr(node_sync, "_call", fake)
    return calls


def test_shared_cycle_uploads_with_own_prefix_downloads_and_never_sends_back(db, factory, local_env):
    ev = factory.event("en_proceso", cloud_event_id=77, local_shared=True)
    factory.person(ev, "1001")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id, timestamp=utcnow()))
    db.commit()
    assert node_sync.shared_events_now(db) == [ev]
    out = node_sync.sync_shared(db, ev)
    assert out["ok"] and out["pulled"]["persons"] == 1 and out["pulled"]["access_logs"] == 1
    sent = [c[2] for c in local_env if c[1].endswith("/access-logs")][0]["records"]
    assert [r["client_id"] for r in sent] == [f"smio-{ev.id}-l{db.query(AccessLog).filter_by(user_id='1001').one().id}"]
    db.expire_all()
    e = db.get(Event, ev.id)
    assert json.loads(e.peer_cursor)["l"] == 10 and peer_changes.last_pull_at(e)
    assert node_sync.pending_counts(db, e)["total"] == 0          # lo bajado (4004) no queda pendiente de subir
    local_env.clear()
    node_sync.sync_shared(db, e)
    assert not [c for c in local_env if c[1].endswith("/outbox") or c[1].endswith("/access-logs")]


def test_ping_turns_on_sharing_for_a_server_that_already_had_the_event(db, factory):
    ev = factory.event("en_proceso", cloud_event_id=88)
    node_sync._refresh_shared_flags(db, {"shared_events": [88]})
    db.expire_all()
    assert db.get(Event, ev.id).local_shared is True
    node_sync._refresh_shared_flags(db, {"shared_events": []})
    db.expire_all()
    assert db.get(Event, ev.id).local_shared is False


# ------------------------------------------------------------------ 0160: lo que antes no subía (ediciones, deshacer registro, áreas, inventario, turnos)
def _door_setup(db, factory, **ev_extra):
    from app.models import EventArea, InventoryItem
    ev = factory.event("en_proceso", **ev_extra)
    factory.person(ev, "1001")
    db.add(EventArea(event_id=ev.id, name="Auditorio"))
    parent = InventoryItem(event_id=ev.id, name="Comida", initial_qty=0)
    db.add(parent)
    db.flush()
    db.add(InventoryItem(event_id=ev.id, name="Perro", initial_qty=10, parent_id=parent.id))
    db.commit()
    return ev


def test_cloud_applies_edits_areas_deliveries_turns_calls_idempotently(client, factory, db):
    from app.models import AreaMovement, InventoryDelivery, PersonChangeLog, QueueCall, QueueTurn
    (a,) = _nodes(db, factory, "Puerta A")
    ev = _door_setup(db, factory)
    ev.local_node_name = "Puerta A"
    db.commit()
    t0 = utcnow().replace(microsecond=0)
    body = {"edits": [{"cedula": "1001", "field": "email", "old": None, "new": "ana@x.co", "at": t0.isoformat(), "source": "edit"},
                      {"cedula": "1001", "field": "opcional_2", "old": None, "new": "Bogotá", "at": t0.isoformat(), "source": "edit"}],
            "areas": [{"cedula": "1001", "area": "auditorio", "direction": "in", "method": "qr", "at": t0.isoformat()}],
            "deliveries": [{"cedula": "1001", "item": "Perro", "parent": "Comida", "batch": "b1", "qty": 2, "at": t0.isoformat()}],
            "turns": [{"cedula": "1001", "lane": "A", "number": 5, "rank": 5, "status": "waiting", "created_at": t0.isoformat()}],
            "calls": [{"lane": "A", "number": 5, "desk": "Caja 1", "at": t0.isoformat()}], "turn_status": []}
    r = client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(a))
    assert r.status_code == 200, r.text
    assert {k: v for k, v in r.json()["saved"].items() if v} == {"edits": 2, "areas": 1, "deliveries": 1, "turns": 1, "calls": 1}
    assert client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(a)).json()["saved"]["areas"] == 0          # repetir no duplica
    db.expire_all()
    u = db.query(User).filter_by(id="1001").one()
    assert u.email == "ana@x.co" and u.get_extras().get("opcional_2") == "Bogotá"
    assert db.query(AreaMovement).count() == 1 and db.query(InventoryDelivery).one().qty == 2 and db.query(PersonChangeLog).count() == 2
    turn = db.query(QueueTurn).one()
    assert turn.status == "called" and turn.desk == "Caja 1" and db.query(QueueCall).count() == 1
    # una edición más VIEJA del mismo campo queda en el historial pero no pisa el valor; el estado del turno solo avanza
    old = {"edits": [{"cedula": "1001", "field": "email", "new": "viejo@x.co", "at": "2020-01-01T00:00:00"}],
           "turn_status": [{"cedula": "1001", "status": "done", "done_at": utcnow().isoformat()}], "turns": [{"cedula": "9999", "lane": "A", "number": 5}]}
    out = client.post(f"/api/node/events/{ev.id}/extra", json=old, headers=_hdr(a)).json()["saved"]
    assert out["edits"] == 1 and out["turn_status"] == 1
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().email == "ana@x.co" and db.query(QueueTurn).one().status == "done"


def test_undo_registration_and_birth_date_are_applied_in_the_cloud(client, factory, db):
    (a,) = _nodes(db, factory, "Puerta A")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    ev.local_node_name = "Puerta A"
    db.commit()
    when = utcnow().replace(microsecond=0)
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id, client_id="x1", timestamp=when))
    db.commit()
    later = when.replace(year=when.year) + __import__("datetime").timedelta(seconds=30)
    body = {"print_logs": [], "person_changes": [{"cedula": "1001", "at": later.isoformat(), "kind": "registration_status", "old_value": "Registrado", "new_value": "No registrado"},
                                                 {"cedula": "1001", "at": later.isoformat(), "kind": "birth_date", "old_value": None, "new_value": "2012-05-01"}]}
    assert client.post(f"/api/node/events/{ev.id}/records", json=body, headers=_hdr(a)).json()["ok"]
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 0          # deshecho
    u = db.query(User).filter_by(id="1001").one()
    assert str(u.birth_date) == "2012-05-01" and u.is_biometric_enabled is False


def test_local_uploads_extra_after_package_and_counts_it_pending(db, factory, monkeypatch):
    from datetime import timedelta
    from app.models import AreaMovement, EventArea, QueueTurn
    monkeypatch.setenv("LOCAL_SERVER", "1")
    sent = []

    def fake(method, path, body=None):
        sent.append((path, body))
        return {"ok": True, "saved": {}}
    monkeypatch.setattr(node_sync, "_call", fake)
    ev = _door_setup(db, factory, cloud_event_id=77)
    ev.sync_package_at = utcnow() - timedelta(minutes=5)
    area = db.query(EventArea).filter_by(event_id=ev.id).one()
    db.add(AreaMovement(event_id=ev.id, area_id=area.id, user_id="1001", tenant_id=ev.tenant_id, direction="in", timestamp=utcnow() - timedelta(hours=1)))          # viene del paquete: no sube
    db.add(AreaMovement(event_id=ev.id, area_id=area.id, user_id="1001", tenant_id=ev.tenant_id, direction="in", timestamp=utcnow()))
    db.add(QueueTurn(event_id=ev.id, user_id="1001", lane="B", number=1, rank=1, token="tok-1", created_at=utcnow()))
    db.commit()
    assert node_sync.pending_counts(db, ev)["extra"] == 2
    node_sync._push_extra(db, ev)
    body = [b for p, b in sent if p.endswith("/extra")][0]
    assert [x["area"] for x in body["areas"]] == ["Auditorio"] and body["turns"][0]["lane"] == "B"
    db.expire_all()
    e = db.get(Event, ev.id)
    assert node_sync.pending_counts(db, e)["extra"] == 0 and e.sync_turn_at is not None
    # el turno ya enviado cambia de estado: sube solo su estado
    t = db.query(QueueTurn).one()
    t.status, t.called_at, t.desk = "called", utcnow() + timedelta(seconds=1), "Caja 3"
    db.commit()
    sent.clear()
    node_sync._push_extra(db, db.get(Event, ev.id))
    assert [b["turn_status"][0]["status"] for p, b in sent] == ["called"]
    assert "area_movements" not in [t for t, _c, _l in node_sync.LOCAL_ONLY]


def test_peer_pull_applies_extra_and_undo(db, factory):
    from app.models import AreaMovement, QueueTurn
    ev = _door_setup(db, factory, cloud_event_id=77, local_shared=True)
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id, client_id="local-1", timestamp=utcnow()))
    db.commit()
    t0 = utcnow().replace(microsecond=0)
    from datetime import timedelta
    data = {"areas": [{"cedula": "1001", "area": "Auditorio", "direction": "in", "at": t0.isoformat()}],
            "turns": [{"cedula": "1001", "lane": "C", "number": 2, "rank": 2, "status": "waiting"}],
            "edits": [{"cedula": "1001", "field": "phone", "new": "3001234567", "at": t0.isoformat()}],
            "person_changes": [{"cedula": "1001", "at": (t0 + timedelta(minutes=1)).isoformat(), "kind": "registration_status", "new_value": "No registrado"}]}
    added = peer_changes.apply_changes(db, ev, data, tag="smio")
    db.commit()
    assert added["areas"] == 1 and added["turns"] == 1 and added["edits"] == 1 and added["person_changes"] == 1
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == 0
    assert db.query(AreaMovement).one().from_peer is True and db.query(QueueTurn).one().from_peer is True
    assert db.query(User).filter_by(id="1001").one().phone == "3001234567"
    e = db.get(Event, ev.id)
    assert node_sync.pending_counts(db, e)["extra"] == 0          # lo bajado no vuelve a subir


# ------------------------------------------------------------------ 0160: ruleta, expositores, aceptaciones, autorizaciones y COPIA COMPLETA
def test_cloud_applies_roulette_leads_acceptances_and_consents(client, factory, db):
    from app.models import AuditConsentLog, EventExhibitor, ExhibitorLead, RouletteDraw, WebAcceptance
    (a,) = _nodes(db, factory, "Puerta A")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    ev.local_node_name = "Puerta A"
    db.commit()
    t0 = utcnow().replace(microsecond=0)
    body = {"roulette": [{"label": "Rifa 1", "mode": "attendees", "is_random": True, "candidates": 30, "winners_json": '["1001"]', "at": t0.isoformat()}],
            "leads": [{"cedula": "1001", "at": t0.isoformat(), "exhibitor": {"name": "Stand Café", "contact_name": "Luis", "email": "l@x.co"}}],
            "acceptances": [{"cedula": "1001", "created_at": t0.isoformat(), "verified_at": t0.isoformat(), "verified_via": "staff"}],
            "consents": [{"id": "6f1c2b9e-0000-4000-8000-000000000001", "cedula": "1001", "at": t0.isoformat(), "version": "v1", "legal_text_hash": "ab" * 32,
                          "accepted": True, "adult": True, "reason": "consent"}]}
    saved = client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(a)).json()["saved"]
    assert (saved["roulette"], saved["leads"], saved["acceptances"], saved["consents"]) == (1, 1, 1, 1)
    again = client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(a)).json()["saved"]
    assert (again["roulette"], again["leads"], again["acceptances"], again["consents"]) == (0, 0, 0, 0)
    db.expire_all()
    assert db.query(RouletteDraw).count() == 1 and db.query(EventExhibitor).one().name == "Stand Café" and db.query(ExhibitorLead).count() == 1
    assert db.query(WebAcceptance).one().verified_via == "staff"
    c = db.query(AuditConsentLog).one()
    assert c.reason == "consent" and len(c.cedula_hash) == 64


def test_full_backup_includes_every_event_table_and_is_sent_only_when_it_changes(db, factory, monkeypatch):
    import gzip
    from app import local_backup
    from app.models import RouletteDraw
    monkeypatch.setenv("LOCAL_SERVER", "1")
    ev = factory.event("en_proceso", cloud_event_id=77)
    factory.person(ev, "1001")
    db.add(RouletteDraw(event_id=ev.id, mode="attendees", winners_json="[]", created_at=utcnow()))
    db.commit()
    dump = local_backup.dump_event(db, ev)
    names = {t.name for t in local_backup.event_tables()}
    assert {"access_logs", "event_attendees", "roulette_draws", "queue_turns", "exhibitor_leads", "audit_consent_logs", "area_movements"} <= names
    assert dump["tables"]["roulette_draws"] and dump["tables"]["users"][0]["id"] == "1001" and "face_encoding" not in dump["tables"]["users"][0]
    sent = []
    monkeypatch.setattr(node_sync, "_call_bytes", lambda path, data, ctype: sent.append((path, data)) or {"ok": True})
    assert node_sync.push_backup(db, ev)["copy"] is True
    assert sent[0][0] == "/api/node/events/77/backup" and gzip.decompress(sent[0][1])
    assert node_sync.push_backup(db, ev)["copy"] is False          # nada cambió: no se repite
    db.add(RouletteDraw(event_id=ev.id, mode="attendees", winners_json="[1]", created_at=utcnow()))
    db.commit()
    assert node_sync.push_backup(db, ev)["copy"] is True


def test_cloud_stores_the_full_backup_and_only_super_admin_downloads_it(client, factory, db, monkeypatch, tmp_path):
    import gzip
    from app import storage as storage_mod
    monkeypatch.setattr(storage_mod, "get_storage", lambda: storage_mod.LocalStorage(str(tmp_path)))
    (a,) = _nodes(db, factory, "Puerta A")
    ev = factory.event("en_proceso")
    ev.local_node_name = "Puerta A"
    db.commit()
    blob = gzip.compress(b'{"format": "golden-local-backup"}')
    hdr = {**_hdr(a), "Content-Type": "application/gzip"}
    assert client.post(f"/api/node/events/{ev.id}/backup", content=b"no-gzip", headers=hdr).status_code == 400
    assert client.post(f"/api/node/events/{ev.id}/backup", content=blob, headers=hdr).json()["ok"]
    assert client.post(f"/api/node/events/{ev.id}/backup-file", params={"key": "acme/docs/a.pdf"}, content=b"%PDF", headers=hdr).json()["ok"]
    factory.staff("admin", "adm_bk")
    login(client, "adm_bk")
    assert client.get(f"/api/events/{ev.id}/local-backups").status_code == 403
    client.get("/logout")
    factory.staff("super_admin", "sa_bk")
    login(client, "sa_bk")
    rows = client.get(f"/api/events/{ev.id}/local-backups").json()["backups"]
    assert len(rows) == 1 and rows[0]["node"] == "Puerta_A"
    r = client.get(f"/api/events/{ev.id}/local-backups/download", params={"key": rows[0]["key"]})
    assert r.status_code == 200 and gzip.decompress(r.content).startswith(b'{"format"')
    assert client.get(f"/api/events/{ev.id}/local-backups/download", params={"key": "otra/empresa/x.json.gz"}).status_code == 404
