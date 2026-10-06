"""La llave del rostro es obligatoria en producción: sin ella no arranca y no se guarda nada biométrico en claro (decisión 2026-10-06)."""
import pytest

from app import crypto


def test_production_without_the_key_fails_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(crypto.KeyMissing):
        crypto.assert_ready()
    with pytest.raises(crypto.KeyMissing):
        crypto.encrypt_text("[[0.1]]")
    with pytest.raises(crypto.KeyMissing):
        crypto.encrypt_bytes(b"foto")


def test_production_with_the_key_encrypts_and_development_still_works_without_it(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.assert_ready()
    assert crypto.encrypt_text("[[0.1]]").startswith("enc1:") and crypto.encrypt_bytes(b"x").startswith(b"GWENC1:")
    monkeypatch.delenv("FACE_ENCRYPTION_KEY")
    monkeypatch.setenv("ENVIRONMENT", "development")
    crypto.assert_ready()
    assert crypto.encrypt_text("[[0.1]]") == "[[0.1]]"                          # desarrollo y pruebas: sin llave se guarda en claro (como siempre)


def test_the_app_refuses_to_start_in_production_without_the_key(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(crypto.KeyMissing):
        with TestClient(app):
            pass
