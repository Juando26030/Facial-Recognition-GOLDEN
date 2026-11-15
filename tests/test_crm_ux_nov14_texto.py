"""CRM, 14-nov-2026 (revisión de Juan David): tareas desde «Mi día», buscador predictivo de cuentas, todo plegable y búsquedas que responden al escribir."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_mi_dia_tiene_boton_nueva_tarea_ligada_a_cuenta():
    assert 'id="dayNew"' in read("templates/crm_midia.html")
    assert "X.activityForm({ pick: true }" in read("static/js/crm_midia.js")
    common = read("static/js/crm_common.js")
    assert "Toda tarea va ligada a una cuenta" in common and "payload.account_id = Number(accPick.value)" in common


def test_buscador_predictivo_reemplaza_buscar_cuenta():
    for f in ("crm_cotizaciones.js", "crm_kanban.js", "crm_leads.js"):
        js = read(f"static/js/{f}")
        assert "accountPicker(" in js, f
        assert '"Buscar cuenta"' not in js and "Cuenta elegida" not in js, f
    live = read("static/js/crm_live.js")
    assert "function picker(" in live and "accountPicker" in live and "opportunityPicker" in live
    assert "js/crm_live.js" in read("templates/_crm_shell_bottom.html")
    assert ".crm-picker__list" in read("static/css/p-crm.css")


def test_todo_el_crm_es_plegable_y_busca_al_escribir():
    assert "\n<main class=\"golden-main\" data-gw-fold>\n" in read("templates/_crm_shell_top.html")          # la etiqueta real, no el comentario de arriba
    ui = read("static/js/gw-ui.js")
    assert "fold: { refresh: foldInit }" in ui and ":scope > .crm-card-head" in ui and "scope._gwBar" in ui
    assert "window.GW.fold.refresh()" in read("static/js/crm_fold.js")
    assert "form.crm-filters input[type='search']" in read("static/js/crm_live.js")
    for t in ("_crm_shell_bottom", "crm_cuenta", "crm_cuentas"):
        assert "js/crm_fold.js" in read(f"templates/{t}.html"), t
    for t in ("_crm_shell_top", "crm_cuenta", "crm_cuentas"):
        assert "\n<main class=\"golden-main\" data-gw-fold>\n" in read(f"templates/{t}.html"), t


def test_plantilla_del_pdf_muestra_cual_es_la_predeterminada():
    js = read("static/js/crm_cotizacion.js")
    assert "Usar la predeterminada (" in js and "Administrar plantillas" in js


def test_calendario_tiene_boton_grande_eventos_crm_solo_con_lo_de_cada_comercial():
    html = read("templates/calendario.html")
    assert 'id="calMode"' in html and 'data-mode="crm"' in html and "{% if crm_calendar %}" in html
    assert "/api/crm/calendar" in html and "function setCalMode" in html and "modo=crm" in html
    main = read("app/main.py")
    assert '"crm_calendar": crm_enabled() and bool({"comercial", "admin", "super_admin"} & roles)' in main
    router = read("app/routers/crm_today.py")
    assert '@router.get("/calendar")' in router and "owner = staff.id" in router          # el comercial solo ve lo suyo
    assert ".cal-mode" in read("static/css/gw-eventos.css")


def test_staff_tiene_buscador_y_el_calendario_deja_elegir_entre_tarea_y_cuenta():
    assert 'id="staffSearch"' in read("templates/staff.html") and "searchTerm" in read("static/js/gw-staff.js")
    html = read("templates/calendario.html")
    assert "function openCrmItem" in html and "Ir a la cuenta" in html and "Abrir y editar la tarea" in html and "data-crm-new" in html
    assert 'id="calModeHint"' in html and "MODE_HINT" in html          # el texto de «qué estoy viendo» está en Eventos Y en CRM
    assert '@router.get("/activities/{activity_id}")' in read("app/routers/crm_pipeline.py")
    midia = read("static/js/crm_midia.js")
    assert "function categoryBar" in midia and "crm-day-group" in midia and "byMonth" in midia
