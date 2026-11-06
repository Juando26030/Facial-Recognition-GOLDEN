"""Base visual común (Fase 1A, pieza 0): contrastes WCAG AA por código, tokens en claro y oscuro, interruptor de tema, ayuda «?» con teclado, animaciones con alternativa de movimiento
reducido, plantillas con url_for('static', ...) y el sprite de íconos. Pruebas de archivos: no necesitan base de datos ni servidor."""
import pathlib
import re

CSS = pathlib.Path("static/css/design-system.css").read_text(encoding="utf-8")
JS = pathlib.Path("static/js/gw-ui.js").read_text(encoding="utf-8")
SPRITE = pathlib.Path("static/img/icons.svg").read_text(encoding="utf-8")
GUIDE = pathlib.Path("docs/ux/guia_visual.html").read_text(encoding="utf-8")
TEMPLATES = sorted(pathlib.Path("templates").glob("*.html"))


# ------------------------------------------------------------------------------------------------------------------------------------ colores
def _block(selector_start):
    """Cuerpo de la primera regla cuyo selector empieza por `selector_start`."""
    i = CSS.index(selector_start)
    return CSS[CSS.index("{", i) + 1:CSS.index("\n}", i)]


def _tokens(block):
    return dict(re.findall(r"(--gw-[\w-]+):\s*([^;]+);", block))


LIGHT = _tokens(_block(":root, .gw-no-theme"))
DARK = {**LIGHT, **_tokens(_block(':root[data-theme="dark"] {'))}


def _hex(value):
    v = value.strip().lower()
    assert re.fullmatch(r"#[0-9a-f]{6}", v), f"se esperaba un #rrggbb, hay: {value}"
    return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    a, b = sorted((_lum(_hex(fg)), _lum(_hex(bg))), reverse=True)
    return (a + 0.05) / (b + 0.05)


# (primer plano, fondo, mínimo, descripción). 4,5 = texto normal; 3 = texto grande, íconos, bordes de controles y anillo de foco.
TEXT_PAIRS = [
    ("--gw-text", "--gw-bg", 4.5), ("--gw-text", "--gw-surface", 4.5), ("--gw-text", "--gw-surface-2", 4.5),
    ("--gw-text-muted", "--gw-bg", 4.5), ("--gw-text-muted", "--gw-surface", 4.5), ("--gw-text-muted", "--gw-surface-2", 4.5),
    ("--gw-link", "--gw-bg", 4.5), ("--gw-link", "--gw-surface", 4.5), ("--gw-link", "--gw-surface-2", 4.5),
    ("--gw-gold-text", "--gw-bg", 4.5), ("--gw-gold-text", "--gw-surface", 4.5), ("--gw-gold-text", "--gw-surface-2", 4.5),
    ("--gw-on-gold", "--gw-gold-1", 4.5), ("--gw-on-gold", "--gw-gold-2", 4.5),                         # texto de botones y mosaicos sobre los DOS extremos del degradado
    ("--gw-on-danger", "--gw-danger", 4.5),
    ("--gw-secondary-text", "--gw-secondary-bg", 4.5),
    ("--gw-ok-text", "--gw-ok-bg", 4.5), ("--gw-ok-bg", "--gw-ok-text", 4.5), ("--gw-warn-text", "--gw-warn-bg", 4.5), ("--gw-err-text", "--gw-err-bg", 4.5), ("--gw-info-text", "--gw-info-bg", 4.5),
    ("--gw-err-text", "--gw-surface", 4.5), ("--gw-err-text", "--gw-surface-2", 4.5), ("--gw-secondary-text", "--gw-surface-2", 4.5),                                                             # mensaje de error de un campo
    ("--gw-nav-text", "--gw-nav-bg", 4.5), ("--gw-nav-accent", "--gw-nav-bg", 4.5),
]
NON_TEXT_PAIRS = [
    ("--gw-border-strong", "--gw-surface", 3), ("--gw-border-strong", "--gw-bg", 3),                    # borde de campos y botones secundarios
    ("--gw-focus", "--gw-surface", 3), ("--gw-focus", "--gw-bg", 3),                                    # anillo de foco
    ("--gw-ok-line", "--gw-ok-bg", 3), ("--gw-warn-line", "--gw-warn-bg", 3), ("--gw-err-line", "--gw-err-bg", 3), ("--gw-info-line", "--gw-info-bg", 3),   # íconos y bordes de estado
    ("--gw-err-line", "--gw-surface", 3),                                                               # borde de un campo con error
    ("--gw-gold-1", "--gw-surface", 3),                                                                 # borde dorado al pasar sobre un mosaico
    ("--gw-nav-accent", "--gw-nav-bg", 3),
    ("--gw-ok-line", "--gw-surface", 3), ("--gw-warn-line", "--gw-surface", 3), ("--gw-info-line", "--gw-surface", 3),   # barra de estado de .gw-person y borde de .gw-conn/.gw-stat sobre superficie
]


