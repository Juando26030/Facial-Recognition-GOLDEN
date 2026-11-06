"""Reingeniería visual de «Parámetros del evento» (estándares: docs/ux/ESTANDARES_VISUALES.md). Pruebas sobre los archivos: base visual y tema, pestañas, un solo botón principal,
sin colores/tamaños sueltos, sin emojis como íconos, sin jerga técnica, controles con nombre, íconos del sprite, recorrido de primera vez y acciones destructivas en rojo."""
import pathlib
import re
from html.parser import HTMLParser

from tests.conftest import login

TEMPLATE = pathlib.Path("templates/kiosk_parametros.html").read_text(encoding="utf-8")
PAGE_CSS = pathlib.Path("static/css/parametros.css").read_text(encoding="utf-8")
SAVE_JS = pathlib.Path("static/js/params-save.js").read_text(encoding="utf-8")
DS_CSS = pathlib.Path("static/css/design-system.css").read_text(encoding="utf-8")
SPRITE = pathlib.Path("static/img/icons.svg").read_text(encoding="utf-8")
GUIDE = pathlib.Path("docs/ux/guia_visual.html").read_text(encoding="utf-8")
EMOJI = re.compile("[←-⇿⌀-⏿☀-➿⬀-⯿\U0001f000-\U0001faff️]")
TABS = ["registro", "facial", "invitaciones", "impresion", "escarapelas", "zonas", "campos", "privacidad"]


def _visible_text(src: str) -> str:
    no_code = re.sub(r"<script.*?</script>|<!--.*?-->|\{#.*?#\}|\{%.*?%\}", " ", src, flags=re.S)
    return re.sub(r"<[^>]+>", " ", no_code)


def test_the_page_uses_the_visual_base_the_theme_toggle_and_a_plain_title():
    assert '<body class="gw-page gw-parametros' in TEMPLATE
    assert '{% include "_gw_head.html" %}' in TEMPLATE and '{% include "_gw_theme_toggle.html" %}' in TEMPLATE
    assert "<title>Parámetros del evento |" in TEMPLATE and "<h1 class=\"gw-title\">Parámetros del evento</h1>" in TEMPLATE
    assert "gradient-text" not in TEMPLATE and "golden-section-title" not in TEMPLATE, "sin palabras de color suelto en el título"
    assert "url_for('static', path='css/parametros.css')" in TEMPLATE
    assert "css/design-system.css" not in TEMPLATE, "el CSS base entra por _gw_head.html (una sola vez)"


def test_there_is_a_single_primary_button_and_no_legacy_button_classes():
    assert TEMPLATE.count("gw-btn--primary") == 1 and 'class="gw-btn gw-btn--primary" id="paramsSaveBtn"' in TEMPLATE and ">Guardar cambios<" in TEMPLATE
    assert "gw-btn--primary" not in SAVE_JS
    for legacy in ("golden-btn", "small-btn", "onclick", "params-table"):
        assert legacy not in TEMPLATE, legacy


def test_no_inline_styles_hex_colors_or_loose_sizes():
    assert not re.search(r"""style\s*=\s*["'`\\]""", TEMPLATE), "ningún style= (ni en el HTML ni en el que arma el JS)"
    for name, src in (("template", TEMPLATE), ("css", PAGE_CSS), ("js", SAVE_JS)):
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", src), f"{name}: colores sueltos"
    assert not re.search(r"\.style\.(cssText|color|fontWeight|fontSize|margin|width|height|border|background|padding)", TEMPLATE + SAVE_JS), "colores y medidas por clase, no por JS"
    assert not re.findall(r"border-radius\s*:\s*\d", PAGE_CSS), "radios con tokens"
    assert "<style" not in TEMPLATE.split("</head>")[0], "sin bloque <style> en la cabecera"


