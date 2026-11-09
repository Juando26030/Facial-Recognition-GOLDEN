"""Fase 6 (agente A): lista de eventos de la nube en el servidor local y «Descargar a local» en un paso; API de nodo en la nube."""
import io
import urllib.error

import pytest

from app import cloud_client, event_lease
from app.models import Event
from tests.conftest import login

TOKEN = "token-de-prueba"


# ---------------------------------------------------------------- cliente de la nube (sin red)
def test_cloud_client_config_and_https_only(monkeypatch):
    for k in ("CLOUD_BASE_URL", "NODE_TOKEN", "NODE_NAME"):
        monkeypatch.delenv(k, raising=False)
    assert not cloud_client.configured() and cloud_client.node_name() == "Servidor local"
    with pytest.raises(cloud_client.CloudError):
        cloud_client.list_events()
    monkeypatch.setenv("CLOUD_BASE_URL", "http://nube.example.com")
    monkeypatch.setenv("NODE_TOKEN", TOKEN)
    monkeypatch.setenv("NODE_NAME", "  Portátil   bodega 1 ")
    assert cloud_client.configured() and cloud_client.node_name() == "Portátil bodega 1"
    with pytest.raises(cloud_client.CloudError) as e:
        cloud_client.list_events()
    assert "HTTPS" in str(e.value)


def test_cloud_client_sends_token_and_maps_errors(monkeypatch):
    monkeypatch.setenv("CLOUD_BASE_URL", "https://nube.example.com/")
    monkeypatch.setenv("NODE_TOKEN", TOKEN)
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(req, timeout=None):
        seen["url"], seen["token"], seen["method"] = req.full_url, req.get_header("X-node-token"), req.get_method()
        return Resp(b'{"events": [{"id": 1}]}')

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", ok)
    assert cloud_client.list_events() == [{"id": 1}]
    assert seen == {"url": "https://nube.example.com/api/node/events", "token": TOKEN, "method": "GET"}

    def http_409(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 409, "x", {}, io.BytesIO('{"detail": "Ya está en otro servidor"}'.encode()))

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", http_409)
    with pytest.raises(cloud_client.CloudError) as e:
        cloud_client.take_lease(5)
    assert e.value.status == 409 and "otro servidor" in str(e.value)

    def down(req, timeout=None):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", down)
    with pytest.raises(cloud_client.CloudError) as e:
        cloud_client.list_events()
    assert e.value.status is None and "conexión" in str(e.value)


# ---------------------------------------------------------------- API de nodo (nube)
def _node(monkeypatch):
    monkeypatch.setenv("NODE_TOKEN_STUB", TOKEN)
    return {"X-Node-Token": TOKEN, "X-Node-Name": "Portátil 1"}


def test_node_api_needs_the_token(client, factory, db, monkeypatch):
    monkeypatch.setenv("NODE_TOKEN_STUB", TOKEN)
    ev = factory.event("en_proceso")
    assert client.get("/api/node/events").status_code == 401
    assert client.get("/api/node/events", headers={"X-Node-Token": "otro"}).status_code == 401
    assert client.post(f"/api/node/events/{ev.id}/lease").status_code == 401


def test_node_lists_metadata_leases_and_releases(client, factory, db, monkeypatch):
    h = _node(monkeypatch)
    ev = factory.event("en_proceso")
    ev_id = ev.id
    body = client.get("/api/node/events", headers=h).json()
    meta = [e for e in body["events"] if e["id"] == ev_id][0]
    assert meta["local"]["leased"] is False and "event_code" in meta and "first_name" not in meta
    r = client.post(f"/api/node/events/{ev_id}/lease", headers=h)
    assert r.status_code == 200 and r.json()["leased"] and r.json()["already_mine"] is False and r.json()["node_name"] == "Portátil 1"
    assert client.post(f"/api/node/events/{ev_id}/lease", headers=h).json()["already_mine"] is True
    other = {**h, "X-Node-Name": "Otro"}
    assert client.post(f"/api/node/events/{ev_id}/lease", headers=other).status_code == 409
    assert client.post(f"/api/node/events/{ev_id}/release", headers=other).status_code == 409
    assert client.post(f"/api/node/events/{ev_id}/release", headers=h).json()["leased"] is False


