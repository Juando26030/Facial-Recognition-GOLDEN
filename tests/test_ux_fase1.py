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


def test_montserrat_is_served_from_our_own_static_files(client, factory, db):
    css = open("static/css/montserrat.css", encoding="utf-8").read()
    files = re.findall(r"url\('\.\./fonts/([\w.-]+\.woff2)'\)", css)
    assert len(files) == 3 and not any(h in css for h in FONT_HOSTS)
    for name in files:
        assert client.get(f"/static/fonts/{name}").status_code == 200, name
    ev = _event(client, factory, "coordinador", facial_enabled=True, aceptar_enabled=True)
    assert "css/montserrat.css" in client.get(f"/kiosk/{ev.id}").text and "fonts.g" not in client.get(f"/kiosk/{ev.id}").text
    ev.facial_enabled, ev.aceptar_enabled = True, True
    db.commit()
    client.cookies.clear()
    assert "css/montserrat.css" in client.get(f"/aceptar/{ev.event_code}").text and "fonts.g" not in client.get(f"/aceptar/{ev.event_code}").text


def test_a_tab_is_marked_saved_only_when_the_real_save_finishes_ok(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado", facial_enabled=True)
    login(client, "su")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "const runSave" in page and "saveWaiter" in page and "r.ok) dirty[g.id] = false; else" in page          # solo se limpia «sin guardar» con el éxito que avisa el guardado de siempre
    assert "No se guardó: " in page and "Los cambios siguen sin guardar." in page and "dirty[g.id] = false;\n                });" not in page