def test_no_text_under_14px():
    for name, src in (("template", TEMPLATE), ("css", PAGE_CSS), ("js", SAVE_JS)):
        for val in re.findall(r"font-size\s*:\s*([^;}\"']+)", src):
            val = val.strip()
            if val.startswith("var(--gw-fs-"):
                continue
            num = float(re.match(r"[\d.]+", val).group(0))
            px = num * 16 if val.endswith("rem") or val.endswith("em") else num
            assert px >= 14, f"{name}: font-size {val}"
    assert "<small" not in TEMPLATE
    assert float(re.search(r"--gw-fs-sm:\s*([\d.]+)rem", DS_CSS).group(1)) * 16 >= 14


def test_no_emojis_or_symbols_as_icons():
    for name, src in (("template", TEMPLATE), ("js", SAVE_JS)):
        found = sorted(set(EMOJI.findall(src)))
        assert not found, f"{name}: {found}"
    for ident in re.findall(r"""(?:ic|gwIcon)\('([a-z-]+)'""", TEMPLATE):
        assert f'id="i-{ident}"' in SPRITE, f"falta el ícono {ident} en el sprite"
        assert f'id="i-{ident}"' in GUIDE, f"falta el ícono {ident} en la guía visual"


def test_no_technical_jargon_in_the_visible_text():
    text = _visible_text(TEMPLATE)
    for word in ("SMTP", "Twilio", "encoding", ".env", "FACE_ENCRYPTION_KEY", "Paso 0", "/rostro", "Paso 1", "Paso 2", "Paso 3", "token", "endpoint"):
        assert word not in text, word
    assert "Abrir pantalla de la puerta" in text and "Parámetros del evento" in text
    assert "FACE_ENCRYPTION_KEY" not in TEMPLATE