def test_node_package_is_a_zip(client, factory, db, monkeypatch):
    h = _node(monkeypatch)
    ev = factory.event("en_proceso")
    r = client.get(f"/api/node/events/{ev.id}/package", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and r.content[:2] == b"PK"


# ---------------------------------------------------------------- servidor local
def _local(monkeypatch, events=None):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("CLOUD_BASE_URL", "https://nube.example.com")
    monkeypatch.setenv("NODE_TOKEN", TOKEN)
    monkeypatch.setenv("NODE_NAME", "Portátil 1")
    monkeypatch.setattr(cloud_client, "list_events", lambda: events or [])


def test_local_routes_do_not_exist_in_the_cloud(client, factory, db, monkeypatch):
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/local/cloud-events").status_code == 404
    assert client.post("/api/local/cloud-events/1/download").status_code == 404
    assert client.get("/servidor-local", follow_redirects=False).status_code == 302


def test_local_list_marks_what_is_here_or_elsewhere(client, factory, db, monkeypatch):
    factory.staff("coordinador", "coord")
    here = factory.event("en_proceso")
    code = here.event_code
    _local(monkeypatch, [
        {"id": 1, "event_code": code, "name": "A", "tenant_name": "Acme", "local": {"leased": True, "node_name": "Portátil 1"}},
        {"id": 2, "event_code": "OTRO-2", "name": "B", "tenant_name": "Acme", "local": {"leased": True, "node_name": "Bodega"}},
        {"id": 3, "event_code": "LIBRE-3", "name": "C", "tenant_name": "Beta", "local": {"leased": False}},
    ])
    login(client, "coord")
    body = client.get("/api/local/cloud-events").json()
    by = {e["id"]: e for e in body["events"]}
    assert by[1]["downloaded"] and by[1]["leased_here"] and not by[1]["leased_elsewhere"]
    assert by[2]["leased_elsewhere"] and not by[2]["downloaded"]
    assert not by[3]["downloaded"] and not by[3]["leased_here"] and not by[3]["leased_elsewhere"]
    assert client.get("/servidor-local").status_code == 200


def test_local_list_offline_and_digitador_forbidden(client, factory, db, monkeypatch):
    factory.staff("coordinador", "coord")
    factory.staff("digitador", "dig")
    _local(monkeypatch)

    def boom():
        raise cloud_client.CloudError("No hay conexión con la nube.")

    monkeypatch.setattr(cloud_client, "list_events", boom)
    login(client, "coord")
    body = client.get("/api/local/cloud-events").json()
    assert body["offline"] is True and body["events"] == [] and "conexión" in body["error"]
    client.get("/logout")
    login(client, "dig")
    assert client.get("/api/local/cloud-events").status_code == 403


def test_download_one_step_imports_and_keeps_the_lease(client, factory, db, monkeypatch):
    """Origen y destino en la misma base de pruebas: el paquete se arma de un evento y se importa con otro código (lo que haría el local con una base vacía)."""
    from app import event_transfer
    factory.staff("coordinador", "coord")
    src = factory.event("en_proceso")
    data, _ = event_transfer.export_event(db, src, staff_username="t")
    db.query(Event).filter(Event.id == src.id).update({"event_code": src.event_code + "-ORIGEN", "name": src.name + " origen"})
    db.commit()
    _local(monkeypatch)
    calls = []
    monkeypatch.setattr(cloud_client, "take_lease", lambda i: calls.append(("lease", i)) or {"leased": True, "already_mine": False})
    monkeypatch.setattr(cloud_client, "download_event", lambda i: calls.append(("zip", i)) or data)
    monkeypatch.setattr(cloud_client, "release_lease", lambda i: calls.append(("release", i)) or {})
    login(client, "coord")
    r = client.post("/api/local/cloud-events/77/download")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["event_id"], r.text
    assert calls == [("lease", 77), ("zip", 77)]
    db.expire_all()
    new = db.get(Event, r.json()["event_id"])
    assert not event_lease.is_leased(new)          # la copia local no nace «en servidor local»


def test_download_failure_gives_the_event_back(client, factory, db, monkeypatch):
    factory.staff("coordinador", "coord")
    _local(monkeypatch)
    calls = []
    monkeypatch.setattr(cloud_client, "take_lease", lambda i: calls.append("lease") or {"leased": True, "already_mine": False})

    def fail(i):
        raise cloud_client.CloudError("No hay conexión con la nube.")

    monkeypatch.setattr(cloud_client, "download_event", fail)
    monkeypatch.setattr(cloud_client, "release_lease", lambda i: calls.append("release") or {})
    login(client, "coord")
    r = client.post("/api/local/cloud-events/5/download")
    assert r.status_code == 502 and calls == ["lease", "release"]


def test_download_refused_when_the_event_is_in_another_server(client, factory, db, monkeypatch):
    factory.staff("coordinador", "coord")
    _local(monkeypatch)

    def busy(i):
        raise cloud_client.CloudError("El evento ya está en el servidor local «Bodega».", 409)

    monkeypatch.setattr(cloud_client, "take_lease", busy)
    login(client, "coord")
    r = client.post("/api/local/cloud-events/5/download")
    assert r.status_code == 409 and "Bodega" in r.json()["detail"]
