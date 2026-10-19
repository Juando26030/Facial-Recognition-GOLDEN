"""Fase 1 de UX (rama ux/fase1-visual): sistema visual, menú por ciclo, Parámetros en pestañas, íconos SVG. Solo presentación: las pantallas de la puerta y de contingencia no se tocan."""
import re

import pytest

from tests.conftest import login

CSS = open("static/css/ux1.css", encoding="utf-8").read()


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4      # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _token(name):
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS).group(1)


def _event(client, factory, role="coordinador", **kw):
    factory.staff(role, "u1")
    ev = factory.event("creado", **kw)
    login(client, "u1")
    return ev


# ------------------------------------------------------------------------------------------------------------------------------------ tokens
@pytest.mark.parametrize("fg", ["ux-ink", "ux-ink-2", "ux-danger", "ux-warn", "ux-ok", "ux-link", "ux-gold-ink"])
def test_text_colors_reach_4_5_to_1_on_white_and_on_the_page_background(fg):
    assert _ratio(_token(fg), "#ffffff") >= 4.5 and _ratio(_token(fg), _token("ux-bg")) >= 4.5, fg


def test_the_gold_is_only_a_background_with_dark_text():
    assert _ratio(_token("ux-gold"), "#111111") >= 7 and _ratio(_token("ux-gold"), "#ffffff") < 3          # por eso nunca se usa como color de texto


def test_the_type_scale_has_body_16_over_24_and_help_never_below_14():
    assert "--ux-fs-body: 1rem;" in CSS and "--ux-lh-body: 1.5rem;" in CSS and "--ux-fs-label: 0.875rem;" in CSS
    sizes = set(re.findall(r"--ux-fs-[a-z]+:\s*([0-9.]+)rem", CSS))
    assert sizes == {"2", "1.5", "1.25", "1", "0.875"}                                                      # 5 tamaños: 32 · 24 · 20 · 16 · 14 px
    for grey in ("#777", "#888", "#999", "#aaa", "#bbb", "#b26a00"):
        assert f'[style*="color:{grey}"]' in CSS or grey == "#b26a00" and 'color:#b26a00' in CSS             # los grises que no llegaban a 4,5:1 se remplazan aunque vengan con estilo en la plantilla


def test_touch_targets_are_24_px_minimum_and_44_px_for_the_main_controls():
    assert "width: 24px !important; height: 24px !important" in CSS and "--ux-target: 44px" in CSS and "min-height: var(--ux-target)" in CSS and ":focus-visible" in CSS


# ------------------------------------------------------------------------------------------------------------------------------------ íconos
def test_every_icon_in_the_macro_renders_an_aria_hidden_svg_and_menus_use_no_emoji():
    from app.main import templates
    macro = templates.get_template("_icons.html").module.icon
    for name in ("camera", "id", "door", "box", "paperclip", "ticket", "form", "wheel", "chart", "users", "folder", "receipt", "gear", "award", "download", "mail", "building", "calendar", "pulse", "check", "lock", "list"):
        svg = str(macro(name))
        assert svg.startswith("<svg") and 'aria-hidden="true"' in svg and any(shape in svg for shape in ("<path", "<circle", "<rect")), name
    assert "<svg" in str(macro("no-existe"))                                                                  # un nombre desconocido no rompe la página


# ------------------------------------------------------------------------------------------------------------------------------------ menú del evento
def test_the_event_menu_is_ordered_by_the_event_cycle_with_first_steps(client, factory, db):
    ev = _event(client, factory, "coordinador")
    page = client.get(f"/kiosk/{ev.id}").text
    order = [page.index(t) for t in ("1 · Configurar", "2 · Cargar personas", "3 · Invitar", "4 · Puerta", "5 · Después")]
    assert order == sorted(order) and "Primeros pasos" in page and 'class="ux1 has-sidebar"' in page
    assert page.index("Parámetros del Evento") < page.index("Adjuntar Base de Datos") < page.index("Invitaciones y aceptación") < page.index(">Registro<") < page.index("Estadísticas")
    assert "mode-icon\">📸" not in page and "mode-icon\">🪪" not in page and '<svg class="ux-icon"' in page


