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


def test_public_link_prefill_is_masked_and_restored_only_for_the_same_cedula():
    """27-nov-2026: al escribir la cédula en el enlace público se precargan nombre, celular y familiar, pero el navegador solo recibe versiones ocultas; el real se pone en el servidor."""
    pub = ROUTER[ROUTER.index("def pledge_prefill"):ROUTER.index("def check_registered")]
    assert "mask_prefill_value(fields[fid], val)" in pub and "_limit(db, request, \"form_lookup\", form, 60)" in pub and 'formsvc.PLEDGE_KIND' in pub
    assert '"pp": ced' in pub                                                  # el token queda atado a ESA cédula
    restore = pub[pub.index("def _restore_pledge_values"):]
    assert 'claims.get("pp")' in restore and "!= ced" in restore and "mask_prefill_value(f, val)" in restore      # solo si es la misma cédula y el valor sigue enmascarado
    assert "_restore_pledge_values(db, form, design, values, claims)" in ROUTER.split("def _submit", 1)[1] or "_restore_pledge_values(db, form, design, values, claims)" in ROUTER
    assert "logger" not in pub
    page = (Path(__file__).resolve().parent.parent / "templates" / "form_public.html").read_text(encoding="utf-8")
    assert "/pledge-prefill" in page and "st.pledge_prefill" in page and "dataset.masked" in page
    assert "pledge_prefill" in ROUTER and '"*" in str(clean[fid])' in SRC          # un valor enmascarado nunca se guarda


def test_only_the_cedula_is_locked_and_prefill_comes_from_the_session():
    assert "prefill = pledge.prefill_for(db, form, who)" in ROUTER and "[pledge.FID_ID] + ([pledge.FID_NAME] if prefill.get(pledge.FID_NAME) else [])" in ROUTER          # 25-nov-2026: cédula y nombre fijos
