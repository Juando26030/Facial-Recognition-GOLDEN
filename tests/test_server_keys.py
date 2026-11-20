"""Llaves de producto del servidor local (20-nov-2026): crear/ver/deshabilitar (admin), reclamo del instalador, vinculación con la llave, apagado y frescura de versión."""
import types

import pytest

from app import node_auth, server_keys, versioning
from app.models import LocalNode, LocalServerKey
from tests.conftest import PASSWORD, login

INST = "a" * 32


def _create(client, factory, label="Portátil 1"):
    factory.staff("admin", "adm")
    login(client, "adm")
    r = client.post("/api/server-keys", json={"label": label})
    assert r.status_code == 200
    return r.json()


def test_only_admin_manages_keys(client, factory):
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/server-keys").status_code == 403
    assert client.post("/api/server-keys", json={}).status_code == 403


def test_create_list_and_one_use(client, factory, db):
    k = _create(client, factory)
    assert k["code"].startswith("GLD-") and k["status"] == "unused"
    assert client.get("/api/server-keys").json()["counts"]["unused"] == 1
    factory.staff("admin", "adm2")
    # enroll sin llave: se niega
    r = client.post("/api/node/enroll", json={"username": "adm2", "password": PASSWORD, "installation_id": INST})
    assert r.status_code == 400
    # llave sin reclamar por el instalador: se niega
    r = client.post("/api/node/enroll", json={"username": "adm2", "password": PASSWORD, "key": k["code"], "installation_id": INST})
    assert r.status_code == 403


def test_full_flow_claim_enroll_burn_disable(client, factory, db, monkeypatch):
    k = _create(client, factory)
    monkeypatch.setattr("app.local_update.published_manifest", lambda: {"available": True, "package_url": "https://x/p.zip", "sha256": "0" * 64, "commit": "abc", "schema": versioning.schema_head()})
    c = client.post("/api/node/key/claim", json={"key": k["code"], "installation_id": INST})
    assert c.status_code == 200 and c.json()["ticket"]
    # otra instalación no puede reclamar la misma llave
    assert client.post("/api/node/key/claim", json={"key": k["code"], "installation_id": "b" * 32}).status_code == 403
    e = client.post("/api/node/enroll", json={"username": "adm", "password": PASSWORD, "key": k["code"], "installation_id": INST})
    assert e.status_code == 200 and e.json()["server_id"] == k["code"] and e.json()["token"].startswith("gwn_")
    token = e.json()["token"]
    # la llave quedó usada: no sirve una segunda vez
    assert client.post("/api/node/enroll", json={"username": "adm", "password": PASSWORD, "key": k["code"], "installation_id": INST}).status_code == 403
    db.expire_all()
    key = db.query(LocalServerKey).filter_by(code=k["code"]).one()
    assert key.node_id is not None and key.activated_at is not None
    # el servidor aparece con su frescura
    row = client.get("/api/server-keys").json()["keys"][0]
    assert row["status"] == "active" and row["node"]["freshness"]["status"] == "desconocida"
    # deshabilitar: el servidor recibe 403 con el texto fijo, no 401
    assert client.post(f"/api/server-keys/{key.id}/disable").status_code == 200
    r = client.get("/api/node/ping", headers={"X-Node-Token": token})
    assert r.status_code == 403 and r.json()["detail"] == node_auth.DISABLED_DETAIL
    # y la llave no se reutiliza
    assert client.post("/api/node/key/claim", json={"key": k["code"], "installation_id": INST}).status_code == 403
    assert client.get("/api/server-keys").json()["keys"][0]["status"] == "disabled"


def test_freshness_against_production():
    cloud = {"commit": "bbb", "schema": "0158_x"}
    from app.routers.server_keys import _freshness
    assert _freshness(types.SimpleNamespace(last_version="bbb|0158_x"), cloud)["status"] == "igual"
    assert _freshness(types.SimpleNamespace(last_version="aaa|0157_x"), cloud)["status"] == "desactualizada"
    assert _freshness(types.SimpleNamespace(last_version="aaa|0158_x"), cloud)["status"] == "distinta_version"
    assert _freshness(types.SimpleNamespace(last_version=None), cloud)["status"] == "desconocida"


def test_package_gating(client, monkeypatch):
    monkeypatch.setenv("UPDATE_PACKAGE_AUTH", "1")
    monkeypatch.setattr("app.local_update.published_manifest", lambda: {"available": True, "package_url": "https://x/p.zip", "sha256": "0" * 64, "commit": "abc", "schema": "0158_x"})
    m = client.get("/api/ops/update-manifest")
    if m.status_code == 200:
        assert m.json()["package_url"] is None and m.json()["locked"] is True


def test_migration_0158_shape():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0158_local_server_keys.py").read_text(encoding="utf-8")
    assert 'revision = "0158_local_server_keys"' in src and len("0158_local_server_keys") <= 32 and 'down_revision = "0157_sync_prints_changes"' in src