def _check(pairs, theme_name, tokens):
    bad = []
    for fg, bg, minimum in pairs:
        got = ratio(tokens[fg], tokens[bg])
        if got < minimum:
            bad.append(f"{theme_name}: {fg} {tokens[fg]} sobre {bg} {tokens[bg]} = {got:.2f}:1 (mínimo {minimum}:1)")
    return bad


def test_text_pairs_reach_4_5_to_1_in_light_and_dark():
    assert _check(TEXT_PAIRS, "claro", LIGHT) + _check(TEXT_PAIRS, "oscuro", DARK) == []


def test_icons_borders_and_focus_ring_reach_3_to_1_in_light_and_dark():
    assert _check(NON_TEXT_PAIRS, "claro", LIGHT) + _check(NON_TEXT_PAIRS, "oscuro", DARK) == []


def test_the_contrast_calculator_matches_known_wcag_values():
    assert round(ratio("#000000", "#ffffff"), 2) == 21.0
    assert round(ratio("#777777", "#ffffff"), 2) == 4.48            # el gris clásico que NO llega a 4,5 (docs/ux/PLAN_FASE1_UX.md)
    assert ratio("#ffffff", "#ffffff") == 1.0


def test_dark_theme_redefines_every_surface_text_and_state_token():
    must = ["--gw-bg", "--gw-surface", "--gw-surface-2", "--gw-border", "--gw-border-strong", "--gw-text", "--gw-text-muted", "--gw-link", "--gw-gold-text", "--gw-focus",
            "--gw-danger", "--gw-on-danger", "--gw-secondary-bg", "--gw-secondary-text"] + [f"--gw-{s}-{p}" for s in ("ok", "warn", "err", "info") for p in ("bg", "text", "line")]
    own = _tokens(_block(':root[data-theme="dark"] {'))
    assert [t for t in must if t not in own] == []
    assert "prefers-color-scheme" not in CSS, "el tema oscuro es POR DISPOSITIVO (interruptor), no sigue al sistema operativo"


def test_brand_palette_and_scales_are_declared():
    assert LIGHT["--gw-gold-1"] == "#b8862b" and LIGHT["--gw-gold-2"] == "#e8c25a" and LIGHT["--gw-navy"] == "#1e2a6e" and LIGHT["--gw-navy-deep"] == "#141c4d"
    assert LIGHT["--gw-tap"] == "44px"
    assert all(f"--gw-sp-{i}" in LIGHT for i in range(1, 9)) and all(k in LIGHT for k in ("--gw-radius-sm", "--gw-radius-md", "--gw-radius-lg", "--gw-shadow-md", "--gw-ring", "--gw-fs-sm", "--gw-fs-3xl"))
    assert "Agrandir" in LIGHT["--gw-font"]
    assert float(LIGHT["--gw-fs-sm"].replace("rem", "")) * 16 >= 14, "ningún tamaño de texto por debajo de 14 px"