def test_first_steps_reflect_what_the_event_already_has(client, factory, db):
    ev = _event(client, factory, "coordinador")
    page = client.get(f"/kiosk/{ev.id}").text
    assert page.count('<li class="done">') == 0
    ev.facial_enabled, ev.roster_uploaded, ev.aceptar_enabled, ev.status = True, True, True, "en_proceso"
    db.commit()
    page = client.get(f"/kiosk/{ev.id}").text
    assert page.count('<li class="done">') == 4
    ev.facial_enabled, ev.biometrics_locked = False, True                                                      # «No usa rostro» también cuenta como decidido
    db.commit()
    assert client.get(f"/kiosk/{ev.id}").text.count('<li class="done">') == 4


def test_the_menu_keeps_every_link_and_each_role_sees_the_same_cards_as_before(client, factory, db):
    ev = _event(client, factory, "admin", areas_enabled=True, inventory_enabled=True, certificates_enabled=True)
    page = client.get(f"/kiosk/{ev.id}").text
    for path in ("registro", "areas", "inventario", "roster", "escarapela", "formularios", "ruleta", "estadisticas", "usuarios", "certificado", "documentos", "legalizaciones", "parametros"):
        assert f'href="/kiosk/{ev.id}/{path}"' in page, path
    client.cookies.clear()
    factory.staff("comercial", "u2")
    login(client, "u2")
    page = client.get(f"/kiosk/{ev.id}").text
    for hidden in ("roster", "escarapela", "parametros", "areas", "inventario"):
        assert f'href="/kiosk/{ev.id}/{hidden}"' not in page, hidden                                           # la comercial sigue sin verlas
    assert "Primeros pasos" not in page and f'href="/kiosk/{ev.id}/estadisticas"' in page


# ------------------------------------------------------------------------------------------------------------------------------------ Parámetros en pestañas
def test_parameters_come_in_six_tabs_and_the_original_save_buttons_stay_for_the_one_save_per_tab(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "su")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    for label in ("General", "Reconocimiento facial", "Invitaciones", "Escarapelas y certificados", "Campos del formulario", "Privacidad"):
        assert f"label: '{label}'" in page, label
    for tab in ("general", "facial", "escarapelas", "campos", "privacidad"):
        assert f'data-ux-tab="{tab}"' in page, tab
    for button in ("ccSave", "pcSave", "saveCategoriesBtn", "saveParamsBtn"):                                 # los guardados de siempre (mismos endpoints) siguen ahí: el Guardar de la pestaña los dispara
        assert f'id="{button}"' in page, button
    assert "Cambios sin guardar" in page and "beforeunload" in page and "setAttribute('role', 'tablist')" in page


def test_the_hash_links_from_the_menu_land_on_real_tabs(client, factory, db):
    ev = _event(client, factory, "coordinador")
    menu = client.get(f"/kiosk/{ev.id}").text
    anchors = set(re.findall(r"/parametros#(\w+)", menu))
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert anchors == {"facial", "invitaciones"} and all(f"id: '{a}'" in page for a in anchors)


def test_privacy_actions_are_red_zone_and_not_primary_and_keep_their_confirmations(client, factory, db):
    factory.staff("admin", "ad")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "ad")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "ux-privacy-zone" in page and 'id="privAll"' in page and 'id="privEvent"' in page and "golden-btn-primary\" style=\"width:auto;\">Suprimir" not in page
    assert "#privAll, body.ux1 #privEvent" in CSS and "var(--ux-danger)" in CSS
    js = open("static/js/biometric-purge.js", encoding="utf-8").read()
    assert "showPrompt" in js and "confirm_name" in js                                                         # el borrado del evento sigue pidiendo escribir su nombre
    assert "showConfirm(msg.replace" in page                                                                   # y suprimir/revocar siguen pidiendo confirmación


