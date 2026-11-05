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
    assert len(re.findall(r"gw-btn--primary", view)) == 1 and 'id="openRegisterModalBtn" class="gw-btn gw-btn--primary"' in view
    assert "gw-btn--primary" not in BUSC, "el buscador (con su ayuda) no trae otro botón principal"
    assert view.index("gw-workarea__bar") < view.index('id="openRegisterModalBtn"') < view.index("gw-workarea__list"), "buscador y «Registrar nuevo» arriba, la lista debajo"
    assert "autofocus" in BUSC and 'id="searchCedula"' in BUSC
    assert "gw-workarea__list" in view and "directoryTableBody" in view.split("gw-workarea__list")[1]
    assert "Registrar nuevo" in view and "Escanear" in view


def test_scan_actions_are_grouped_and_keep_their_ids():
    view = _directory_view()
    menu = view[view.index('id="gwScanMenu"'):view.index('id="openRegisterModalBtn"')]
    for ident in ("scanQrBtn", "scanMrzBtn", "scanMrzCameraBtn", "scanMrzInput"):
        assert f'id="{ident}"' in menu, ident


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


def test_row_actions_have_one_main_button_and_a_more_menu():
    assert "buildMoreMenu" in DIR_JS and "'Acreditar'" in DIR_JS and "btn-accredit-row" in DIR_JS
    assert "aria-label', 'Más acciones" in DIR_JS and "innerText = '🖨" not in DIR_JS
