"""23-nov-2026: (1) las confirmaciones de «escribe la palabra» NO se cierran en silencio si la palabra está mal: el aviso rojo sale en el mismo cuadro;
(2) el desplegable de coordinador del evento nuevo no ofrece coordinadores temporales (el servidor los rechaza). Pruebas de texto: no necesitan base de datos."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _t(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_showprompt_valida_y_no_cierra():
    s = _t("static/js/toast.js")
    assert "opts.validate" in s and 'id="toastPromptErr"' in s and "gw-alert--err" in s
    # con validate, el cuadro solo se cierra (done) si no hay problema
    assert "if (problem) { showErr(problem); input.focus(); input.select(); return; }" in s


def test_todas_las_confirmaciones_con_palabra_usan_validate():
    assert "validate: function (v) { return matches(v, word)" in _t("static/js/gw-confirm-typed.js")
    assert "validate:" in _t("static/js/dependents-upload.js")
    assert "validate:" in _t("templates/kiosk_roster.html")
    assert "validate:" in _t("templates/kiosk_parametros.html")
    assert "validate:" in _t("static/js/biometric-purge.js")
    assert _t("static/js/crm_importar.js").count("validate:") == 2


def test_coordinador_del_evento_nuevo_sin_temporales():
    s = _t("app/event_template_svc.py")
    assert "coordination.coordinator_candidates(db)" in s
    assert "StaffUser.event_only.is_(False)" in s


def test_recien_editado_si_sigue_no_registrada():
    s = _t("static/js/directory.js")
    assert "'Recién editado'" in s and "u.status === 'No registrado'" in s


def test_material_de_golden_no_es_del_digitador():
    """24-nov-2026 (Juan David): el material de Golden (computadores, equipos) no le sale al digitador: ni la tarjeta, ni la página, ni el API. «Control de inventario» (entregas a personas) sí sigue."""
    assert 'staff_role not in ("comercial", "digitador")' in _t("templates/kiosk_select.html")
    main = _t("app/main.py")
    assert 'kiosk_alistamiento.html", min_role="digitador", exclude_roles=["comercial", "digitador"]' in main
    inv = _t("app/routers/inventory.py")
    assert 'def get_checklist(' in inv and 'Depends(require_role("coordinador"))' in inv.split("def get_checklist(")[1].split("\n")[0]
    assert 'tile("/kiosk/%s/inventario" % event.id' in _t("templates/kiosk_select.html")
