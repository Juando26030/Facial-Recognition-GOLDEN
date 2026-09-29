"""Staging nunca se presenta como producción: distintivo en pantallas y prefijo en correos."""
from app import mailer


def test_login_shows_staging_badge_only_in_staging(client, monkeypatch):
    monkeypatch.delenv("DEPLOY_ENV", raising=False)
    assert "golden-env-badge" not in client.get("/login").text.replace(".golden-env-badge", "")
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    assert "STAGING" in client.get("/login").text


def test_staging_mail_subject_is_prefixed(monkeypatch):
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    for k in ("AZURE_TENANT_ID", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    seen = []
    monkeypatch.setattr(mailer, "_outbox_fallback", lambda msg, to, reason: seen.append(msg["Subject"]) or {"sent": False, "detail": ""})
    mailer.send_mail("a@b.co", "Hola", "cuerpo")
    mailer.send_mail("a@b.co", "[STAGING] Ya", "cuerpo")
    assert seen == ["[STAGING] Hola", "[STAGING] Ya"]


# ------------------------------------------------------------------ D.2: diagnóstico de IP y simulacro de caída (solo staging)
def _ops_headers(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "token-de-prueba")
    return {"X-Ops-Token": "token-de-prueba"}


def test_client_ip_diagnostic_needs_ops_token_and_shows_the_chosen_hop(client, monkeypatch):
    monkeypatch.setenv("TRUST_CF_CONNECTING_IP", "0")
    monkeypatch.setenv("XFF_CLIENT_INDEX", "-2")
    assert client.get("/api/ops/client-ip").status_code in (401, 403)
    r = client.get("/api/ops/client-ip", headers={**_ops_headers(monkeypatch), "X-Forwarded-For": "6.6.6.6, 203.0.113.9, 142.250.0.1"}).json()
    assert r["x_forwarded_for"] == ["6.6.6.6", "203.0.113.9", "142.250.0.1"] and r["chosen_ip"] == "203.0.113.9" and r["xff_client_index"] == "-2"


def test_simulate_crash_is_404_outside_staging_with_chaos_and_kills_only_when_armed(client, monkeypatch):
    import app.routers.ops as ops_router
    calls = []
    monkeypatch.setattr(ops_router, "_die", lambda: calls.append("die"))
    headers = _ops_headers(monkeypatch)
    monkeypatch.delenv("DEPLOY_ENV", raising=False)
    monkeypatch.setenv("CHAOS_ENABLED", "1")
    assert client.post("/api/ops/simulate-crash", headers=headers).status_code == 404                     # sin DEPLOY_ENV=staging (producción)
    monkeypatch.setenv("DEPLOY_ENV", "production")
    assert client.post("/api/ops/simulate-crash", headers=headers).status_code == 404
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    monkeypatch.delenv("CHAOS_ENABLED")
    assert client.post("/api/ops/simulate-crash", headers=headers).status_code == 404                     # sin CHAOS_ENABLED
    monkeypatch.setenv("CHAOS_ENABLED", "1")
    assert client.post("/api/ops/simulate-crash").status_code in (401, 403)                               # sin credenciales
    assert not calls
    assert client.post("/api/ops/simulate-crash", headers=headers).json() == {"crashing": True} and calls == ["die"]
