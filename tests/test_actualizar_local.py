"""Fase 6: «Actualizar ahora» en un servidor local (app/local_update.py): reglas, petición para el servicio de actualización y estado."""
import json

import pytest

from app import local_update as lu
from app import versioning
from tests.conftest import login

GOOD = {"available": True, "commit": "bbb", "schema": "0111_event_lease", "package_url": "https://example.com/p.zip", "sha256": "a" * 64}
OLD = {"configured": True, "status": "desactualizada", "message": "x", "local": {"commit": "aaa", "schema": "0110_notifications"}, "production": {}}


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("LOCAL_UPDATE_DIR", str(tmp_path))
    monkeypatch.setattr(versioning, "check", lambda force=False: OLD)
    monkeypatch.setattr(lu, "fetch_manifest", lambda timeout=4.0: dict(GOOD))
    return tmp_path


def test_published_manifest_needs_https_and_a_valid_hash(monkeypatch):
    monkeypatch.delenv("UPDATE_PACKAGE_URL", raising=False)
    assert lu.published_manifest()["available"] is False
    monkeypatch.setenv("UPDATE_PACKAGE_URL", "http://inseguro/p.zip")
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "a" * 64)
    assert lu.published_manifest()["available"] is False and lu.published_manifest()["package_url"] is None
    monkeypatch.setenv("UPDATE_PACKAGE_URL", "https://ok/p.zip")
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "xyz")
    assert lu.published_manifest()["available"] is False
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "A" * 64)
    m = lu.published_manifest()
    assert m["available"] is True and m["sha256"] == "a" * 64 and m["package_url"] == "https://ok/p.zip"


def test_validate_manifest():
    assert lu.validate_manifest(dict(GOOD)) is None
    assert lu.validate_manifest(None) and lu.validate_manifest({"available": False})
    assert lu.validate_manifest({**GOOD, "package_url": "http://x/p.zip"})
    assert lu.validate_manifest({**GOOD, "sha256": "12"})
    assert lu.validate_manifest({**GOOD, "schema": "desconocida"})


def test_shift_rule():
    assert lu.shift_in_progress(1, 5) is True
    assert lu.shift_in_progress(1, 0) is False and lu.shift_in_progress(0, 9) is False


def test_request_writes_the_file_and_pending_status(local):
    assert lu.request_update(staff_id=3, events_in_progress=0, recent_checkins=0) == {"state": "pending"}
    req = json.loads((local / lu.REQUEST_FILE).read_text(encoding="utf-8"))
    assert req["package_url"] == GOOD["package_url"] and req["sha256"] == "a" * 64 and req["by_staff_id"] == 3 and req["from_schema"] == "0110_notifications"
    assert lu.read_status()["state"] == "pending" and lu.is_busy()
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=3, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "busy"


def test_refuses_in_the_cloud_when_up_to_date_or_without_a_package(local, monkeypatch):
    monkeypatch.setattr(versioning, "check", lambda force=False: {**OLD, "status": "igual"})
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "up_to_date"
    monkeypatch.setattr(versioning, "check", lambda force=False: OLD)
    monkeypatch.setattr(lu, "fetch_manifest", lambda timeout=4.0: {"available": False})
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "bad_manifest"
    monkeypatch.delenv("LOCAL_SERVER")
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "not_local"


def test_a_shift_in_progress_needs_explicit_confirmation(local):
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=1, recent_checkins=4)
    assert e.value.code == "shift_active" and not (local / lu.REQUEST_FILE).exists()           # sin confirmar no se deja nada
    assert lu.request_update(staff_id=1, events_in_progress=1, recent_checkins=4, confirm_shift=True)["state"] == "pending"
    assert json.loads((local / lu.REQUEST_FILE).read_text(encoding="utf-8"))["confirmed_during_shift"] is True


def test_read_status_ignores_garbage(tmp_path):
    (tmp_path / lu.STATUS_FILE).write_text("{no json", encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "idle"
    (tmp_path / lu.STATUS_FILE).write_text(json.dumps({"state": "inventado"}), encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "idle"
    (tmp_path / lu.STATUS_FILE).write_text(json.dumps({"state": "migrate", "message": "m"}), encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "migrate"


def test_endpoints(client, factory, db, local):
    factory.staff("coordinador", "coord")
    factory.staff("digitador", "dig")
    assert client.get("/api/ops/update-manifest").status_code == 200
    login(client, "dig")
    assert client.post("/api/ops/update", json={}).status_code == 403
    client.get("/logout")
    login(client, "coord")
    assert client.get("/api/ops/update-status").json()["enabled"] is True
    r = client.post("/api/ops/update", json={})
    assert r.status_code == 200 and r.json()["state"] == "pending", r.text
    assert client.post("/api/ops/update", json={}).status_code == 409


def test_status_endpoint_is_disabled_in_the_cloud(client, factory, db, monkeypatch):
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/ops/update-status").json() == {"enabled": False}


def test_auto_update_respects_flag_and_shift(local, monkeypatch):
    class Q:
        def __init__(self, n): self.n = n
        def filter(self, *a): return self
        def count(self): return self.n
    class DB:
        def __init__(self, ev, rc): self.ev, self.rc = ev, rc
        def query(self, m): return Q(self.ev if m.__name__ == "Event" else self.rc)
    monkeypatch.setenv("AUTO_UPDATE", "0")
    assert lu.auto_update(DB(0, 0)) == "disabled"
    monkeypatch.setenv("AUTO_UPDATE", "1")
    assert lu.auto_update(DB(1, 5)) == "shift_active"
    assert lu.auto_update(DB(0, 0)) == "pending"


def test_catalog_write_blocked_only_in_local():
    from app import localmode as lm
    assert lm.is_catalog_write("POST", "/api/inventory/products")
    assert lm.is_catalog_write("PATCH", "/api/inventory/products/3/manage")
    assert not lm.is_catalog_write("GET", "/api/inventory/products")
    assert not lm.is_catalog_write("POST", "/api/events/1/inventory-deliver")
