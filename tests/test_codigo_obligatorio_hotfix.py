"""Hotfix 25-nov-2026: con «Código de la persona» obligatorio, Editar/Registrar rechazaba guardar aunque el código estuviera puesto
(el código vive en EventAttendee y `final_values` no lo llevaba a `_missing_required_fields`)."""
from pathlib import Path

API = (Path(__file__).resolve().parent.parent / "app" / "routers" / "api.py").read_text(encoding="utf-8")


def test_edit_person_passes_code_to_required_check():
    assert 'final_values["code"] = (clean_code if (code_raw is not None and event.code_enabled)' in API


def test_manual_register_passes_code_to_required_check():
    assert '"digital_contact": contact_clean or "", "code": code_clean or "", **extras}' in API


def test_outbox_edit_counts_stored_code_and_create_only_warns():
    assert 'final["code"] = (attendee.code if attendee else "") or ""' in API
    assert "Falta el código de la persona (QR): complétalo en Editar" in API