# ------------------------------------------------------------------------------------------------------------------------------------ títulos y lo que NO se toca
def test_titles_say_the_task(client, factory, db):
    ev = _event(client, factory, "coordinador", facial_enabled=True)
    assert "Registro <span class=\"gradient-text\">y acceso</span>" in client.get(f"/kiosk/{ev.id}/registro").text
    assert "Elige un evento para entrar a trabajar en él" in client.get("/eventos").text and 'aria-label="Buscar eventos por nombre o código"' in client.get("/eventos").text


def test_the_door_the_registration_and_the_public_pages_are_not_restyled(client, factory, db):
    ev = _event(client, factory, "coordinador", facial_enabled=True, face_door_enabled=True)
    door = client.get(f"/kiosk/{ev.id}/rostro").text
    reg = client.get(f"/kiosk/{ev.id}/registro").text
    assert "ux1" not in door and "ux1.css" not in door and "ux1" not in reg.split("<body")[1].split(">")[0] and "ux1.css" not in reg
    client.cookies.clear()
    assert "ux1.css" not in client.get(f"/aceptar/{ev.event_code}").text


def test_only_presentation_files_changed_in_this_branch():
    import subprocess
    out = (subprocess.run(["git", "diff", "--name-only", "3509cc3"], capture_output=True, text=True).stdout
           + subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout).split()
    if subprocess.run(["git", "cat-file", "-e", "3509cc3"], capture_output=True).returncode != 0:
        pytest.skip("sin historial git para comparar")
    allowed = ("templates/", "static/", "tests/", "docs/")
    assert [f for f in out if not f.startswith(allowed)] == [], "la rama de UX no debe tocar código de la aplicación (app/, alembic/, deploy/)"


# ------------------------------------------------------------------------------------------------------------------------------------ fuentes propias y guardado honesto
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "fonts.bunny.net", "cdnjs.cloudflare.com/ajax/libs/font")
# Pantallas que todavía eligen entre ~40 tipografías de Google para escarapelas, certificados, formularios y ruleta (decisión pendiente del dueño: alojarlas o reducir la lista). Nada nuevo puede sumarse aquí.
LEGACY_GOOGLE_FONTS = {"templates/badge_editor.html", "templates/badge_print.html", "templates/certificate_public.html", "templates/digital_badge.html", "templates/form_public.html",
                       "templates/kiosk_certificados.html", "templates/kiosk_formulario_editor.html", "templates/kiosk_ruleta_visual.html", "templates/roulette_display.html",
                       "static/js/roulette-render.js", "static/js/theme.js"}


def test_no_page_asks_a_third_party_for_fonts_except_the_listed_legacy_pickers():
    import pathlib
    offenders = set()
    for root in ("templates", "static/css", "static/js"):
        for f in pathlib.Path(root).rglob("*"):
            if f.suffix in (".html", ".css", ".js") and any(h in f.read_text(encoding="utf-8", errors="ignore") for h in FONT_HOSTS):
                offenders.add(f.as_posix())
    assert offenders - LEGACY_GOOGLE_FONTS == set(), "una página nueva pide fuentes a un tercero: aloja la fuente en static/fonts"
    for page in ("templates/aceptar.html", "templates/_ux_head.html", "templates/kiosk_select.html", "templates/kiosk_parametros.html", "templates/eventos.html"):
        assert page not in offenders, page


