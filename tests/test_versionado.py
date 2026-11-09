"""Fase 6 · versión del servidor y comparación con producción (app/versioning.py): los servidores locales avisan si no están al día."""
from pathlib import Path

from app import versioning as v
from tests.conftest import login

SRC = Path(__file__).resolve().parent.parent


def test_schema_head_is_the_newest_migration_of_the_chain():
    head = v.schema_head()
    names = {p.stem for p in (SRC / "alembic" / "versions").glob("*.py")}
    assert head in names and v._order(head) >= 110          # 0110_notifications o más nueva
    assert v.schema_head(SRC / "no_existe") == "desconocida"


def test_schema_head_picks_the_revision_nobody_points_to(tmp_path):
    (tmp_path / "0001_a.py").write_text('revision = "0001_a"\ndown_revision = None\n', encoding="utf-8")
    (tmp_path / "0002_b.py").write_text('revision = "0002_b"\ndown_revision = "0001_a"\n', encoding="utf-8")
    assert v.schema_head(tmp_path) == "0002_b"


def test_compare_statuses():
    me = {"commit": "aaa", "date": "x", "schema": "0110_notifications"}
    assert v.compare(me, {"commit": "aaa", "schema": "0110_notifications"})["status"] == "igual"
    assert v.compare(me, {"commit": "bbb", "schema": "0110_notifications"})["status"] == "distinta_version"
    old = v.compare({**me, "schema": "0108_event_change_log"}, {"commit": "bbb", "schema": "0110_notifications"})
    assert old["status"] == "desactualizada" and "actualizar" in old["message"]
    assert v.compare(me, {"commit": "bbb", "schema": "0108_event_change_log"})["status"] == "adelantada"
    assert v.compare(me, None)["status"] == "desconocida" and v.compare(me, {"commit": "b"})["status"] == "desconocida"
    assert v.compare({**me, "commit": "desconocida"}, {"commit": "bbb", "schema": "0110_notifications"})["status"] == "igual"


def test_fetch_production_only_accepts_https_or_localhost():
    assert v.fetch_production("http://produccion.example.com") is None and v.fetch_production("ftp://x") is None


def test_version_endpoint_is_public_and_light(client):
    d = client.get("/api/ops/version").json()
    assert set(d) == {"commit", "date", "schema"} and d["schema"] == v.schema_head()


def test_version_check_needs_a_session_and_is_off_in_the_cloud(client, factory, monkeypatch):
    monkeypatch.delenv("PRODUCTION_URL", raising=False)
    assert client.get("/api/ops/version-check").status_code == 401
    factory.staff("coordinador", "co")
    login(client, "co")
    assert client.get("/api/ops/version-check").json() == {"configured": False}


def test_version_check_on_a_local_server_compares_with_production(client, factory, monkeypatch):
    monkeypatch.setenv("PRODUCTION_URL", "https://app.example.com")
    monkeypatch.setattr(v, "fetch_production", lambda url, timeout=4.0: {"commit": "zzz", "date": "d", "schema": "0999_futura"})
    v._remote_cache.update(at=0.0, value=None)
    factory.staff("coordinador", "co")
    login(client, "co")
    d = client.get("/api/ops/version-check?force=true").json()
    assert d["configured"] and d["status"] == "desactualizada" and d["production"]["schema"] == "0999_futura" and d["local"]["schema"] == v.schema_head()
    v._remote_cache.update(at=0.0, value=None)
