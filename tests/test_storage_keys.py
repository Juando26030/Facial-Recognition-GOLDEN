"""Fotos biométricas bajo un prefijo común en la nube (regla de ciclo de vida de 1 día para sus versiones viejas) y la migración las deja ahí."""
from app.storage import photo_key
from scripts.migrate_files_to_gcs import target_key


def test_photo_key_uses_the_biometric_prefix_only_when_configured(monkeypatch):
    monkeypatch.delenv("BIOMETRIC_KEY_PREFIX", raising=False)
    assert photo_key("acme", "1001") == "acme/known_people/1001.jpg"                    # VM: como siempre
    monkeypatch.setenv("BIOMETRIC_KEY_PREFIX", "biometric")
    assert photo_key("acme", "1001") == "biometric/acme/known_people/1001.jpg"


def test_migration_moves_only_biometric_photos_to_the_same_place_the_app_looks(monkeypatch):
    monkeypatch.setenv("BIOMETRIC_KEY_PREFIX", "biometric")
    assert target_key("acme/known_people/1001.jpg", "biometric") == photo_key("acme", "1001")
    assert target_key("acme/signatures/1_2.png", "biometric") == "acme/signatures/1_2.png"
    assert target_key("acme/badge_assets/known_people.png", "biometric") == "acme/badge_assets/known_people.png"
    assert target_key("acme/known_people/1001.jpg") == "acme/known_people/1001.jpg"      # sin la opción, igual que antes
