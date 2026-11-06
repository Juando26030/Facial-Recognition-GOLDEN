"""Plan 8 (reingeniería visual de Registro): pruebas sobre archivos (como test_design_system.py). Fallan si la pantalla vuelve a tener emojis de ícono, estilos `style=` con color o
tamaño, hex sueltos, textos menores de 14 px, un segundo botón principal en la vista o si falta `gw-page`. No ejecutan la app."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
BUSC = (ROOT / "templates/_gw_buscador.html").read_text(encoding="utf-8")
REG_CSS = (ROOT / "static/css/registro.css").read_text(encoding="utf-8")
DIR_JS = (ROOT / "static/js/directory.js").read_text(encoding="utf-8")
OUT_JS = (ROOT / "static/js/outbox-ui.js").read_text(encoding="utf-8")
DS_CSS = (ROOT / "static/css/design-system.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs/ux/guia_visual.html").read_text(encoding="utf-8")
STANDARDS = (ROOT / "docs/ux/ESTANDARES_VISUALES.md").read_text(encoding="utf-8")

EMOJI = re.compile("[←-⇿⌀-⏿①-➿⤀-⧿⬀-⯿\U0001f000-\U0001ffff️]")


def _no_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _directory_view():
    a = TPL.index('id="directorio" class="section{% if not event.facial_enabled %} active{% endif %}"')
    return TPL[a:TPL.index("<!-- Modal flotante")]


def test_registro_uses_the_design_system_base():
    assert re.search(r'<body class="gw-page[ "]', TPL) and '{% include "_gw_head.html" %}' in TPL
    assert "url_for('static', path='css/registro.css')" in TPL and "gw-registro" in TPL


def test_no_emoji_icons_in_registro_files():
    for name, text in (("kiosk_registro.html", TPL), ("_gw_buscador.html", BUSC), ("directory.js", DIR_JS), ("outbox-ui.js", OUT_JS)):
        bad = sorted(set(EMOJI.findall(text)))
        assert not bad, f"{name} tiene emojis como íconos: {bad} (usar el sprite static/img/icons.svg)"


def test_no_inline_styles_hex_or_small_text_in_the_registro_template():
    assert not re.search(r"\sstyle\s*=", TPL), "nada de style= en kiosk_registro.html: clases .gw-*"
    assert not re.search(r"<style\b", TPL)
    code = re.sub(r"\{#.*?#\}|<!--.*?-->", "", TPL, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"href=\"#[\w-]+\"|href=\"[^\"]*#i-[\w-]+\"|#i-[\w-]+", "", code)), "nada de colores sueltos"
    assert not re.search(r"font-size\s*:\s*(?:[\d.]+px|0?\.\d+r?em)", code), "textos de al menos 14 px"
    assert not re.search(r"\son(click|change|input|submit)\s*=", TPL), "sin manejadores inline"
    assert not re.search(r"\b(alert|confirm|prompt)\(", re.sub(r"showConfirm|showPrompt", "", TPL))


def test_registro_css_and_outbox_use_only_tokens_and_14px_text():
    css = _no_comments(REG_CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "registro.css: solo tokens --gw-*"
    for m in re.finditer(r"font-size:\s*([\d.]+)(px|rem)", css):
        assert float(m.group(1)) * (16 if m.group(2) == "rem" else 1) >= 14, m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\bcssText\b", OUT_JS), "outbox-ui.js: clases, sin colores en el código"


def test_directory_view_has_one_primary_button_and_the_fixed_search_bar():
    view = _directory_view()
    assert len(re.findall(r"gw-btn--primary", view)) == 1 and 'id="openRegisterModalBtn" class="gw-btn gw-btn--primary gw-btn--xl"' in view
    assert "gw-btn--primary" not in BUSC, "el buscador (con su ayuda) no trae otro botón principal"
    assert view.index("gw-workarea__bar") < view.index('id="openRegisterModalBtn"') < view.index("gw-workarea__list"), "buscador y «Registrar nuevo» arriba, la lista debajo"
    assert "autofocus" in BUSC and 'id="searchCedula"' in BUSC
    assert "gw-workarea__list" in view and "directoryTableBody" in view.split("gw-workarea__list")[1]
    assert "Registrar nuevo" in view and "Escanear" in view


def test_single_scan_button_opens_the_camera_and_nothing_attaches_images():
    view = _directory_view()
    toolbar = view[view.index('id="scanQrBtn"'):view.index('id="openRegisterModalBtn"')]
    assert view.count('id="scanQrBtn"') == 1 and "Escanear" in toolbar
    for gone in ("gwScanMenu", "gwScanPanel", "scanMrzBtn", "scanMrzCameraBtn", "scanMrzInput", "regScanMrzBtn", "regScanMrzInput", "Adjuntar imagen"):
        assert gone not in TPL, gone
    assert 'type="file"' not in toolbar
    assert "formats: ['qr_code', 'pdf417']" in TPL and "QrCode.classify" in TPL
    assert "editMrzInput" not in pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")


def test_mobile_page_scrolls_with_the_finger_no_nested_scroll_trap():
    css = pathlib.Path("static/css/p-registro-puerta.css").read_text(encoding="utf-8")
    assert "p-registro-puerta.css" in TPL
    block = css[css.index("@media (max-width: 720px), (pointer: coarse)"):]
    block = block[:block.index("}\n}")]
    assert "overflow: visible" in block and "overscroll-behavior: auto" in block and "height: auto" in block
    assert "overscroll-behavior: contain" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_hardware_and_modes_stay_behind_the_single_gear_with_an_accessible_name():
    assert TPL.count('id="gwRegCfgBtn"') == 1 and 'aria-label="Configuración del registro"' in TPL
    assert "#i-settings" in TPL and 'id="gwRegCfgPanel"' in TPL
    assert re.search(r"\.gw-regcfg__btn \{[^}]*min-width: 44px; min-height: 44px", REG_CSS)
    for ident in ("autoRegisterBtn", "autoPrintBtn", "gwRegCfgBar"):
        panel = TPL[TPL.index('id="gwRegCfgPanel"'):TPL.index("</section>", TPL.index('id="gwRegCfgPanel"'))]
        assert f'id="{ident}"' in panel, ident


def test_offline_notice_text_and_triggers():
    assert "Sin conexión: ves tu lista y lo que registres aquí; no ves a los otros equipos hasta que vuelva la red." in TPL
    assert 'id="gwOfflineAlert" class="gw-alert' in TPL and "navigator.onLine === false" in TPL and "gw:poll" in TPL and "gw:poll" in DIR_JS


def test_visible_text_has_no_technical_jargon():
    assert "({{ staff_role }})" not in TPL and "por Cédula" not in TPL and "POR CEDULA" not in TPL
    assert "Registro y acceso" in TPL
    visible = re.sub(r"<script.*?</script>|\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}|<!--.*?-->", "", TPL, flags=re.S)
    for word in ("Opt_1", "opt_1", "staff_role", "SMTP", "encoding"):
        assert word not in re.sub(r"<[^>]+>", "", visible), word


def test_every_icon_only_button_has_an_accessible_name_and_every_used_icon_exists():
    sprite = (ROOT / "static/img/icons.svg").read_text(encoding="utf-8")
    ids = set(re.findall(r'<symbol id="(i-[\w-]+)"', sprite))
    for name in set(re.findall(r"#(i-[\w-]+)", TPL + BUSC)):
        assert name in ids, name
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", TPL, flags=re.S):
        text = re.sub(r"<svg.*?</svg>|<span[^>]*hidden[^>]*></span>|\{%.*?%\}|\{\{.*?\}\}", "", m.group(2), flags=re.S).strip()
        assert text or "aria-label" in m.group(1), m.group(0)[:120]


def test_new_components_are_in_the_css_the_guide_and_the_standards():
    for cls in ("gw-workarea", "gw-toolbar", "gw-chip", "gw-menu", "gw-origin", "gw-rowact"):
        assert f".{cls}" in DS_CSS and cls in GUIDE and cls in STANDARDS, cls
    for part in (".gw-workarea__bar", ".gw-workarea__list", ".gw-menu__panel", ".gw-menu__item"):
        assert part in DS_CSS and part[1:] in GUIDE, part
    block = _no_comments(DS_CSS[DS_CSS.index("Zona de trabajo (Registro"):])
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block), "solo --gw-*"
    assert "var(--gw-tap)" in block


def test_row_actions_are_visible_in_one_line_and_more_is_only_for_the_rare_destructive():
    """Regla de frecuencia: Acreditar + Imprimir + Editar a la vista en cada fila; «Más» solo con eliminar (con confirmación)."""
    row = DIR_JS[DIR_JS.index("function buildRow"):DIR_JS.index("function renderRows")]
    for label in ("'Imprimir'", "'Editar'", "'Acreditado' : 'Acreditar'"):
        assert label in row, label
    assert "actBtn('Imprimir', 'printer'" in row and "actBtn('Editar', 'edit'" in row and "'Imprimir escarapela'" in row
    more = row[row.index("buildMoreMenu(["):]
    assert "Eliminar de este evento" in more and "Imprimir" not in more.split("who));")[0] and "Editar" not in more.split("who));")[0], "«Más» no esconde imprimir ni editar"
    assert "async function deletePerson" in DIR_JS and "showConfirm(" in DIR_JS[DIR_JS.index("async function deletePerson"):DIR_JS.index("function buildEditModal")]
    assert "btn-table-action" in row and "btn-accredit-row" in row and "is-done" in row, "clases para el modo touch y el estado «Acreditado»"
    assert re.search(r"\.gw-registro \.action-cell \{[^}]*flex-wrap: nowrap", REG_CSS), "una sola línea"
    assert re.search(r"\.gw-registro \.action-cell \.gw-btn \{[^}]*min-height: var\(--gw-tap\)", REG_CSS), "44 px"
    assert "gw-act__t" in REG_CSS and "gw-act__t" in DIR_JS, "texto con ícono; solo ícono en pantallas muy estrechas"


def test_three_step_guide_first_time_tour_and_purposeful_animations():
    assert 'data-gw-tour="registro"' in TPL and "data-gw-tour-auto" in TPL
    steps = re.findall(r'data-gw-tour-step="(\d)"', TPL + BUSC)
    assert sorted(steps) == ["1", "2", "3"]
    assert 'data-gw-tour-restart="registro"' not in BUSC, "la guía ya no vive dentro de la ayuda del buscador: es el 4.º chip del renglón de pasos"
    steps = TPL[TPL.index('class="gw-steps gw-steps--compact"'):]
    steps = steps[:steps.index("</ol>")]
    assert steps.count("<li") == 4 and 'data-gw-tour-restart="registro"' in steps and "gw-registro__steps" not in TPL
    for short in (">Busca<", ">Acredita<", ">Imprime<", ">Guía<"):
        assert short in steps, short
    assert "Imprime la escarapela" in TPL and steps.count("call ayuda(") == 3, "texto completo en el popover de cada paso"
    assert "window.GW_ICON_URL" in TPL
    assert "prefers-reduced-motion: no-preference" in REG_CSS
    for m in re.finditer(r"animation:\s*[\w-]+\s+(\d+)ms", REG_CSS):
        assert int(m.group(1)) <= 250, m.group(0)
    assert "is-done .gw-icon" in REG_CSS and "gw-reason" in REG_CSS and "gw-regcfg__panel:not([hidden])" in REG_CSS


def test_frequency_and_guide_rules_are_in_the_standards():
    assert "Regla de frecuencia" in STANDARDS and "nunca esconder en un menú la acción más usada" in STANDARDS.lower()
    assert "guía de 3 pasos" in STANDARDS and "250 ms" in STANDARDS


def test_celular_la_lista_no_queda_sin_alto():
    css = (ROOT / "static/css/design-system.css").read_text(encoding="utf-8")
    bloque = css.split("@media (max-width: 720px) {\n  .gw-workarea {")[1].split("}")[0]
    assert "height: auto" in bloque, "en celular la zona de trabajo no tiene alto fijo"


def test_search_has_a_trash_button_and_the_created_pill_is_blue():
    """Pedido de Juan David (5-nov-2026): papelera junto a la caja única, y «Recién creado» (alta manual) en píldora sólida AZUL, distinta de «Recién registrado» (verde)."""
    assert 'id="searchClearBtn"' in BUSC and 'aria-label="Borrar lo escrito"' in BUSC and "#i-trash" in BUSC and "gw-search__row" in BUSC
    css = _no_comments(DS_CSS)
    assert ".gw-search__clear" in css and ".gw-recent-tag--new" in css and "var(--gw-info-line)" in css.split(".gw-recent-tag--new")[1].split("}")[0]
    assert "Recién creado" in DIR_JS and "Recién registrado" in DIR_JS and "gw-recent-tag--new" in DIR_JS
    assert "gw-search__clear" in STANDARDS and "gw-recent-tag--new" in STANDARDS and "gw-recent-tag--new" in GUIDE


def test_register_new_always_opens_blank():
    assert "window.resetRegForm" in TPL and "registerModal.style.display !== 'flex'" in TPL


# ------------------------------------------------------------------------------------------------------------------------ Fase 1.7, Ola 1A (remodelado de puerta)
PUERTA_CSS = (ROOT / "static/css/p-registro-puerta.css").read_text(encoding="utf-8")
VERDICT_JS = (ROOT / "static/js/registro-veredicto.js").read_text(encoding="utf-8")


def test_puerta_css_is_loaded_after_registro_css_and_uses_only_tokens():
    assert TPL.index("css/registro.css") < TPL.index("css/p-registro-puerta.css")
    css = _no_comments(PUERTA_CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "p-registro-puerta.css: solo tokens --gw-*"
    assert not re.search(r"font-size:\s*[\d.]+(px|rem|em)", css), "tamaños de texto solo con tokens --gw-fs-*"


def test_one_hero_search_with_scan_next_to_it_and_the_unified_ids_intact():
    view = _directory_view()
    assert "{% set busq_hero = true %}" in TPL and "gw-search--hero" in BUSC and "gw-search__field" in BUSC and "#i-search" in BUSC
    assert view.count('id="searchCedula"') + BUSC.count('id="searchCedula"') >= 1 and TPL.count("_gw_buscador.html") == 2
    assert 'id="scanQrBtn" class="gw-btn gw-btn--secondary gw-btn--xl"' in view and "Registrar nuevo" in view


def test_connection_and_verdict_pieces_exist_and_the_offline_alert_stays():
    assert 'id="gwConn" class="gw-conn"' in TPL and "En línea" in TPL and "Sin conexión, guardando" in TPL and "#i-wifi" in TPL
    assert 'id="gwVerdict" class="gw-verdict"' in TPL and "js/registro-veredicto.js" in TPL
    assert TPL.index("js/registro-veredicto.js") < TPL.index("js/directory.js")
    assert 'id="gwOfflineAlert"' in TPL
    assert "window.GWVerdict" in VERDICT_JS and "role" in VERDICT_JS


def test_verdict_calls_cover_accredited_already_registered_and_not_found():
    assert "verdict('ok', 'Acreditado(a)'" in DIR_JS and "verdict('warn', 'Ya estaba registrado(a)'" in DIR_JS and "verdict('err', 'No está en la lista'" in DIR_JS


def test_register_modal_keeps_ids_and_folds_only_simple_optional_fields():
    assert "{% macro reg_field(cfg) %}" in TPL and 'id="regExtras"' in TPL and "Más datos (opcional)" in TPL
    assert "reg_core_only" in TPL and "gw-form-group" in TPL
    assert 'id="regPhotoGroup"' in TPL and 'id="regPhotoInput"' in TPL and 'id="regBioConsent"' in TPL and 'id="regPhotoCameraBtn"' in TPL
    ids = re.findall(r'\bid="([\w-]+)"', TPL)
    for ident in ("gwWorkarea", "directorio"):
        assert ids.count(ident) == 2, ident          # uno por rama (cliente / resto de roles): son excluyentes en el mismo render
    assert TPL.index("{% if staff_role == \"cliente\" %}\n        <!-- PESTAÑA: ESTADÍSTICAS") < TPL.index("{% else %}\n\n        {% if event.facial_enabled %}")


def test_compact_mobile_first_screen_rules_without_nested_scroll():
    css = pathlib.Path("static/css/p-registro-puerta.css").read_text(encoding="utf-8")
    for needle in (".gw-steps--compact", "repeat(3, minmax(0, 1fr)) auto", "gw-registro__headside { flex-wrap: nowrap", ".gw-workarea__summary .gw-chip"):
        assert needle in css, needle
    assert "overscroll-behavior: contain" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_list_is_not_redrawn_under_the_finger_so_the_touch_scroll_is_not_cancelled():
    """Causa real del atasco en el celular: el sondeo redibujaba las filas (replaceChildren) con el dedo encima y el navegador cancelaba el gesto de desplazar."""
    js = pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    body = js[js.index("function drawRows()"):]
    body = body[:body.index("\n    }\n")]
    assert "if (gestureBusy()) { redrawSoon(); return; }" in body
    assert "touchstart" in js and "touchcancel" in js and "passive: true" in js
    assert "tbody.replaceChildren(...rows)" in body and "const same =" in body, "si las filas son las mismas no se toca el DOM"
    css = pathlib.Path("static/css/p-registro-puerta.css").read_text(encoding="utf-8")
    assert "touch-action: manipulation" in css
    assert "preventDefault" not in "".join(l for l in js.splitlines() if "touchstart" in l or "touchmove" in l)


def test_m10_person_card_compact_kebab_and_loose_badges():
    """M10: tarjeta compacta (nombre en una línea, cédula+estado+origen sueltos, acciones en una fila con «Más» como tres puntos) y CSS bien cerrado."""
    css = (ROOT / "static" / "css" / "p-registro-puerta.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), "llaves balanceadas: un bloque sin cerrar dejó las reglas de M2/M4 dentro de prefers-reduced-motion"
    assert "'more'" in DIR_JS and "gw-menu__btn--kebab" in DIR_JS and 'aria-expanded' in DIR_JS and "'Escape'" in DIR_JS and "ArrowDown" in DIR_JS
    assert 'id="i-more"' in (ROOT / "static" / "img" / "icons.svg").read_text(encoding="utf-8")
    row = DIR_JS[DIR_JS.index("function buildRow"):DIR_JS.index("function renderRows")]
    assert "dataset.field = 'origin'" in row and "['recent', 'reason']" in row, "origen, «Recién registrado» y motivo van en casillas propias (sin insignias anidadas en el estado)"
    assert "statusTd.appendChild" not in row
    for rule in ("td[data-field=origin]", "td[data-field=recent]", "text-overflow: ellipsis", ".gw-menu__btn--kebab", "flex-wrap: nowrap"):
        assert rule in css, rule
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "solo tokens --gw-*"