def test_agrandir_stays_the_default_font_everywhere_and_the_redesign_imposes_no_other(client, factory, db):
    css = open("static/css/ux1.css", encoding="utf-8").read()
    assert "--ux-font: var(--font-body" in css and "--ux-font-heading: var(--font-heading-secondary" in css and "Montserrat" not in css      # sigue lo que diga Configuración > Apariencia
    assert not __import__("pathlib").Path("static/css/montserrat.css").exists()
    own = open("static/css/agrandir.css", encoding="utf-8").read()
    assert own.count("@font-face") == 2 and "agrandir-thin.ttf" in own and "agrandir-regular.otf" in own
    for name in ("agrandir-thin.ttf", "agrandir-regular.otf"):
        assert client.get(f"/static/fonts/{name}").status_code == 200, name
    ev = _event(client, factory, "coordinador", facial_enabled=True, aceptar_enabled=True)
    menu = client.get(f"/kiosk/{ev.id}").text
    assert "css/style.css" in menu and "montserrat" not in menu.lower() and "fonts.g" not in menu
    client.cookies.clear()
    page = client.get(f"/aceptar/{ev.event_code}").text
    assert "css/agrandir.css" in page and "font-family:'Agrandir'" in page and "Montserrat" not in page and "fonts.g" not in page


def test_a_tab_is_marked_saved_only_when_the_real_save_finishes_ok(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "su")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "const runSave" in page and "saveWaiter" in page and "r.ok) dirty[g.id] = false; else" in page          # solo se limpia «sin guardar» con el éxito que avisa el guardado de siempre
    assert "No se guardó: " in page and "Los cambios siguen sin guardar." in page and "dirty[g.id] = false;\n                });" not in page


def test_text_under_18_px_uses_agrandir_regular_and_thin_is_kept_for_18_px_or_more():
    assert "--ux-weight-small: 600;" in CSS and "--ux-weight-large: 400;" in CSS and "body.ux1 { font-weight: var(--ux-weight-small); }" in CSS
    inputs = re.search(r"body\.ux1 input\[type=\"text\"\].*?\{(.*?)\}", CSS, re.S).group(1)
    assert "font-weight: var(--ux-weight-small)" in inputs                                          # los campos de formulario no heredan el peso: se pone aparte
    sizes = {name: float(v) * 16 for name, v in re.findall(r"--ux-fs-([a-z]+):\s*([0-9.]+)rem", CSS)}
    assert sizes["body"] == 16 and sizes["label"] == 14 and all(px >= 18 for name, px in sizes.items() if name not in ("body", "label"))      # lo que no es Regular (>= 18 px) son títulos
    agrandir = open("static/css/agrandir.css", encoding="utf-8").read()
    assert "font-weight: 100 500" in agrandir and "font-weight: 600 900" in agrandir and "agrandir-regular.otf" in agrandir.split("font-weight: 600 900")[0].rsplit("@font-face", 1)[1]


# ------------------------------------------------------------------------------------------------------------------------------------ ronda de revisión del dueño (17 oct)
def test_radios_and_checkboxes_align_with_the_first_line_of_their_text():
    rule = re.search(r'body\.ux1 label:has\(> input\[type="checkbox"\]\), body\.ux1 label:has\(> input\[type="radio"\]\) \{(.*?)\}', CSS, re.S).group(1)
    assert "align-items: flex-start !important" in rule and "align-items: center" not in rule and "padding: 10px 0" in rule      # 24 px de línea + 20 = 44 px de objetivo
    assert 'label:has(> input[type="radio"]) > input { margin: 0 !important; }' in CSS


def test_the_fixed_save_bar_never_covers_the_last_lines_or_buttons():
    assert ":root:has(body.ux1) { scroll-padding-bottom: 112px; }" in CSS and "body.ux1 .ux-panel > :nth-last-child(2) { margin-bottom: var(--ux-s6, 32px); }" in CSS
    assert "position: sticky; bottom: 0" in CSS


def test_the_six_tabs_stay_in_one_scrollable_row_and_the_active_one_is_centered(client, factory, db):
    tabs = re.search(r"body\.ux1 \.ux-tabs \{(.*?)\}", CSS, re.S).group(1)
    assert "flex-wrap: nowrap" in tabs and "overflow-x: auto" in tabs and "flex-wrap: wrap" not in tabs
    assert "flex: none; white-space: nowrap" in CSS
    factory.staff("super_admin", "su")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "su")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "function centerActive(id)" in page and "bar.scrollLeft +=" in page and "centerActive(id);" in page
    assert "fieldset > * { min-width: 0; }" in CSS and "grid-template-columns: minmax(0, 1fr)" in CSS            # a 375 px nada ensancha la página


