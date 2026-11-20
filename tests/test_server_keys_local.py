"""Llaves de producto, lado servidor local e instalador (20-nov-2026). Sin base: bloqueo por archivo, y forma de los scripts del instalador."""
import pathlib

from app import local_env, server_keys, server_lock

SRC = pathlib.Path(__file__).resolve().parent.parent
WIN = SRC / "deploy" / "windows"


def test_lock_flag_in_env_file(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    f.write_text("NODE_TOKEN=gwn_x\nSERVER_KEY=GLD-AAAA-BBBB-CCCC\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    monkeypatch.delenv("SERVER_DISABLED", raising=False)
    server_lock._cache.update(at=0.0, locked=False)
    assert server_lock.is_locked() is False
    server_lock.note_cloud_error(401, "otra cosa")                      # solo el 403 con el texto fijo bloquea
    server_lock.note_cloud_error(403, "Acceso denegado")
    server_lock._cache.update(at=0.0, locked=False)
    assert server_lock.is_locked() is False
    server_lock.note_cloud_error(403, server_keys.DISABLED_DETAIL)
    assert server_lock.is_locked() is True
    assert "SERVER_DISABLED=1" in f.read_text(encoding="utf-8")
    monkeypatch.delenv("SERVER_DISABLED", raising=False)                # otro proceso: se entera por el archivo
    server_lock._cache.update(at=0.0, locked=False)
    assert server_lock.is_locked() is True


def test_env_keys_and_texts():
    assert "SERVER_KEY" in local_env.KEYS and "INSTALLATION_ID" in local_env.KEYS
    assert server_keys.DISABLED_DETAIL.startswith("Servidor deshabilitado")
    assert "llave" in server_lock.LOCKED_MSG.lower()


def test_installer_is_light_and_asks_for_key():
    iss = (WIN / "GoldenLocal.iss").read_text(encoding="utf-8-sig")
    assert "payload\\app\\*" not in iss                                    # el .exe NO lleva el código de la app
    assert "CreateInputQueryPage" in iss and "install-request.json" in iss and "GLD-" in iss
    inst = (WIN / "install.ps1").read_text(encoding="utf-8-sig")
    assert "download-app.ps1" in inst and "SERVER_KEY" in inst and "INSTALLATION_ID" in inst and "SERVER_DISABLED" in inst
    dl = (WIN / "download-app.ps1").read_text(encoding="utf-8-sig")
    for needle in ("/api/node/key/claim", "X-Install-Ticket", "X-Install-Id", "Get-FileHash", "-MaximumRedirection 0"):
        assert needle in dl
    assert "$pkgUrl.StartsWith($prod + '/')" in dl                          # el permiso solo viaja a producción


def test_local_side_wiring():
    link = (SRC / "app" / "local_link.py").read_text(encoding="utf-8")
    assert "SERVER_KEY" in link and "installation_id" in link and "server_id" in link
    main = (SRC / "app" / "main.py").read_text(encoding="utf-8")
    assert "server_lock.is_locked()" in main
    sync = (SRC / "app" / "node_sync.py").read_text(encoding="utf-8")
    assert "note_cloud_error" in sync and "cloud_ping()" in sync
    upd = (SRC / "app" / "local_update.py").read_text(encoding="utf-8")
    assert '"X-Node-Token"' in upd
    js = (SRC / "static" / "js" / "version-banner.js").read_text(encoding="utf-8")
    assert "/api/ops/server-id" in js and "gw-versionbar--id" in js
    css = (SRC / "static" / "css" / "gw-notifications.css").read_text(encoding="utf-8")
    assert "gw-versionbar--id" in css
