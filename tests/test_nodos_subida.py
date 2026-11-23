"""Fase 6 (B): tokens de servidores locales, lo que la nube recibe de un nodo, y la subida del servidor local (marcas de agua, reintentos, «pasar a internet»)."""
import pathlib

import pytest

from app import event_lease, node_auth, node_sync, versioning
from app.models import AccessLog, Event, EventAttendee, LocalNode, PrintLog, User
from datetime import timedelta

from app.timeutil import utcnow
from tests.conftest import login

SRC = pathlib.Path(__file__).resolve().parent.parent
HEAD = versioning.schema_head()


def _hdr(token, schema=None):
    return {"X-Node-Token": token, "X-Node-Schema": schema or HEAD, "X-Node-Version": f"abc|{schema or HEAD}"}


# ------------------------------------------------------------------ puro
def test_token_shape_hash_and_compatibility():
    token, digest = node_auth.generate_token()
    assert token.startswith("gwn_") and len(token) > 40 and digest == node_auth.hash_token(token) and token not in digest
    assert node_auth.generate_token()[0] != token
    assert node_auth.schema_compatible(HEAD)[0] is True
    assert node_auth.schema_compatible("0001_old")[0] is False and node_auth.schema_compatible(None)[0] is False


def test_migration_0112():
    src = (SRC / "alembic" / "versions" / "0112_local_nodes.py").read_text(encoding="utf-8")
    assert 'revision = "0112_local_nodes"' in src and len("0112_local_nodes") <= 32 and 'down_revision = "0111_event_lease"' in src
    for col in ("token_hash", "cloud_event_id", "sync_log_id", "sync_persons_at", "sync_error"):
        assert col in src


# ------------------------------------------------------------------ nube: administrar nodos
def test_only_admin_creates_a_node_and_the_token_is_shown_once(client, factory, db):
    factory.staff("coordinador", "coord")
    factory.staff("admin", "adm")
    login(client, "coord")
    assert client.post("/api/nodes", json={"name": "Portátil 1"}).status_code == 403
    client.get("/logout")
    login(client, "adm")
    r = client.post("/api/nodes", json={"name": "Portátil 1"})
    assert r.status_code == 200 and r.json()["token"].startswith("gwn_")
    token, node_id = r.json()["token"], r.json()["id"]
    assert client.post("/api/nodes", json={"name": "Portátil 1"}).status_code == 409
    assert "token" not in client.get("/api/nodes").json()["nodes"][0]
    db.expire_all()
    stored = db.get(LocalNode, node_id)
    assert stored.token_hash == node_auth.hash_token(token) and token not in (stored.token_hash or "")
    assert client.post(f"/api/nodes/{node_id}/revoke").json()["revoked"] is True
    client.get("/logout")
    assert client.get("/api/node/ping", headers=_hdr(token)).status_code == 401           # revocado


def _node(db, factory, name="Portátil 1"):
    admin = factory.staff("admin", "adm_n")
    token, digest = node_auth.generate_token()
    db.add(LocalNode(name=name, token_hash=digest, created_by_id=admin.id))
    db.commit()
    return token


def test_ping_needs_a_valid_token_and_reports_compatibility(client, factory, db):
    token = _node(db, factory)
    assert client.get("/api/node/ping").status_code == 401
    assert client.get("/api/node/ping", headers={"X-Node-Token": "gwn_mala"}).status_code == 401
    ok = client.get("/api/node/ping", headers=_hdr(token)).json()
    assert ok["ok"] and ok["compatible"] is True and ok["node"] == "Portátil 1"
    old = client.get("/api/node/ping", headers=_hdr(token, "0001_old")).json()
    assert old["compatible"] is False and old["message"]


