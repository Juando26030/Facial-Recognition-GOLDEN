"""Pedidos del 6-nov-2026 (rama ux/fase-1-8-pedidos). Pruebas de código fuente: no necesitan base de datos."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_excel_de_inscritos_distingue_si_la_persona_ya_estaba_en_la_base():
    forms = read("app/routers/forms.py")
    assert "Persona en la base antes de inscribirse" in forms and "formsvc.known_before" in forms
    assert '"En la base del evento"' not in forms          # la columna vieja medía otra cosa (si la inscripción ya se pasó a la base)
    svc = read("app/formsvc.py")
    assert "def known_before" in svc and "def sub_person_id" in svc and '"autoregistro"' in svc


def test_origen_solo_para_el_personal():
    stats, an, fs = read("app/routers/stats.py"), read("app/routers/analytics.py"), read("app/form_stats.py")
    assert "def is_staff_view" in stats and 'v[0] != "origin"' in stats and "staff_view" in stats
    assert "with_origin" in an and "_origin_kpis" in an and "is_staff_view(staff)" in an
    assert "with_origin" in fs
    links, client = read("app/routers/stats_links.py"), read("app/routers/form_client.py")
    assert "registro_dashboard(db, event)" in links and "with_origin" not in links          # el enlace público nunca lo recibe
    assert "form_stats.build(db, form, False)" in client                                      # el cliente del formulario tampoco
    assert "data_for(db, event, variable)" in links                                           # sin staff_view → «Origen de carga» no es válida para enlaces públicos


def test_aplicar_a_todos_los_textos_copia_todo_el_aspecto():
    ed = read("templates/badge_editor.html")
    for key in ("font_family", "font_size", "font_color", "font_weight", "align"):
        assert f"{key}: el.{key}" in ed
    assert "text_case" in ed and "p_case_all" in ed


def test_paginacion_20_con_selector_y_sin_parametro_del_evento():
    pager = read("static/js/gw-pager.js")
    assert "DEFAULT = 20" in pager and "pageSizeSelect" in pager and "pagerBar" in pager and "localStorage" in pager
    assert "pageSize('registro')" in read("static/js/directory.js")
    params = read("templates/kiosk_parametros.html")
    assert "directoryPageSize" not in params and "key: 'page'" not in params
    assert "ANSWERS_DEFAULT_PAGE_SIZE = 20" in read("app/formlib.py")
    for rel in ("templates/kiosk_registro.html", "templates/kiosk_usuarios.html", "templates/kiosk_formulario_editor.html"):
        assert "js/gw-pager.js" in read(rel), rel


def test_usuarios_del_evento_excel_borrado_en_bloque_y_clave_cedula():
    ev = read("app/routers/events.py")
    assert "staff-users/template" in ev and "staff-users/import" in ev and "staff-users/purge-temporary" in ev
    assert "or data.username" in ev and "password: Optional[str] = None" in ev
    assert "use_username" in read("app/routers/staff.py")
    page, js = read("templates/kiosk_usuarios.html"), read("static/js/usuarios.js")
    assert 'id="purgeTempBtn"' in page and "gw-btn--danger" in page and 'id="importStaffForm"' in page and "Descargar la plantilla" in page
    assert 'id="uPassword"' not in page and "data-gw-pwcheck" not in page
    assert "purge-temporary" in js and "staff-users/import" in js and "tempUsersPager" in js and "use_username" in js


def test_logos_tamano_global_y_por_evento():
    assert "golden_logo_height" in read("app/logosize.py")
    main = read("app/main.py")
    assert "def golden_logo_attrs" in main and "--gw-logo-h" in main
    assert "var(--gw-logo-h, 50px)" in read("static/css/style.css")
    assert "golden-logo-height" in read("app/routers/print_stations.py") and 'require_role("super_admin")' in read("app/routers/print_stations.py")
    cfg = read("templates/configuracion.html")
    assert 'id="goldenLogoH"' in cfg and 'staff_role == "super_admin"' in cfg
    params = read("templates/kiosk_parametros.html")
    assert 'id="logoH"' in params and "{% if event.logo_mode != 'custom' %}hidden{% endif %}" not in params


def test_papelera_en_todos_los_buscadores_dentro_del_campo():
    """Una sola papelera por campo (la de gw-ui.js): antes convivía con otra de gw-clear.js y al escribir se veían dos."""
    js, css = read("static/js/gw-ui.js"), read("static/css/design-system.css")
    assert not (ROOT / "static/js/gw-clear.js").exists() and "gw-clear.js" not in read("templates/_gw_head.html")
    assert "gw-clearbtn" not in css and "gw-clearbtn" not in js
    assert "data-gw-clear-btn" in js and "gw-search__clear--proxy" in js
    assert re.search(r"\.gw-search__clear--in \.gw-icon \{ width: 1\.5rem", css)
    assert "right: var(--gw-sp-4)" in css
    for rel, ident in (("templates/kiosk_registro.html", "searchNombre"), ("templates/_gw_buscador.html", "searchCedula"), ("templates/kiosk_areas.html", "nameSearch"),
                       ("templates/kiosk_ruleta.html", "pickerSearch"), ("templates/calendario.html", "noteTargetSearch")):
        assert re.search(rf'id="{ident}"[^>]*data-gw-clearable', read(rel)), (rel, ident)


def test_eventos_usa_la_misma_fila_que_clientes():
    ev = read("templates/eventos.html")
    assert "gw-event-card" in ev and "p-cli__acts" in ev and "css/p-clientes.css" in ev and "gw-event-list" in ev
    assert "ev-card__row" not in ev
