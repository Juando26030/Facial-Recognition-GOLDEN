"""Fase 10 (E): tarjeta «Servidor local» de Configuración (app/local_installer.py, app/routers/local_installer.py). Permisos (todos menos digitador y cliente), estado «aún no disponible»,
elección de la versión más nueva, descarga por app/storage.py y auditoría."""
import pytest

from app import local_installer as li
from app.models import AuditAction
from app.storage import get_storage, key_of
from tests.conftest import login


def _put(name, data=b"MZ-instalador"):
    get_storage().put(key_of("system", "local-installer", name), data)


def test_roles_allowed_rule():
    assert not li.roles_allowed({"digitador"}) and not li.roles_allowed({"cliente"}) and not li.roles_allowed({"digitador", "cliente"})
    for r in ("coordinador", "comercial", "admin", "super_admin", "almacen", "contabilidad"):
        assert li.roles_allowed({r})
    assert li.roles_allowed({"coordinador", "digitador"})


def test_not_available_until_a_file_exists(client, factory, monkeypatch):
    monkeypatch.delenv("LOCAL_INSTALLER_URL", raising=False)
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/local-installer").json()["available"] is False
    r = client.get("/api/local-installer/download")
    assert r.status_code == 404 and "aún no está disponible" in r.json()["detail"]


def test_latest_version_is_offered_and_downloaded_and_audited(client, factory, db):
    _put("GoldenLocal-Setup-2026.11.9.exe", b"viejo")
    _put("GoldenLocal-Setup-2026.11.10.exe", b"nuevo")
    _put("otra-cosa.txt", b"x")
    factory.staff("admin", "adm")
    login(client, "adm")
    st = client.get("/api/local-installer").json()
    assert st["available"] and st["version"] == "2026.11.10" and st["filename"] == "GoldenLocal-Setup-2026.11.10.exe"
    r = client.get("/api/local-installer/download")
    assert r.status_code == 200 and r.content == b"nuevo" and "GoldenLocal-Setup-2026.11.10.exe" in r.headers["content-disposition"]
    row = db.query(AuditAction).filter_by(entity="local_installer").one()
    assert row.action == "download" and row.entity_id == "2026.11.10"


@pytest.mark.parametrize("role", ["digitador", "cliente"])
def test_digitador_and_cliente_are_denied(client, factory, role):
    _put("GoldenLocal-Setup-1.0.exe")
    factory.staff(role, "x")
    login(client, "x")
    assert client.get("/api/local-installer").status_code == 403
    assert client.get("/api/local-installer/download").status_code == 403


def test_anonymous_is_denied(client):
    assert client.get("/api/local-installer").status_code in (401, 403)


def test_external_url_is_used_only_when_https(client, factory, monkeypatch):
    factory.staff("comercial", "com")
    login(client, "com")
    monkeypatch.setenv("LOCAL_INSTALLER_URL", "http://inseguro.example.com/a.exe")
    assert client.get("/api/local-installer").json()["available"] is False
    monkeypatch.setenv("LOCAL_INSTALLER_URL", "https://descargas.example.com/GoldenLocal-Setup-1.2.exe")
    assert client.get("/api/local-installer").json()["available"] is True
    r = client.get("/api/local-installer/download", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://descargas.example.com/")


def test_config_page_shows_card_only_to_allowed_roles(client, factory):
    factory.staff("coordinador", "coord")
    factory.staff("digitador", "dig")
    login(client, "coord")
    assert 'id="tab_servidor"' in client.get("/configuracion").text
    client.post("/logout")
    login(client, "dig")
    assert 'id="tab_servidor"' not in client.get("/configuracion").text


def test_publish_tutorial_visible_only_to_admins(client, factory):
    factory.staff("coordinador", "coord")
    factory.staff("admin", "adm")
    login(client, "coord")
    assert "localInstallerPublish" not in client.get("/configuracion").text
    client.post("/logout")
    login(client, "adm")
    assert "localInstallerPublish" in client.get("/configuracion").text
