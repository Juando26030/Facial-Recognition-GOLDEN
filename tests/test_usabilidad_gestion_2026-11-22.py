"""Correcciones de usabilidad de GESTIÓN (docs/revision_2026-11-22/13_usabilidad_gestion_correcciones.md). Pruebas de texto, sin base de datos:
python3 -m pytest --noconftest -q tests/test_usabilidad_gestion_2026-11-22.py · La lógica pura está en tests/js/gw_confirm_typed_check.js."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def read(*parts):
    return Path(*parts).read_text(encoding="utf-8")


CONFIRM = read("static", "js", "gw-confirm-typed.js")
PARAMS = read("templates", "kiosk_parametros.html")
USERS = read("templates", "kiosk_usuarios.html")
USERS_JS = read("static", "js", "usuarios.js")
EDITOR = read("templates", "kiosk_formulario_editor.html")
EVENTS = read("templates", "eventos.html")
NEW_JS = read("static", "js", "nuevo-evento.js")
STAFF = read("templates", "staff.html")
MODAL = read("templates", "_event_edit_modal.html")
CONFIG = read("templates", "configuracion.html")
TAG = "js/gw-confirm-typed.js"


def test_strong_confirmations_never_use_native_dialogs():
    for src in (CONFIRM, read("static", "js", "gw-summary-help.js")):
        assert not re.search(r"\b(alert|confirm|prompt)\(", src.replace("showConfirm(", "").replace("showPrompt(", ""))
    assert "root.showPrompt(" in CONFIRM and "root.showConfirm(" in CONFIRM


def test_node_check_of_typed_confirmation():
    if not shutil.which("node"):
        pytest.skip("sin node")
    out = subprocess.run(["node", "tests/js/gw_confirm_typed_check.js"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_privacy_suppress_and_revoke_ask_to_type_a_word():
    assert TAG in PARAMS
    assert "purgeData('all', GWConfirm.TEXT.suppressAll, 'SUPRIMIR'" in PARAMS and "purgeData('biometric', GWConfirm.TEXT.revoke, 'REVOCAR'" in PARAMS
    assert "GWConfirm.typed(GWConfirm.fill(text, { id }), word" in PARAMS
    assert "escribe la palabra <b>SUPRIMIR</b>" in CONFIRM and "escribe la palabra <b>REVOCAR</b>" in CONFIRM and "dígito por dígito" in CONFIRM
    assert "¿Suprimir TODOS los datos de la persona con cédula {id}?" not in PARAMS          # el Sí/No de antes ya no está
    assert "purge-data?event_id=${window.EVENT_ID}&scope=${scope}&confirm=true" in PARAMS          # el mismo endpoint de siempre


def test_purge_temporary_users_is_away_from_approve_all_and_asks_to_type():
    head = USERS[USERS.index('class="gw-usr__listhead"'):USERS.index('id="tempUsersStatus"')]
    assert "approveAllBtn" in head and "purgeTempBtn" not in head          # ya no es vecino de «Autorizar a todos»
    zone = USERS[USERS.index('id="purgeTempZone"'):]
    assert USERS.index('id="tempUsersPager"') < USERS.index('id="purgeTempZone"')
    assert 'class="gw-btn gw-btn--danger-outline gw-btn--sm" id="purgeTempBtn"' in zone and 'class="gw-btn gw-btn--danger" id="purgeTempBtn"' not in USERS
    assert TAG in USERS and USERS.index(TAG) < USERS.index("path='js/usuarios.js'")
    assert "GWConfirm.typed(GWConfirm.fill(GWConfirm.TEXT.purgeTemp, { n }), 'ELIMINAR'" in USERS_JS and "purgeZone.hidden = !on" in USERS_JS
    assert "/staff-users/purge-temporary" in USERS_JS


def test_wompi_refund_asks_to_type_and_shows_amount_and_reference():
    assert TAG in EDITOR
    assert "GWConfirm.fill(GWConfirm.TEXT.refund, { amount: cop($('rfAmount').value), reference: refunding.reference }), 'REEMBOLSAR'" in EDITOR
    assert "devolver {amount}" in CONFIRM and "{reference}" in CONFIRM and "REEMBOLSAR" in CONFIRM
    assert "¿Confirmas que ya se devolvió ese dinero?" in EDITOR          # el reembolso manual (solo registro) conserva su confirmación


def test_reopening_a_finished_event_has_its_own_text():
    assert TAG in EVENTS
    assert 'const reopening = previousStatus === "finalizado" && newStatus === "en_proceso";' in EVENTS
    assert "reopening ? await GWConfirm.reopenEvent(STATUS_LABELS[newStatus]) : await confirmStatusChange(newStatus, STATUS_LABELS[newStatus])" in EVENTS
    text = CONFIRM[CONFIRM.index("reopen:"):CONFIRM.index("activatePaid:")]
    for piece in ("Finalizado", "registrar, imprimir y entrar con el rostro", "usuarios temporales", "plazo de 7 días", "empieza de cero", "ya se borraron no vuelven", "REABRIR"):
        assert piece in text, piece


def test_activating_a_paid_form_confirms_real_money_and_account():
    i = EDITOR.index("async function saveAll()")
    body = EDITOR[i:EDITOR.index("$('saveBtn').addEventListener", i)]
    assert "$('cfgStatus').value === 'activo'" in body and "x.type === 'payment'" in body and "GWConfirm.activatePaidForm({ account: GWConfirm.accountName(form.payments, payAccounts) })" in body
    assert body.index("GWConfirm.activatePaidForm") < body.index("saveDesign()")          # se pregunta ANTES de guardar nada
    assert "cobra dinero real" in CONFIRM and "<b>Cobra con:</b> {account}" in CONFIRM
    assert 'id="payAccountLine"' in EDITOR and "GWConfirm.accountLine(form.payments" in EDITOR
    assert "(sin asignar) → asignar en " in CONFIRM and 'href="/cuentas-de-cobro"' in CONFIRM
    assert "payment_account_id" not in EDITOR          # solo lectura: la asignación sigue en Cuentas de cobro


def test_new_event_shows_what_is_next_without_changing_the_save():
    assert "fetch('/api/events', { method: 'POST'" in NEW_JS and "showNextSteps(created);" in NEW_JS
    assert "Evento creado. ¿Qué sigue?" in NEW_JS
    for path, title in (("roster", "Cargar la base"), ("escarapela", "Diseñar la escarapela"), ("usuarios", "Dar acceso a los digitadores")):
        assert f"path: '{path}', title: '{title}'" in NEW_JS
    assert "/kiosk/${encodeURIComponent(created.id)}/${s.path}" in NEW_JS and "window.location.href = AFTER_URL" in NEW_JS


def test_role_helps_in_staff_and_event_users():
    for key in ("coordinador", "dir_coordinadores", "comercial", "almacen", "contabilidad"):
        assert f"call ayuda('ay_rol_{key}'" in STAFF, key
        assert f'<option value="{key}">' in STAFF
    for key in ("digitador", "cliente", "coordinador_temp"):
        assert f"call ayuda('ay_rol_{key}'" in USERS, key
    assert STAFF.count("Puede: ") == 5 and STAFF.count("No puede: ") == 5 and USERS.count("No puede: ") == 3


def test_edit_event_has_one_help_per_section():
    sections = re.findall(r'<summary class="gw-form-group__summary">([^<{]+)', MODAL)
    helps = re.findall(r"call ee_ayuda\('(ee_ay_\d+)'", MODAL)
    assert len(sections) == 13 and len(helps) == 13 and len(set(helps)) == 13
    assert "js/gw-summary-help.js" in MODAL and "data-gw-help-btn" in MODAL
    for word in ("jornada", "superevento", "Facturado", "sin internet"):
        assert word in MODAL, word


def test_configuration_hides_commands_and_variables_under_advanced():
    visible = re.sub(r"<details.*?</details>", "", CONFIG, flags=re.S)
    visible = re.sub(r"<script.*?</script>|\{#.*?#\}|<!--.*?-->", "", visible, flags=re.S)
    for jargon in ("gcloud", "gsutil", "gh workflow", "git checkout", "SESSION_IDLE_MINUTES", "SINGLE_SESSION", "OFFSITE_FOLDER_URL"):
        assert jargon not in visible, jargon
        assert jargon in CONFIG, jargon          # el texto exacto se conserva dentro de «Avanzado»
    assert CONFIG.count("Avanzado") >= 4 and "(solo técnicos)" in CONFIG
    assert "Este valor lo fija la configuración del servidor (SESSION_IDLE_MINUTES) y manda sobre lo que se elija aquí." in CONFIG
    assert "Está forzado por la variable de entorno SINGLE_SESSION: este interruptor no cambia nada mientras exista." in CONFIG
    assert 'id="sessionMinEnvNote" hidden' in CONFIG and 'id="singleSessionNote"' in CONFIG


def test_headers_show_a_readable_role_name():
    macro = read("templates", "_gw_role_name.html")
    assert '"super_admin": "Administrador general"' in macro and '"admin": "Administrador"' in macro
    for name in ("kiosk_parametros", "kiosk_usuarios", "staff", "configuracion", "kiosk_formulario_editor", "nuevo_evento", "eventos", "cuentas_cobro"):
        html = read("templates", name + ".html")
        assert '{% from "_gw_role_name.html" import role_name %}' in html and "({{ role_name(staff_role) }})</span>" in html, name
        assert "({{ staff_role }})" not in html, name


def test_ql800_values_are_folded_without_touching_any_control():
    i = PARAMS.index('<details class="gw-advanced" id="psAdvanced">')
    block = PARAMS[i:PARAMS.index("</details>", i)]
    assert "no cambiar salvo indicación de soporte" in block and "<details open" not in block
    for ident in ("ps_tapeWidth", "ps_tapeType", "ps_lengthMm", "ps_rotation", "ps_crop", "ps_cropMarginMm", "ps_feedMm", "ps_cut", "ps_mirror", "ps_invert", "psSave", "psReset"):
        assert PARAMS.count(f'id="{ident}"') == 1 and f'id="{ident}"' in block, ident
    assert '<div id="psForm" data-psave="ps" class="gw-form-grid">' in block
    assert '<input class="gw-input" type="number" id="ps_feedMm" min="0" max="10" step="0.5">' in block          # mismos límites de siempre
    assert '<option value="auto">Automático (el lado largo a lo largo de la cinta)</option><option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option>' in block


def test_new_css_uses_only_tokens():
    css = read("static", "css", "design-system.css")
    tail = css[css.index("Revisión 22-nov-2026 (docs/revision_2026-11-22/13)"):]
    tail = tail[tail.index("*/"):]
    assert ".gw-advanced" in tail and ".gw-rolehelp" in tail
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|\d+px|rgba?\(", re.sub(r"[12]px solid", "", tail))          # bordes de 1 y 2 px: los mismos del resto del sistema
