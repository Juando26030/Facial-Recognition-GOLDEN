"""Servidor local: /certificado entrega la autoridad para quitar el aviso «No seguro» en los equipos que se conectan (20-nov-2026). Solo con LOCAL_SERVER=1; sin sesión."""
import base64
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _gen_cert():
    spec = importlib.util.spec_from_file_location("gen_cert_lc", ROOT / "deploy" / "windows" / "gen_cert.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["gen_cert_lc"] = m
    spec.loader.exec_module(m)
    return m


def test_windows_script_recreates_the_exact_certificate(tmp_path):
    from app.routers import local_cert
    _gen_cert().make(tmp_path, "SERVIDOR", ["192.168.1.149"])
    der = (tmp_path / "GoldenLocal-CA.cer").read_bytes()
    cmd = local_cert.windows_cmd(der)
    assert "\r\n" in cmd and "certutil -user -addstore Root" in cmd
    body = cmd.split("echo -----BEGIN CERTIFICATE-----\r\n", 1)[1].split("\r\necho -----END CERTIFICATE-----", 1)[0]
    b64 = "".join(ln[len("echo "):] for ln in body.split("\r\n"))
    assert base64.b64decode(b64) == der
    assert ")" not in b64          # dentro del bloque ( … ) de cmd un paréntesis rompería el script
    fp = local_cert.fingerprint(der)
    assert len(fp) == 95 and fp.count(":") == 31


def test_only_on_local_server_and_without_session(client, monkeypatch, tmp_path):
    _gen_cert().make(tmp_path, "SERVIDOR", ["192.168.1.149"])
    monkeypatch.setenv("LOCAL_CERT_DIR", str(tmp_path))
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    assert client.get("/certificado").status_code == 404
    assert client.get("/certificado/golden-local-ca.cer").status_code == 404
    monkeypatch.setenv("LOCAL_SERVER", "1")
    r = client.get("/certificado")
    assert r.status_code == 200 and "No seguro" in r.text and "instalar-windows.cmd" in r.text
    c = client.get("/certificado/golden-local-ca.cer")
    assert c.status_code == 200 and c.content == (tmp_path / "GoldenLocal-CA.cer").read_bytes()
    w = client.get("/certificado/instalar-windows.cmd")
    assert w.status_code == 200 and b"certutil -user -addstore Root" in w.content
    assert "ca.key" not in r.text and b"PRIVATE KEY" not in c.content + w.content


def test_missing_certificate_is_explained(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("LOCAL_CERT_DIR", str(tmp_path / "no_existe"))
    assert "todavía no tiene certificado" in client.get("/certificado").text
    assert client.get("/certificado/golden-local-ca.cer").status_code == 404


def test_wiring():
    assert "/certificado" in (ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    assert "'/certificado'" in (ROOT / "static" / "js" / "version-banner.js").read_text(encoding="utf-8")
    assert "LOCAL_CERT_DIR" in (ROOT / "deploy" / "windows" / "install.ps1").read_text(encoding="utf-8-sig")
    from app import idle
    assert "/certificado" in idle.EXEMPT_PREFIXES
