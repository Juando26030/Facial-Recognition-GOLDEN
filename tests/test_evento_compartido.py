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
    assert peer_changes.clean_cursor('{"l": "5", "a": -3, "p": "x"}') == {"l": 5, "a": 0, "p": 0, "c": 0}
    assert peer_changes.clean_cursor(None) == {"l": 0, "a": 0, "p": 0, "c": 0}
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
