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
    body = SRC[SRC.index("def previous_by_cedula"):SRC.index("def prefill_for")]
    assert 'StaffUser.username == cedula, StaffUser.role == "digitador"' in body and "tenant_id" not in body.split('"""')[2]
    assert "signed_at.desc()" in body          # el dato más reciente
    assert "logger" not in body and "log." not in body          # sin datos personales en logs
    assert 'staff.role != "digitador"' in SRC[SRC.index("def previous_answers"):SRC.index("def prefill_for")]          # la sesión: solo digitadores


def test_public_link_prefill_is_complete_and_editable():
    """27-nov-2026 (Juan David): al escribir la cédula se precargan nombre, celular y familiar COMPLETOS y editables (sin asteriscos); solo falta responder las preguntas."""
    pub = ROUTER[ROUTER.index("def pledge_prefill"):ROUTER.index("def check_registered")]
    assert "mask_prefill_value" not in pub and "_restore_pledge_values" not in ROUTER and '"pp"' not in ROUTER          # nada enmascarado ni restaurado en el servidor
    assert '_limit(db, request, "form_lookup", form, 60)' in pub and "formsvc.PLEDGE_KIND" in pub and "logger" not in pub
    page = (Path(__file__).resolve().parent.parent / "templates" / "form_public.html").read_text(encoding="utf-8")
    hook = page[page.index("if (st.pledge_prefill)"):]
    assert "/pledge-prefill" in hook and "dataset.prefilled" in hook and "dataset.masked" not in page
    assert "readOnly" not in hook and "readonly" not in hook                    # editable
    assert "pledge_prefill" in ROUTER and '"*" in str(clean[fid])' not in SRC


def test_only_the_cedula_is_locked_and_prefill_comes_from_the_session():
    assert "prefill = pledge.prefill_for(db, form, who)" in ROUTER and "[pledge.FID_ID] + ([pledge.FID_NAME] if prefill.get(pledge.FID_NAME) else [])" in ROUTER          # 25-nov-2026: cédula y nombre fijos
