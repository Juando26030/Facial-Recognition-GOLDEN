"""Prellenado del compromiso del digitador que ya firmó antes (misma cédula, cualquier cliente o evento). Pruebas de texto: corren sin base."""
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "app" / "pledge.py").read_text(encoding="utf-8")
ROUTER = (Path(__file__).resolve().parent.parent / "app" / "routers" / "forms_public.py").read_text(encoding="utf-8")


def test_only_contact_fields_are_prefilled_never_the_checkboxes():
    line = [ln for ln in SRC.splitlines() if ln.startswith("PREFILL_FROM_BEFORE")][0]
    for fid in ("FID_NAME", "FID_PHONE", "FID_EM_NAME", "FID_EM_PHONE"):
        assert fid in line
    for fid in ("FID_MED", "FID_DRUG", "FID_SUPPORT", "FID_CONTRACT", "FID_ATTEND", "FID_DECL", "FID_AUTH", "FID_SIG"):
        assert fid not in line


def test_match_is_by_cedula_across_clients_and_only_for_digitadores():
    body = SRC[SRC.index("def previous_answers"):SRC.index("def prefill_for")]
    assert 'staff.role != "digitador"' in body and "StaffUser.username == staff.username" in body and "tenant_id" not in body.split('"""')[2]
    assert "signed_at.desc()" in body          # el dato más reciente
    assert "logger" not in body and "log." not in body          # sin datos personales en logs


def test_only_the_cedula_is_locked_and_prefill_comes_from_the_session():
    assert "pledge.prefill_for(db, form, who), [pledge.FID_ID]" in ROUTER
