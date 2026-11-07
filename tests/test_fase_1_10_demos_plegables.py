"""Fase 1.10 (6-nov-2026): «deshabilitar demos automáticas» por CUENTA y bloques plegables en las pantallas de configuración.
Pruebas de código fuente (sin base de datos); el comportamiento se verificó en navegador (ver docs/historial.md)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_la_preferencia_de_demos_vive_en_la_cuenta():
    assert "tours_auto_off = Column(Boolean" in read("app/models.py")
    mig = read("alembic/versions/0085_tours_auto_off.py")
    assert 'revision = "0085_tours_auto_off"' in mig and len("0085_tours_auto_off") <= 32
    assert 'down_revision = "0084_stats_links"' in mig and "ADD COLUMN IF NOT EXISTS tours_auto_off" in mig
    au = read("app/routers/auth.py")
    assert 'request.session["tours_off"] = bool(staff.tours_auto_off)' in au          # se copia a la sesión al ingresar (cualquier dispositivo)
    assert '@router.put("/api/me/tours-auto-off")' in au and "Depends(get_current_staff)" in au
    assert re.search(r"def set_tours_auto_off\(", au)                                   # endpoint `def`, no `async def`


def test_las_demos_automaticas_respetan_la_preferencia_y_la_guia_manual_sigue():
    js = read("static/js/gw-ui.js")
    assert "if (auto && !window.GW_TOURS_OFF)" in js                                    # el arranque automático se salta
    assert "startTour(el.getAttribute('data-gw-tour-restart'), { force: true })" in js  # el botón «Guía» siempre funciona
    assert "/api/me/tours-auto-off" in js and "data-gw-tour-off" in js
    assert "window.GW_TOURS_OFF" in read("templates/_gw_head.html")
    cfg = read("templates/configuracion.html")
    assert 'id="toursOff"' in cfg and "Deshabilitar demos automáticas" in cfg and "tours_off" in cfg


def test_los_bloques_de_configuracion_se_pliegan_sin_mover_nodos():
    js = read("static/js/gw-ui.js")
    assert "function foldInit" in js and "data-gw-fold-btn" in js and "data-gw-fold-all" in js and "foldInit();" in js
    assert "wrapChild" not in js and "appendChild(item" not in js                         # solo clase gw-is-folded: ids y selectores no cambian
    css = read("static/css/design-system.css")
    assert ".gw-is-folded > :not(.gw-fold__head) { display: none !important; }" in css
    # «Formulario de persona» ahora tiene cabecera plegable como «Campos de la persona»
    assert '<div class="gw-item-head"><h4 id="personFormTitle">Formulario de persona</h4></div>' in read("templates/kiosk_parametros.html")


def test_fase_1_11_todo_en_una_columna_y_plegar_todo_en_las_opciones_del_evento():
    # nada de secciones lado a lado en configuración (Parámetros, Configuración, editor de formularios, ruleta)
    assert ".gw-parametros .gw-tabpanel { display: grid" not in read("static/css/parametros.css")
    assert ".gw-config__wrap .gw-tabpanel { display: grid" not in read("static/css/p-configuracion.css")
    assert "#pane-config.active { display: grid" not in read("static/css/gw-editor-form.css")
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .gw-ruleta-split__preview" not in read("static/css/gw-ruleta.css")
    # «Plegar todo / Desplegar todo» en cada opción del evento (menos Registro)
    for t in ("kiosk_estadisticas", "kiosk_roster", "kiosk_formularios", "kiosk_ruleta", "kiosk_usuarios", "kiosk_documentos", "kiosk_legalizaciones", "kiosk_areas", "kiosk_inventario",
              "kiosk_certificados", "badge_editor", "kiosk_formulario_editor", "kiosk_parametros"):
        assert '<main class="golden-main" data-gw-fold' in read(f"templates/{t}.html"), t
    assert "data-gw-fold" not in read("templates/kiosk_registro.html")
    js = read("static/js/gw-ui.js")
    assert "main[data-gw-fold]" in js and "function foldOpenAll" in js and "foldOpenAll();" in js          # las guías abren todo antes de señalar


def test_fase_1_11_cedula_con_asterisco_y_lista_de_eventos():
    d = read("static/js/directory.js")
    assert 'for="editModalCedulaField">${esc(label)}<span class="gw-req"' in d
    for rel in ("static/js/gw-clientes.js", "templates/eventos.html"):
        assert 'class="p-cli__nm"' in read(rel), rel
    css = read("static/css/p-clientes.css")
    assert ".gw-event-card .p-cli__nm {" in css and ".gw-event-card .p-cli__rep { flex: 0 0 6.75rem" in css
    assert ".p-cli__coord .ev-who .p-cli__pfx { display: inline;" in css                                    # «Comercial: …» / «Coordinador: …»


def test_fase_1_12_celular_ordenado_y_barra_de_plegar_en_el_mismo_sitio():
    css = read("static/css/p-clientes.css")
    assert "@media (max-width: 900px) {" in css and ".p-cli__acts .p-cli__status, .p-cli__more { grid-column: auto; }" in css      # estado y «Más acciones» lado a lado
    for rel in ("static/js/gw-clientes.js", "templates/eventos.html"):
        t = read(rel)
        assert "Comercial: </span>" in t and "Coordinador: </span>" in t and "Fecha: </span>" in t and "Código: </span>" in t, rel
    assert "commercial_name" in read("static/js/gw-clientes.js")
    js = read("static/js/gw-ui.js")
    assert "outsideDetails(page, '.gw-steps')" in js and "ref.parentNode.insertBefore(bar, ref.nextSibling)" in js          # debajo del título y de la guía de pasos
    assert "h !== scope && scope.contains(h)" in js                                                                        # las pestañas inactivas también llevan su barra
    assert ":scope > h2.gw-card__title" in js                                                                              # tarjetas con título directo
    assert "justify-content: flex-start; width: 100%" in read("static/css/design-system.css")