def test_event_menu_has_no_loose_event_name_and_the_status_badge_is_14_px_with_enough_contrast(client, factory, db):
    ev = _event(client, factory, "coordinador")
    page = client.get(f"/kiosk/{ev.id}").text
    assert f"letter-spacing:2px; font-size:0.85rem;\">{ev.name}</span>" not in page and "¿Qué vas a hacer hoy?" in page
    assert "body.ux1 .status-pill { font-size: var(--ux-fs-label);" in CSS
    for state, bg, fg in (("creado", "#e3eefb", "ux-link"), ("en_proceso", "#e1f3e6", "ux-ok"), ("finalizado", "#e9eaf0", "ux-ink-2")):
        assert f"body.ux1 .status-{state} {{ background: {bg}; color: var(--{fg}); }}" in CSS
        assert _ratio(_token(fg), bg) >= 4.5, state


def test_the_repeated_card_heading_of_the_facial_tab_is_kept_only_for_screen_readers(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "su")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "Reconocimiento facial: paso guiado" in page                                                  # sigue en la página (lectores de pantalla y pruebas existentes)
    assert 'body.ux1 [data-ux-tab="facial"] > h4:first-child { position: absolute; width: 1px; height: 1px;' in CSS


# ------------------------------------------------------------------------------------------------------------------------------------ íconos del menú lateral en TODAS las pantallas
def _loads_icons_css(name, seen=()):
    """¿La plantilla carga static/css/icons.css, directamente o por una plantilla que incluye?"""
    import pathlib
    text = pathlib.Path("templates", name).read_text(encoding="utf-8")
    if "css/icons.css" in text:
        return True
    return any(_loads_icons_css(inc, seen + (name,)) for inc in re.findall(r'\{%\s*include\s+"([^"]+)"', text) if inc not in seen and pathlib.Path("templates", inc).exists())


def test_every_template_that_uses_icons_or_the_sidebar_loads_the_icon_css():
    import pathlib
    users = [f.name for f in sorted(pathlib.Path("templates").glob("*.html"))
             if f.name != "_icons.html" and re.search(r'_icons\.html|_sidebar\.html', f.read_text(encoding="utf-8"))]
    assert len(users) >= 15 and "configuracion.html" in users and "clientes.html" in users and "calendario.html" in users and "sistema.html" in users and "kiosk_select.html" in users
    assert [n for n in users if not _loads_icons_css(n)] == [], "una plantilla con íconos SVG no carga static/css/icons.css: los íconos se verían rellenos de negro"
    rule = open("static/css/icons.css", encoding="utf-8").read()
    assert ".ux-icon {" in rule and "fill: none" in rule and "stroke: currentColor" in rule


def test_the_icon_rules_are_not_in_the_redesign_stylesheet_and_it_is_not_spread_to_other_screens():
    import pathlib
    assert ".ux-icon {" not in CSS and ".ux-icon{" not in CSS                                         # la regla ya no vive aquí (solo un comentario que dice dónde está)
    redesigned = sorted(f.name for f in pathlib.Path("templates").glob("*.html") if f.name != "_ux_head.html" and re.search(r"_ux_head\.html|css/ux1\.css", f.read_text(encoding="utf-8")))
    assert redesigned == ["eventos.html", "kiosk_parametros.html", "kiosk_roster.html", "kiosk_select.html"]   # ux1.css pisa estilos: solo las pantallas ya revisadas


def test_non_redesigned_screens_get_the_icons_without_the_redesign(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado")
    login(client, "su")
    for path in ("/configuracion", "/clientes", "/calendario", "/sistema", f"/kiosk/{ev.id}/usuarios", f"/kiosk/{ev.id}/estadisticas"):
        page = client.get(path)
        assert page.status_code == 200 and "css/icons.css" in page.text and "ux1.css" not in page.text and 'class="ux-icon"' in page.text, path
