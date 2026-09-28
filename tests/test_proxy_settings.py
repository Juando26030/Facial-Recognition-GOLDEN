"""Detrás de Firebase Hosting: IP real configurable (no confiar en CF-Connecting-IP inventada) y la cookie de sesión puede llamarse «__session»."""
from types import SimpleNamespace

from app import security


def _req(headers):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="10.0.0.1"))


def test_vm_behaviour_is_unchanged():
    assert security.client_ip(_req({"cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2"})) == "1.1.1.1"
    assert security.client_ip(_req({"x-forwarded-for": "2.2.2.2, 3.3.3.3"})) == "2.2.2.2"
    assert security.client_ip(_req({})) == "10.0.0.1"


def test_cloud_run_ignores_forged_cloudflare_header_and_picks_the_trusted_hop(monkeypatch):
    monkeypatch.setenv("TRUST_CF_CONNECTING_IP", "0")
    monkeypatch.setenv("XFF_CLIENT_INDEX", "-2")
    forged = {"cf-connecting-ip": "6.6.6.6", "x-forwarded-for": "6.6.6.6, 190.1.2.3, 35.0.0.1"}
    assert security.client_ip(_req(forged)) == "190.1.2.3"


def test_session_cookie_name_comes_from_the_environment():
    from app.main import app
    mw = next(m for m in app.user_middleware if m.cls.__name__ == "SessionMiddleware")
    assert mw.kwargs["session_cookie"] == "session"                  # por defecto, como en la VM
