"""Plan 6: «Parámetros del evento» agrupado en bloques desplegables y con UN solo «Guardar» global (static/js/params-save.js).
Los endpoints no cambian: aquí se verifica la estructura de la pantalla, que cada guardado existente siga registrado en el guardado global, que las acciones destructivas
sigan inmediatas y que los ids que leen otras pruebas sigan en la página."""
import pathlib
import re

import pytest

from tests.conftest import login

TEMPLATE = pathlib.Path("templates/kiosk_parametros.html").read_text(encoding="utf-8")
SAVE_JS = pathlib.Path("static/js/params-save.js").read_text(encoding="utf-8")

GROUPS = ["registro", "facial", "impresion", "correo", "areas", "campos", "marca"]
# clave del guardado global -> (id del botón por bloque que sigue en el DOM, oculto, o None si el bloque no tenía botón propio)
BLOCKS = {"page": None, "idle": "idleMinutesSave", "cc": "ccSave", "bbp": None, "pc": "pcSave", "cert": None, "digital": None, "sharedprint": None, "ps": "psSave",
          "mail": "mailSave", "mod_areas": None, "mod_inventory": None, "logo": None, "categories": "saveCategoriesBtn", "fields": "saveParamsBtn", "stations": None}


@pytest.fixture(autouse=True)
def company_env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "golden-eventos.com"}.items():
        monkeypatch.setenv(k, v)


def test_the_template_has_seven_collapsible_groups_and_the_first_is_the_only_default_open_one():
    found = re.findall(r'<details class="gw-group" data-group="(\w+)" id="grp_\w+">', TEMPLATE)
    assert found == GROUPS
    assert all("open" not in t for t in re.findall(r'<details class="gw-group"[^>]*>', TEMPLATE)), "el abierto/cerrado lo decide params-save.js (primero abierto, o lo recordado)"
    assert TEMPLATE.count('class="gw-group__sum"') == 7 and TEMPLATE.count("data-group-pending") == 7
    assert "background: white; padding: 1.4rem 2rem" not in TEMPLATE, "las tarjetas viejas con colores sueltos ya no están"


def test_every_block_registers_its_save_in_the_global_save_with_the_existing_endpoints():
    for key in BLOCKS:
        assert f"key: '{key}'" in TEMPLATE or (key.startswith("mod_") and "key: 'mod_' + mod" in TEMPLATE), key
    # mismas rutas de siempre (sin API nueva)
    for route in ("directory-page-size", "idle-minutes", "biometric-setup", "badge-bio-photo", "precalculo-autorizado", "certificates-enabled", "digital-badge-enabled",
                  "/categories", "/modules", "/logo", "field-configs/", "digital-email", "shared-print", "print-settings", "print-stations/"):
        assert route in TEMPLATE, route
    order = [int(n) for n in re.findall(r"key: '[\w]+', label: '[^']+', order: (\d+)", TEMPLATE)]
    assert 5 in order and 100 in order


def test_the_buttons_of_each_block_stay_in_the_dom_hidden_and_call_the_same_save():
    for key, btn in BLOCKS.items():
        if not btn:
            continue
        tag = re.search(rf'<button[^>]*id="{btn}"[^>]*>', TEMPLATE)
        assert tag, btn
        hidden_parent = re.search(rf'<div hidden[^>]*>\s*<button[^>]*id="{btn}"', TEMPLATE)
        assert "hidden" in tag.group(0) or hidden_parent, f"{btn} debe seguir en el DOM pero oculto"
        assert f"GWParams.saveKey('{key}')" in TEMPLATE, key
    assert re.search(r'<button type="button" class="gw-btn gw-btn--primary" id="paramsSaveBtn"', TEMPLATE) and 'id="paramsSaveBar"' in TEMPLATE and 'id="paramsSaveFail"' in TEMPLATE
    assert TEMPLATE.count('id="paramsSaveBtn"') == 1, "UN solo botón Guardar visible"


def test_destructive_and_immediate_actions_keep_their_confirmation():
    assert "🗑️ Borrar campo" in TEMPLATE and "/usage" in TEMPLATE and "Escribe <b>" in TEMPLATE
    assert "showConfirm('¿Eliminar esta zona" in TEMPLATE and "showConfirm('¿Eliminar este ítem" in TEMPLATE and "purgeEventBiometrics" in TEMPLATE
    assert "¿Quitar la configuración de este puesto?" in TEMPLATE and "¿Liberar esta cuenta?" in TEMPLATE and "¿Volver al texto por defecto?" in TEMPLATE
    assert not re.search(r"\b(alert|confirm|prompt)\(", TEMPLATE.replace("showConfirm(", "").replace("showPrompt(", "")), "nada de alert/confirm/prompt del navegador"