def test_no_font_size_in_the_base_is_below_14px():
    for m in re.finditer(r"font-size:\s*([\d.]+)(px|rem)", CSS):
        px = float(m.group(1)) * (16 if m.group(2) == "rem" else 1)
        assert px >= 14, m.group(0)


def test_touch_targets_use_the_44px_token():
    for sel in (".gw-btn {", ".gw-input, .gw-select, .gw-textarea {", ".gw-check {", ".gw-help__btn {", ".gw-theme-toggle {", ".gw-nav__link {", ".gw-nav__toggle {"):
        rule = CSS[CSS.index(sel):CSS.index("}", CSS.index(sel))]
        assert "min-height: var(--gw-tap)" in rule, sel


def test_focus_ring_and_reduced_motion_are_in_the_base():
    assert ":focus-visible" in CSS and "var(--gw-ring)" in CSS
    reduced = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation-duration" in reduced and "transition-duration" in reduced and "scroll-behavior: auto" in reduced


def test_everything_in_the_base_is_behind_gw_classes_so_old_screens_do_not_change():
    """Fuera de :root, .gw-*, la barra lateral compartida y las @media/@keyframes, ninguna regla toca elementos sueltos."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for sel in re.findall(r"(?m)^([^\s@}{][^{]*)\{", css):
        for part in (p.strip() for p in sel.split(",")):
            assert part.startswith((":root", ":where(.gw-page)", ".gw-", ".golden-sidebar", ".golden-nav-user", ".golden-header .gw-", "[data-gw-search-slot")) or re.fullmatch(r"(\d+%|from|to)(,\s*\d+%)*", part), part
        # dentro de una @media los selectores van indentados; los revisa la regla de abajo
    for sel in re.findall(r"(?m)^\s+([.\[:][^{@]*)\{", css):
        for part in (p.strip() for p in sel.split(",")):
            assert part.startswith((".gw-", ":root", ":where(.gw-page)", ".golden-sidebar", ".golden-header .gw-", "[data-gw-search-slot", "0%", "100%")) or re.fullmatch(r"[\d%\s,]+", part), part


# ------------------------------------------------------------------------------------------------------------------------------------ interruptor de tema
def test_theme_switch_exists_stores_per_device_with_try_catch_and_applies_before_paint():
    toggle = pathlib.Path("templates/_gw_theme_toggle.html").read_text(encoding="utf-8")
    assert "data-gw-theme-toggle" in toggle and 'aria-pressed="false"' in toggle and "onclick" not in toggle
    head = pathlib.Path("templates/_gw_head.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('gw_theme')" in head and "try {" in head and "data-theme" in head, "el tema se aplica antes de pintar (sin parpadeo)"
    assert "url_for('static', path='css/design-system.css')" in head and "url_for('static', path='js/gw-ui.js')" in head
    assert "gw_theme" in JS and re.search(r"try \{ if \(get\)", JS), "guardar/leer en localStorage va dentro de try/catch"
    login = pathlib.Path("templates/login.html").read_text(encoding="utf-8")
    assert '_gw_head.html' in login and '_gw_theme_toggle.html' in login and 'class="gw-page"' in login
    assert "data-gw-theme-toggle" in GUIDE


def test_the_dark_theme_never_reaches_what_is_printed():
    assert ".gw-no-theme" in CSS and ":root, .gw-no-theme" in CSS
    assert 'class="gw-no-theme' in GUIDE
    assert not [t.name for t in TEMPLATES if t.name in ("badge_print.html", "badge_editor.html", "digital_badge.html", "impresion_usb.html") and "_gw_head" in t.read_text(encoding="utf-8")], \
        "las pantallas de impresión y escarapela no adoptan el tema oscuro"


# ------------------------------------------------------------------------------------------------------------------------------------ ayuda «?», recorrido, asistente
def test_help_button_works_with_keyboard_and_screen_readers():
    for needle in ("data-gw-help-btn", "'aria-expanded'", "trapTab", "'Escape'", "closeHelp(true)", "data-gw-help-close"):
        assert needle in JS, needle
    for html in (GUIDE, pathlib.Path("templates/login.html").read_text(encoding="utf-8")):
        for tag in re.findall(r"<button[^>]*data-gw-help-btn[^>]*>", html):
            assert "aria-expanded" in tag and "aria-controls" in tag and "aria-label" in tag, tag
        for pop in re.findall(r'<div class="gw-popover"[^>]*>', html):
            assert 'role="dialog"' in pop and "aria-labelledby" in pop and "hidden" in pop, pop
        assert html.count("data-gw-help-close") >= html.count('<div class="gw-popover"') > 0, "cada ayuda trae su botón «Entendido»"
        assert html.count(">Entendido<") >= html.count('<div class="gw-popover"')


def test_animations_have_a_reduced_motion_alternative_and_a_static_final_frame():
    anims = set(re.findall(r"\.gw-anim--(\w+)", CSS))
    assert {"search", "print", "theme"} <= anims
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.gw-anim \*, \.gw-anim \{ animation: none !important; \}", CSS), "con movimiento reducido el dibujo queda quieto"
    assert "reducedMotion()" in JS                                         # el recorrido también evita el desplazamiento suave
    for name in anims:
        assert f"gw-anim--{name}" in GUIDE, f"la guía muestra la animación «{name}»"
    # sin vídeo, sin librerías: solo SVG y CSS
    assert not re.search(r"<video|\.gif|lottie|gsap", GUIDE + CSS + JS, re.I)


def test_first_time_tour_is_once_per_device_with_restart_and_no_external_dependencies():
    for needle in ("'gw_tour_'", "data-gw-tour-restart", "data-gw-tour-skip", "'Paso '", "' de '", "Siguiente", "Atrás", "Omitir", "aria-modal"):
        assert needle in JS, needle
    assert "tourSeen(key)" in JS and re.search(r"function store\(get, key, value\) \{[^}]*try \{", JS), "localStorage con try/catch"
    assert "Ver recorrido de nuevo" in GUIDE and "data-gw-tour-step" in GUIDE
    assert not re.search(r"https?://", JS), "sin red: nada se pide fuera del servidor"
    assert not re.search(r"\b(alert|confirm|prompt)\(", JS)


def _rule(selector):
    """Declaraciones de la primera regla cuyo selector empieza EXACTAMENTE por `selector {`."""
    i = CSS.index(selector + " {")
    return CSS[CSS.index("{", i) + 1:CSS.index("}", i)]


def test_group_and_savebar_components_use_only_verified_token_pairs_and_the_44px_target():
    """Plan 6 (Parámetros agrupado): el título del grupo (texto sobre superficie y sobre superficie-2 al abrir/pasar), la ayuda, la lista de fallos y las insignias de estado de la barra
    usan pares ya verificados arriba, en claro y en oscuro; el título del grupo es un objetivo táctil de 44 px."""
    for cls in (".gw-group", ".gw-group__sum", ".gw-group__body", ".gw-group__item", ".gw-savebar", ".gw-savebar__status", ".gw-savebar__fail"):
        assert cls + " {" in CSS, cls
    assert "min-height: var(--gw-tap)" in _rule(".gw-group__sum")
    pairs = {(fg, bg) for fg, bg, _ in TEXT_PAIRS}
    assert "color: var(--gw-text)" in _rule(".gw-group") and "background: var(--gw-surface)" in _rule(".gw-group") and ("--gw-text", "--gw-surface") in pairs
    assert "background: var(--gw-surface-2)" in CSS[CSS.index(".gw-group[open] > .gw-group__sum {"):] and ("--gw-text", "--gw-surface-2") in pairs
    assert "color: var(--gw-text-muted)" in _rule(".gw-group__hint") and ("--gw-text-muted", "--gw-surface") in pairs and ("--gw-text-muted", "--gw-surface-2") in pairs
    fail = _rule(".gw-savebar__fail")
    assert "color: var(--gw-err-text)" in fail and "background: var(--gw-err-bg)" in fail and ("--gw-err-text", "--gw-err-bg") in pairs
    bar = _rule(".gw-savebar")
    assert "color: var(--gw-text)" in bar and "background: var(--gw-surface)" in bar and "position: sticky" in bar and "bottom: 0" in bar
    # los bordes de estado de la barra son los de las insignias (>= 3:1 sobre su fondo, ya verificados)
    for state, line in (("dirty", "warn"), ("saved", "ok"), ("error", "err")):
        assert f'.gw-savebar[data-state="{state}"] {{ border-color: var(--gw-{line}-line); }}' in CSS
    assert ("--gw-warn-line", "--gw-warn-bg", 3) in NON_TEXT_PAIRS and ("--gw-ok-line", "--gw-ok-bg", 3) in NON_TEXT_PAIRS and ("--gw-err-line", "--gw-err-bg", 3) in NON_TEXT_PAIRS
    # fuera del CSS de la base, ni un color suelto en estos componentes
    block = CSS[CSS.index("Grupo desplegable (<details"):]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", block), "solo tokens --gw-*"
    # y la guía los muestra
    for needle in ("gw-group", "gw-savebar", 'data-state="dirty"', 'data-state="saved"', 'data-state="error"'):
        assert needle in GUIDE, needle


def test_wizard_and_state_components_exist_and_leave_the_search_slot_unbuilt():
    for cls in (".gw-wizard__foot", ".gw-progress", ".gw-state--error", ".gw-spinner", ".gw-tile", ".gw-modal", ".gw-nav", ".gw-badge--ok", ".gw-alert--err", ".gw-table", ".gw-field--error"):
        assert cls in CSS, cls
    assert "Paso 1 de 3" in GUIDE and "data-gw-wizard-next" in GUIDE
    assert "data-gw-search-slot" in GUIDE and "Fase 2" in GUIDE
    assert "startSearch" not in JS and "search-slot" not in CSS.split("Hueco del futuro")[0], "el buscador se deja como hueco documentado, sin construirlo"


# ------------------------------------------------------------------------------------------------------------------------------------ íconos y plantillas
NEEDED_ICONS = {"users", "user-plus", "search", "camera", "face", "printer", "badge", "form", "chart", "calendar", "settings", "help", "check", "error", "alert", "info", "sun", "moon"}


def test_sprite_has_the_icons_needed_for_the_tiles_and_the_guide_inlines_the_same_ones():
    ids = set(re.findall(r'<symbol id="i-([\w-]+)"', SPRITE))
    assert NEEDED_ICONS <= ids
    assert not re.search(r"https?://(?!www\.w3\.org)", SPRITE) and "<script" not in SPRITE and "<image" not in SPRITE
    assert ids == set(re.findall(r'<symbol id="i-([\w-]+)"', GUIDE)), "la guía lleva copiado el mismo sprite (un <use> externo no funciona con file://)"


def test_every_template_loads_static_files_only_through_url_for_and_the_base():
    for t in TEMPLATES:
        text = t.read_text(encoding="utf-8")
        if "css/style.css" in text:
            assert ("css/design-system.css" in text or "_gw_head.html" in text), f"{t.name} carga style.css pero no la base visual (el menú lateral compartido la necesita)"
    for name in ("login.html", "_gw_head.html", "_gw_theme_toggle.html", "_sidebar.html", "_kiosk_top.html"):
        text = pathlib.Path("templates", name).read_text(encoding="utf-8")
        assert not re.search(r'(?:href|src)="/static/', text), name
        assert "url_for('static'" in text, name


def test_login_keeps_its_form_contract_and_has_no_inline_handlers():
    login = pathlib.Path("templates/login.html").read_text(encoding="utf-8")
    assert 'method="post" action="/login"' in login and 'name="username"' in login and 'name="password"' in login and "/olvide-contrasena" in login
    assert "onclick" not in login and "_legal_footer.html" in login and "_env_badge.html" in login
    assert re.search(r"<label[^>]*for=\"usuario\"", login) and re.search(r"<label[^>]*for=\"clave\"", login)


def test_shared_nav_uses_svg_icons_not_emoji_and_the_footer_follows_the_theme_tokens():
    side = pathlib.Path("templates/_sidebar.html").read_text(encoding="utf-8")
    assert not re.search(r"[\U0001F300-\U0001FAFF⚙☰]", side)
    assert "gw-icon" in side and "#i-building" in side and "#i-settings" in side
    assert "var(--gw-text-muted" in pathlib.Path("templates/_legal_footer.html").read_text(encoding="utf-8")


def test_the_kiosk_precaches_what_the_pages_load_so_the_base_works_offline():
    """El service worker del quiosco guarda los /static/* que la página efectivamente cargó (performance.getEntriesByType): la base entra sola si la página la enlaza."""
    for name in ("kiosk_registro.html", "kiosk_rostro.html"):
        text = pathlib.Path("templates", name).read_text(encoding="utf-8")
        assert "css/design-system.css" in text or "_gw_head.html" in text, name        # Registro (Plan 7) la trae por _gw_head.html
    reg = pathlib.Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "performance.getEntriesByType('resource')" in reg and "startsWith(location.origin + '/static/')" in reg
    sw = pathlib.Path("static/js/kiosk-sw.js").read_text(encoding="utf-8")
    assert "url.pathname.startsWith('/static/')" in sw


# ------------------------------------------------------------------------------------------------------------------------------------ formulario de persona (Fase 1A, pieza 5)
def test_person_form_groups_and_columns_are_in_the_base_the_guide_and_the_standards():
    """Componente nuevo `.gw-form-group` / `.gw-fields-row`: en design-system.css, en la guía visual y en ESTANDARES_VISUALES.md; solo tokens (sin colores sueltos), con el objetivo táctil de 44 px,
    el color y el fondo heredados (así sirve en una pantalla clara u oscura: los pares de contraste son los de superficie y texto ya probados) y sin animación con movimiento reducido."""
    standards = pathlib.Path("docs/ux/ESTANDARES_VISUALES.md").read_text(encoding="utf-8")
    for cls in ("gw-form-group", "gw-form-group__summary", "gw-form-group__body", "gw-fields-row"):
        assert f".{cls}" in CSS and cls in GUIDE and cls in standards, cls
    block = CSS[CSS.index("/* ============================================================ Grupos plegables"):CSS.index("/* ============================================================ Recorrido de primera vez")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", block, flags=re.S)), "nada de colores sueltos: solo --gw-*"
    assert "var(--gw-tap)" in block and "prefers-reduced-motion" in block, "44 px, movimiento reducido"
    # sin desbordes: columnas minmax(0,1fr), hijos con min-width:0, border-box dentro del grupo y una columna en ancho de celular
    assert re.search(r"\.gw-fields-row \{[^}]*grid-template-columns: minmax\(0, 1fr\)", block)
    for n in (2, 3, 4):
        assert f"repeat({n}, minmax(0, 1fr))" in block
    assert re.search(r"\.gw-fields-row > \* \{ min-width: 0", block)
    assert re.search(r"\.gw-form-group \*[^{]*\{ box-sizing: border-box", block)
    assert re.search(r"@media \(max-width: 480px\)[^}]*\{[^}]*\.gw-fields-row--2[^}]*grid-template-columns: minmax\(0, 1fr\)", block)
    assert "background" not in re.sub(r"/\*.*?\*/", "", block, flags=re.S), "sin fondo propio: hereda de la pantalla"


