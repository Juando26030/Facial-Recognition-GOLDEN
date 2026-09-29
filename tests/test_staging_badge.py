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