def test_toggles_no_longer_save_on_change_or_reload_the_page_by_themselves():
    for el in ("digitalEnabled", "certificatesEnabled", "badgeBioPhoto", "directoryPageSize"):
        assert not re.search(rf"getElementById\('{el}'\)\.addEventListener\('change', async", TEMPLATE), el
    assert "location.reload()" in TEMPLATE
    # el único recargar «solo» que queda es el de subir una imagen sin otros cambios pendientes
    assert len(re.findall(r"location\.reload\(\)", TEMPLATE)) == 1 and "if (!GWParams.hasDirty())" in TEMPLATE


def test_printing_parameters_are_untouched_by_the_regrouping():
    """INAMOVIBLE (docs/IMPRESION_PARAMETROS_INAMOVIBLES.md): solo cambió QUIÉN dispara el guardado; el cuerpo enviado y las rutas son los de siempre."""
    for needle in ("const FIELDS = ['cut', 'feedMm', 'lengthMm', 'mirror', 'invert', 'tapeWidth', 'tapeType', 'rotation', 'crop', 'cropMarginMm'];",
                   "body: JSON.stringify({ settings: read() })", "body: JSON.stringify({ settings: {} })", "continua de 62 mm (DK-22205)", 'id="ps_tapeWidth"', 'id="psReset"'):
        assert needle in TEMPLATE, needle
    assert "--kiosk-printing" not in TEMPLATE


def test_the_global_save_script_is_safe_without_storage_and_warns_only_when_there_are_changes():
    assert re.search(r"try \{ saved = JSON\.parse\(win\.localStorage\.getItem", SAVE_JS) and "catch (e)" in SAVE_JS
    assert "beforeunload" in SAVE_JS and "if (!ctl.hasDirty()) return undefined;" in SAVE_JS
    assert "[data-pnodirty]" in SAVE_JS or "data-pnodirty" in SAVE_JS
    assert not re.search(r"\b(alert|confirm|prompt)\(", SAVE_JS) and not re.search(r"https?://", SAVE_JS)
    page = pathlib.Path("templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert "url_for('static', path='js/params-save.js')" in page


def test_the_page_renders_with_groups_the_global_bar_and_every_old_id(client, factory):
    factory.staff("super_admin", "root")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "root")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert page.count('<details class="gw-group"') == 7 and 'id="paramsRoot"' in page and 'id="paramsSaveBar"' in page and 'data-state="idle"' in page
    for ident in ("directoryPageSize", "idleMinutes", "idleMinutesSave", "ccMode", "ccSave", "pcSave", "badgeBioPhoto", "certificatesEnabled", "sharedPrintCard", "stationsCard",
                  "printSettingsCard", "psSave", "psReset", "digitalEnabled", "privacyCard", "prTabla", "areasEnabled", "inventoryEnabled", "logoFile", "categoriesBox",
                  "saveCategoriesBtn", "paramsTableBody", "saveParamsBtn", "addOptionalFieldBtn"):
        assert f'id="{ident}"' in page, ident
    assert "qr.addData(aceptarUrl + '?c=qr')" in page and "${window.PUBLIC_BASE || location.origin}/aceptar/" in page
    # no se perdió ningún grupo ni tarjeta para un coordinador (sin privacidad de admin ni súper)
    factory.staff("coordinador", "coord")
    login(client, "coord")
    coord = client.get(f"/kiosk/{ev.id}/parametros").text
    assert coord.count('<details class="gw-group"') == 7 and 'id="prTabla"' not in coord and 'id="pcSave"' not in coord and 'id="saveParamsBtn"' in coord


def test_the_person_form_card_lives_in_the_campos_group_and_registers_in_the_global_save():
    """Unión Plan 4 + Plan 6: «Formulario de persona» es un .gw-group__item del grupo «Categorías y campos», se guarda con el Guardar global (clave `personform`)."""
    designer = pathlib.Path("static/js/person-form-designer.js").read_text(encoding="utf-8")
    campos = TEMPLATE[TEMPLATE.index('data-group="campos"'):TEMPLATE.index('data-group="marca"')]
    assert 'id="personFormCard"' in campos and 'id="personFormEditor"' in campos and 'data-psave="personform"' in campos
    assert "register({ key: 'personform'" in designer and "markDirty('personform')" in designer and "id: 'pfSave'" in designer