# ------------------------------------------------------------------------------------------------------------------------------------ piezas de puerta (Fase 1.7, Ola 0)
DOOR_BLOCK = CSS[CSS.index("Fase 1.7, Ola 0"):]
DOOR_CLASSES = ("gw-btn--xl", "gw-search--hero", "gw-search__scan", "gw-search__field", "gw-search__icon", "gw-verdict", "gw-verdict__icon", "gw-verdict__title", "gw-verdict--ok", "gw-verdict--warn", "gw-verdict--err", "gw-verdict--door",
                "gw-person", "gw-person__name", "gw-person__meta", "gw-person__status", "gw-person__actions", "gw-person__photo", "gw-stat", "gw-stat__value", "gw-stat__label", "gw-stats-row", "gw-tile--hero", "gw-segment", "gw-segment__opt",
                "gw-conn", "gw-conn--warn", "gw-conn--err", "gw-split", "gw-split__main", "gw-split__aside", "gw-empty--hero", "gw-keypad", "gw-keypad__display", "gw-keypad__key", "gw-keypad__key--clear", "gw-keypad__key--ok")
DOOR_ICONS = {"scan", "wifi", "backspace", "check-lg", "id-card", "clock", "arrow-in", "arrow-out"}


def test_door_tokens_are_declared_and_big_enough():
    assert LIGHT["--gw-tap-lg"] == "64px"
    assert float(LIGHT["--gw-fs-door"].replace("rem", "")) * 16 == 24