class _Controls(HTMLParser):
    """Recorre el HTML y anota los controles sin nombre accesible (ni <label>, ni for=, ni aria-label)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.label_depth = 0
        self.label_for, self.controls = set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            if tag == "input" and a.get("type") in ("hidden", "button", "submit"):
                return
            self.controls.append((tag, a, self.label_depth > 0))

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1


def test_every_control_has_a_name_and_the_tabs_are_wired_to_their_panels():
    p = _Controls()
    p.feed(re.sub(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", "", re.sub(r"<script.*?</script>", "", TEMPLATE, flags=re.S), flags=re.S))
    nameless = [(t, a.get("id") or a.get("name")) for t, a, in_label in p.controls if not (in_label or a.get("aria-label") or a.get("id") in p.label_for)]
    assert nameless == [], nameless
    tabs = re.findall(r'role="tab" id="(tab_\w+)" data-tab="(\w+)" aria-controls="(grp_\w+)"', TEMPLATE)
    assert [t[1] for t in tabs] == TABS
    for tab_id, name, panel in tabs:
        assert f'id="{panel}" data-group="{name}" aria-labelledby="{tab_id}"' in TEMPLATE
    assert 'role="tablist"' in TEMPLATE and TEMPLATE.count('role="tab"') == 8 and TEMPLATE.count("gw-tab__sum") == 8, "cada pestaña dice en una línea cómo está"
    for fixed in ("Registro y pantalla", "Reconocimiento facial", "Invitaciones", "Impresión y reimpresión", "Escarapelas y certificados", "Campos", "Privacidad"):
        assert f'<span class="gw-tab__name">{fixed}</span>' in TEMPLATE, fixed


def test_touch_targets_and_motion_follow_the_standard():
    assert re.search(r"\.gw-choice \{[^}]*min-height: var\(--gw-tap\)", DS_CSS) and re.search(r"\.gw-input, \.gw-select, \.gw-textarea \{[^}]*min-height: var\(--gw-tap\)", DS_CSS)
    assert re.search(r"\.gw-tab \{[^}]*min-height: var\(--gw-tap\)", DS_CSS)
    assert re.search(r"\.gw-tabpanel \{[^}]*animation: gw-tab-in var\(--gw-dur\)", DS_CSS) and int(re.search(r"--gw-dur:\s*(\d+)ms", DS_CSS).group(1)) <= 250
    assert re.search(r"animation: gw-pop (\d+)ms", DS_CSS) and int(re.search(r"animation: gw-pop (\d+)ms", DS_CSS).group(1)) <= 250
    assert "animation-duration: 0.001ms" in DS_CSS and "prefers-reduced-motion: reduce" in DS_CSS, "movimiento reducido: sin animaciones"
    assert "gw-tab" in DS_CSS and "overflow-x: auto" in re.search(r"\.gw-tablist \{[^}]*\}", DS_CSS).group(0), "en celular las pestañas se desplazan dentro de su caja"


def test_first_time_tour_three_step_guide_and_help_buttons():
    assert 'data-gw-tour="parametros" data-gw-tour-auto' in TEMPLATE and 'data-gw-tour-restart="parametros"' in TEMPLATE
    assert len(re.findall(r"data-gw-tour-step=\"\d\"", TEMPLATE)) == 3
    assert TEMPLATE.count('class="gw-steps__n"') == 3 and "Elige la sección" in TEMPLATE and "Cambia lo que necesites" in TEMPLATE and "Guarda los cambios" in TEMPLATE
    assert TEMPLATE.count("{% call ayuda(") >= 15, "el detalle largo va en «?» y no en párrafos grises"
    assert 'data-gw-help-btn aria-expanded="false"' in TEMPLATE and 'aria-label="Ayuda: {{ titulo }}"' in TEMPLATE and "data-gw-help-close" in TEMPLATE
    guide_js = pathlib.Path("static/js/gw-ui.js").read_text(encoding="utf-8")
    assert "gw_tour_" in guide_js and re.search(r"try \{", guide_js), "una vez por dispositivo, con localStorage dentro de try/catch"


def test_privacy_actions_are_red_and_ask_for_confirmation():
    for ident, cls in (("privPerson", "gw-btn--danger-outline"), ("privRevoke", "gw-btn--danger-outline"), ("privAll", "gw-btn gw-btn--danger"), ("privEvent", "gw-btn gw-btn--danger")):
        assert re.search(rf'<button type="button" id="{ident}" class="[^"]*{cls}', TEMPLATE), ident
    assert 'class="gw-danger-zone"' in TEMPLATE and "--gw-err-line" in re.search(r"\.gw-danger-zone \{[^}]*\}", DS_CSS).group(0)
    assert "showConfirm(`¿Borrar el rostro" in TEMPLATE and "purgeData('all'," in TEMPLATE and "await showConfirm(msg.replace" in TEMPLATE and "purgeEventBiometrics" in TEMPLATE
    assert re.search(r"\.gw-btn--danger \{[^}]*var\(--gw-danger\)", DS_CSS)


def test_instant_and_pending_changes_are_told_apart_and_the_reprint_history_is_a_table_with_badges():
    assert TEMPLATE.count("Al instante") >= 5 and "Sin guardar" in TEMPLATE
    assert "Cambios sin guardar" in SAVE_JS and "Guardado'" in SAVE_JS and "'check'" in SAVE_JS, "el Guardar confirma con un check"
    reprint = TEMPLATE[TEMPLATE.index('id="reprintCard"'):TEMPLATE.index('id="sharedPrintCard"')]
    assert 'name="reprintMode" value="enabled"' in reprint and 'name="reprintMode" value="disabled"' in reprint and 'id="reprintHistory"' in reprint
    hist = TEMPLATE[TEMPLATE.index("async function loadReprintHistory"):TEMPLATE.index("// Paso guiado de biometría")]
    assert 'class="gw-table gw-pm-stack"' in hist and "gw-badge" in hist and all(s in hist for s in ("pending:", "approved:", "denied:", "expired:", "used:"))


def test_the_page_renders_for_a_coordinator_with_every_section(client, factory):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "coord")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert '<body class="gw-page gw-parametros' in page and page.count('role="tab"') == 8 and page.count('role="tabpanel"') == 8
    assert 'data-gw-tour="parametros"' in page and 'id="paramsSaveBtn"' in page and "Guardar cambios" in page
    main = page[page.index("<main"):page.index("</main>")]
    assert "style=" not in main, "el cuerpo de la pantalla no trae estilos en línea"