def test_node_writes_only_to_events_leased_to_it_and_release_needs_zero_pending(client, factory, db):
    token = _node(db, factory)
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    ev_id = ev.id
    body = {"records": [{"client_id": "n1-l1", "cedula": "1001", "method": "cedula"}]}
    assert client.post(f"/api/node/events/{ev_id}/access-logs", json=body, headers=_hdr(token)).status_code == 409       # no está arrendado a este nodo
    ev.local_node_name = "Portátil 1"
    db.commit()
    r = client.post(f"/api/node/events/{ev_id}/access-logs", json=body, headers=_hdr(token))
    assert r.status_code == 200 and r.json()["results"][0]["result"] == "created", r.text
    assert client.post(f"/api/node/events/{ev_id}/access-logs", json=body, headers=_hdr(token)).json()["results"][0]["result"] == "replayed"
    assert client.post(f"/api/node/events/{ev_id}/access-logs", json=body, headers=_hdr(token, "0001_old")).status_code == 409       # versión incompatible
    assert client.post(f"/api/node/events/{ev_id}/uploaded", headers=_hdr(token)).json()["last_upload_at"]
    assert client.post(f"/api/node/events/{ev_id}/release", json={"pending": 3}, headers=_hdr(token)).status_code == 409
    assert client.post(f"/api/node/events/{ev_id}/release", json={"pending": 0}, headers=_hdr(token)).json()["leased"] is False
    db.expire_all()
    assert not event_lease.is_leased(db.get(Event, ev_id))


# ------------------------------------------------------------------ servidor local: subida
@pytest.fixture()
def local_env(monkeypatch):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("PRODUCTION_URL", "https://nube.example")
    monkeypatch.setenv("NODE_TOKEN", "gwn_test")
    calls = []

    def fake(method, path, body=None):
        calls.append((method, path, body))
        if path.endswith("/ping"):
            return {"ok": True, "compatible": True}
        if path.endswith("/outbox"):
            return {"results": [{"op_id": o["op_id"], "result": "ok"} for o in body["ops"]]}
        if path.endswith("/access-logs"):
            return {"results": [{"client_id": r["client_id"], "result": "created"} for r in body["records"]]}
        if path.endswith("/records"):
            return {"ok": True}
        return {}
    monkeypatch.setattr(node_sync, "_call", fake)
    monkeypatch.setattr(node_sync, "push_backup", lambda db, ev: {"copy": False, "files": 0})          # la copia completa (0160) se prueba en test_evento_compartido.py
    return calls


def _local_event(db, factory):
    ev = factory.event("en_proceso", cloud_event_id=77)
    factory.person(ev, "1001")                                                       # de la base: no se sube como alta
    u = factory.person(ev, "2002", "Nueva", "Persona")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2002").update({"origin": "manual"})
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id, client_id="c-1", timestamp=utcnow()))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id=u.id, record_type="Nuevo", event_id=ev.id, timestamp=utcnow()))
    db.commit()
    return ev


def test_upload_sends_new_people_and_existing_checkins_then_marks_watermarks(db, factory, local_env):
    ev = _local_event(db, factory)
    assert node_sync.pending_counts(db, ev) == {"persons": 1, "logs": 1, "prints": 0, "changes": 0, "extra": 0, "total": 2}
    out = node_sync.upload_event(db, ev, force=True)
    assert out == {"ok": True, "pending": 0, "error": None}
    paths = [c[1] for c in local_env]
    assert paths == ["/api/node/ping", "/api/node/events/77/outbox", "/api/node/events/77/access-logs", "/api/node/events/77/uploaded"]
    ops = [c[2] for c in local_env if c[1].endswith("/outbox")][0]["ops"]
    assert ops[0]["type"] == "create_person" and ops[0]["fields"]["id"] == "2002" and ops[0]["op_id"].startswith(f"n{ev.id}-p")
    recs = [c[2] for c in local_env if c[1].endswith("/access-logs")][0]["records"]
    assert [r["cedula"] for r in recs] == ["1001"] and recs[0]["client_id"] == "c-1"
    db.expire_all()
    ev = db.get(Event, ev.id)
    assert ev.sync_log_id and ev.sync_persons_at and ev.sync_error is None and ev.local_last_upload_at
    local_env.clear()
    assert node_sync.upload_event(db, ev, force=True)["pending"] == 0
    assert not [c for c in local_env if c[1].endswith(("/outbox", "/access-logs"))]           # nada nuevo: nada que enviar