def test_door_components_exist_in_the_base_the_guide_and_the_standards():
    standards = pathlib.Path("docs/ux/ESTANDARES_VISUALES.md").read_text(encoding="utf-8")
    for cls in DOOR_CLASSES:
        assert f".{cls}" in CSS, cls
        assert cls in GUIDE, f"la guía muestra {cls}"
    for cls in ("gw-btn--xl", "gw-search--hero", "gw-verdict", "gw-person", "gw-stat", "gw-stats-row", "gw-tile--hero", "gw-segment", "gw-conn", "gw-split", "gw-empty--hero", "gw-keypad", "--gw-tap-lg", "--gw-fs-door"):
        assert cls in standards, f"los estándares mencionan {cls}"
    assert 'id="puerta"' in GUIDE


def test_door_block_uses_only_tokens_and_no_loose_colors_or_sizes():
    block = re.sub(r"/\*.*?\*/", "", DOOR_BLOCK, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", block), "solo tokens --gw-*"
    assert "prefers-color-scheme" not in block
    for m in re.finditer(r"font-size:\s*([\d.]+)(px|rem)", block):
        raise AssertionError(f"tamaño de texto suelto: {m.group(0)}; usar --gw-fs-*")


def test_door_touch_targets_are_64px_and_keys_72px():
    for sel in (".gw-btn--xl", ".gw-search__scan"):
        assert "var(--gw-tap-lg)" in _rule(sel), sel
    assert "var(--gw-tap-lg)" in _rule(".gw-search--hero .gw-input") and "var(--gw-tap-lg)" in _rule(".gw-keypad__display")
    key = _rule(".gw-keypad__key")
    assert "calc(var(--gw-tap-lg) + var(--gw-sp-2))" in key and "touch-action: manipulation" in key
    assert "var(--gw-tap)" in _rule(".gw-segment__opt") and "var(--gw-tap-lg)" in CSS[CSS.index(".gw-segment--lg .gw-segment__opt {"):]
    assert "var(--gw-fs-door)" in _rule(".gw-verdict__title") and "var(--gw-fs-xl)" in _rule(".gw-btn--xl")


def test_door_states_use_the_verified_state_pairs_and_never_only_color():
    pairs = {(fg, bg) for fg, bg, _ in TEXT_PAIRS}
    for comp, selector in (("verdict", ".gw-verdict--{s}"), ("stat", ".gw-stat--{s}"), ("conn", ".gw-conn--{s}")):
        for state in ("ok", "warn", "err"):
            if comp == "conn" and state == "ok":
                continue
            rule = _rule(selector.format(s=state))
            assert f"background: var(--gw-{state}-bg)" in rule and f"color: var(--gw-{state}-text)" in rule and f"border-color: var(--gw-{state}-line)" in rule, (comp, state)
            assert (f"--gw-{state}-text", f"--gw-{state}-bg") in pairs
    assert "var(--gw-ok-bg)" in _rule(".gw-conn") and "var(--gw-ok-text)" in _rule(".gw-conn")
    assert "var(--gw-ok-bg)" in _rule(".gw-keypad__key--ok") and "var(--gw-err-bg)" in _rule(".gw-keypad__key--clear")
    # el segmento elegido: texto azul marino sobre el dorado (par verificado) y además un visto, no solo color
    sel = _rule('.gw-segment__opt[aria-pressed="true"], .gw-segment__opt[aria-checked="true"], .gw-segment__opt[aria-current="true"]')
    assert "var(--gw-gold-grad)" in sel and "var(--gw-on-gold)" in sel and '.gw-segment__opt[aria-pressed="true"]::before' in CSS
    # la guía los muestra siempre con ícono y texto
    for cls in ("gw-verdict__icon", "gw-stat__icon"):
        assert re.search(rf'<svg class="gw-icon {cls}"', GUIDE), cls


def test_door_has_reduced_motion_touch_and_forced_colors_support():
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.gw-verdict \{ animation: none; \}", DOOR_BLOCK)
    assert "@media (pointer: coarse)" in DOOR_BLOCK and "@media (forced-colors: active)" in DOOR_BLOCK
    assert "minmax(0, 1fr)" in _rule(".gw-stats-row") and "repeat(3," in _rule(".gw-stats-row"), "tres cifras por fila, también en celular"
    assert re.search(r"@media \(max-width: 520px\) \{ \.gw-tile--hero \{ grid-column: auto", CSS), "en una columna el mosaico hero no abre columnas nuevas"
    assert re.search(r"@media \(min-width: 960px\)[^}]*\{[^}]*\.gw-split \{ grid-template-columns: minmax\(0, 1fr\) minmax\(18rem", DOOR_BLOCK), "dos paneles solo en escritorio"


def test_door_icons_are_in_the_sprite_and_do_not_change_existing_rules():
    ids = set(re.findall(r'<symbol id="i-([\w-]+)"', SPRITE))
    assert DOOR_ICONS <= ids
    # nada anterior cambió: el botón, el buscador y el estado base siguen con sus valores
    assert "min-height: var(--gw-tap)" in _rule(".gw-btn") and "font-size: var(--gw-fs-xl)" in _rule(".gw-state__title")
    assert "calc(var(--gw-tap) + var(--gw-sp-2))" in _rule(".gw-search .gw-input")


def test_frozen_public_pages_do_not_load_the_door_pieces():
    for name in ("form_public.html", "digital_badge.html", "certificate_public.html", "roulette_display.html"):
        p = pathlib.Path("templates", name)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            assert "design-system.css" not in text and not re.search(r"gw-(verdict|person|keypad|stat|segment)\b", text), name


def test_m8_guide_chip_is_a_pill_like_the_step_chips_and_words_do_not_break():
    movil = CSS.split("Pasos 1·2·3 + «Guía» = UNA fila de 4 chips")[1].split("Menú ☰ flotante")[0]
    assert "li.gw-steps__guide" in movil and "var(--gw-radius-pill)" in movil and "var(--gw-border-strong)" in movil
    assert "overflow-wrap: normal" in movil and "overflow-wrap: anywhere" not in movil
    assert 'content: "Guía"' in movil


def test_m8_clear_search_component_exists_and_uses_the_sprite_trash_icon():
    assert ".gw-search__clear--in" in CSS and ".gw-clearable" in CSS and ".gw-input--clearable" in CSS
    assert 'id="i-trash"' in SPRITE
    assert "#i-trash" in JS and "Vaciar búsqueda" in JS and "data-gw-clear" in JS

