"""Servidor local: primera vinculación con producción desde el login (app/local_link.py + /api/node/enroll). Sin base: usa simulaciones."""
import os

from app import local_link


def test_save_replaces_and_appends_without_gluing(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    f.write_text("LOCAL_SERVER=1\nNODE_NAME=viejo\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    local_link._save({"NODE_TOKEN": "gwn_x", "NODE_NAME": "nuevo"})
    lines = f.read_text(encoding="utf-8").splitlines()
    assert lines == ["LOCAL_SERVER=1", "NODE_NAME=nuevo", "NODE_TOKEN=gwn_x"]


def test_refresh_reads_token_from_file_for_the_other_worker(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    f.write_text("NODE_TOKEN=gwn_abc\nCLOUD_BASE_URL=https://x.example\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.delenv("NODE_TOKEN", raising=False)
    monkeypatch.delenv("CLOUD_BASE_URL", raising=False)
    assert local_link.linked() is True
    assert os.environ["CLOUD_BASE_URL"] == "https://x.example"
    monkeypatch.delenv("NODE_TOKEN", raising=False)
    monkeypatch.delenv("CLOUD_BASE_URL", raising=False)


def test_link_success_saves_syncs_and_starts(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    monkeypatch.setenv("PRODUCTION_URL", "https://prod.example")
    monkeypatch.setenv("SERVER_KEY", "GW-PRUEBA-LLAVE")          # 20-nov-2026: sin llave de producto no se vincula (la deja el instalador)
    monkeypatch.delenv("NODE_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(local_link, "_post", lambda url, body, timeout=20.0: (200, {"token": "gwn_t", "name": "Servidor local X"}))
    monkeypatch.setattr(local_link.account_sync, "run_once", lambda db: calls.append("sync") or {"ok": True})
    monkeypatch.setattr(local_link.node_sync, "start", lambda: calls.append("start") or True)
    res = local_link.link(None, "ana", "clave")
    assert res == {"ok": True} and calls == ["sync", "start"]
    assert "NODE_TOKEN=gwn_t" in f.read_text(encoding="utf-8")
    monkeypatch.delenv("NODE_TOKEN", raising=False)


def test_link_errors_are_plain(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_ENV_FILE", str(tmp_path / "local.env"))
    monkeypatch.setenv("PRODUCTION_URL", "https://prod.example")
    monkeypatch.delenv("SERVER_KEY", raising=False)
    res = local_link.link(None, "ana", "clave")
    assert res["ok"] is False and res["status"] == 403 and "llave de producto" in res["message"]          # sin llave: ni se intenta
    monkeypatch.setenv("SERVER_KEY", "GW-PRUEBA-LLAVE")
    for status, expected in ((0, 503), (429, 429), (401, 401)):
        monkeypatch.setattr(local_link, "_post", lambda url, body, timeout=20.0, s=status: (s, {}))
        res = local_link.link(None, "ana", "mala")
        assert res["ok"] is False and res["status"] == expected
    assert not (tmp_path / "local.env").exists()


def test_login_and_enroll_are_wired():
    src = open("app/routers/auth.py", encoding="utf-8").read()
    assert "maybe_link_on_login" in src
    nodes = open("app/routers/nodes.py", encoding="utf-8").read()
    assert '"/node/enroll"' in nodes and "login_minutes_locked" in nodes
    assert "LOCAL_ENV_FILE" in open("deploy/windows/run-app.ps1", encoding="utf-8-sig").read()


def test_every_process_reads_the_link_from_the_file_when_its_environment_lacks_it(tmp_path, monkeypatch):
    """El servidor corre con 2 procesos: el que NO vinculó debe ver el token (si no, la pantalla de eventos decía «no está conectado» a ratos)."""
    from app import cloud_client
    f = tmp_path / "local.env"
    f.write_text("NODE_TOKEN=gwn_z\nCLOUD_BASE_URL=https://prod.example\nNODE_NAME=Servidor X\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    monkeypatch.setenv("LOCAL_SERVER", "1")
    for k in ("NODE_TOKEN", "CLOUD_BASE_URL", "NODE_NAME"):
        monkeypatch.delenv(k, raising=False)
    assert cloud_client.configured() is True and cloud_client.node_name() == "Servidor X"
    for k in ("NODE_TOKEN", "CLOUD_BASE_URL", "NODE_NAME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    assert cloud_client.configured() is False          # en la nube no se lee ningún archivo