def test_failed_upload_keeps_watermarks_and_records_a_short_error(db, factory, monkeypatch, local_env):
    ev = _local_event(db, factory)
    ev_id = ev.id

    def down(method, path, body=None):
        if path.endswith("/ping"):
            return {"ok": True, "compatible": True}
        raise node_sync.SyncError("Sin conexión con la nube")
    monkeypatch.setattr(node_sync, "_call", down)
    out = node_sync.upload_event(db, ev, force=True)
    assert out["ok"] is False and out["pending"] == 2
    db.expire_all()
    ev = db.get(Event, ev_id)
    assert ev.sync_error == "Sin conexión con la nube" and ev.sync_log_id is None and ev.sync_persons_at is None


def test_release_only_when_everything_is_uploaded(db, factory, monkeypatch, local_env):
    ev = _local_event(db, factory)
    ev_id = ev.id
    out = node_sync.release_event(db, ev)
    assert out["ok"] is True and ("POST", "/api/node/events/77/release", {"pending": 0}) in local_env
    db.expire_all()
    assert db.get(Event, ev_id).cloud_event_id is None
    ev2 = _local_event(db, factory)
    ev2_id = ev2.id
    monkeypatch.setattr(node_sync, "_call", lambda *a, **k: (_ for _ in ()).throw(node_sync.SyncError("Sin conexión con la nube")))
    assert node_sync.release_event(db, ev2)["ok"] is False
    db.expire_all()
    assert db.get(Event, ev2_id).cloud_event_id == 77            # no se soltó


def test_release_is_blocked_while_local_only_work_exists(db, factory, monkeypatch, local_env):
    """Revisión 9-nov: lo hecho en el local que la subida NO lleva bloquea «Pasar a internet». Las impresiones ya suben (19-nov), así que aquí se simula con la lista fija."""
    monkeypatch.setattr(node_sync, "LOCAL_ONLY", node_sync.LOCAL_ONLY + (("print_logs", "printed_at", "impresiones"),))
    ev = _local_event(db, factory)
    ev.sync_package_at = utcnow() - timedelta(hours=1)
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_at=utcnow()))
    db.commit()
    assert node_sync.local_only_changes(db, ev) == {"impresiones": 1}
    out = node_sync.release_event(db, ev)
    assert out["ok"] is False and "impresiones" in out["error"] and out["local_only"] == {"impresiones": 1}
    assert not [c for c in local_env if c[1].endswith("/release")]
    db.expire_all()
    assert db.get(Event, ev.id).cloud_event_id == 77
    monkeypatch.setenv("NODE_RELEASE_ALLOW_LOCAL_ONLY", "1")                              # válvula de emergencia
    assert node_sync.release_event(db, db.get(Event, ev.id))["ok"] is True


def test_work_from_before_the_download_does_not_block(db, factory, monkeypatch, local_env):
    monkeypatch.setattr(node_sync, "LOCAL_ONLY", node_sync.LOCAL_ONLY + (("print_logs", "printed_at", "impresiones"),))
    ev = _local_event(db, factory)
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_at=utcnow() - timedelta(days=1)))
    ev.sync_package_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert node_sync.local_only_changes(db, ev) == {}


def test_nothing_runs_in_the_cloud(db, factory, monkeypatch):
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    assert node_sync.configured() is False and node_sync.start() is False and node_sync.upload_all(db) == {"configured": False, "events": 0}


def test_prints_and_person_changes_are_uploaded_and_advance_watermarks(db, factory, local_env):
    from app.models import PersonChange
    ev = _local_event(db, factory)
    ev.sync_package_at = utcnow() - timedelta(hours=1)
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_at=utcnow()))
    db.add(PersonChange(tenant_id=ev.tenant_id, event_id=ev.id, user_id="1001", kind="registration_status", old_value="Registrado", new_value="No registrado"))
    db.commit()
    assert node_sync.pending_counts(db, ev)["prints"] == 1 and node_sync.pending_counts(db, ev)["changes"] == 1
    assert node_sync.local_only_changes(db, ev) == {}
    out = node_sync.upload_event(db, ev, force=True)
    assert out["ok"] is True and out["pending"] == 0
    rec = [c for c in local_env if c[1].endswith("/records")][0][2]
    assert len(rec["print_logs"]) == 1 and rec["person_changes"][0]["kind"] == "registration_status"
