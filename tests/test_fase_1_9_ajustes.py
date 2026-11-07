"""Fase 1.9 (6-nov-2026): iconos en las cifras de texto de las estadísticas, Estadísticas oculto al digitador, diseñador del formulario de persona con lienzo/arrastre/vista previa y una sola papelera por buscador.
Pruebas de código fuente (sin base de datos): la lógica pura del diseñador se prueba en Node (tests/js/person_form_check.js)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_las_cifras_de_texto_de_las_estadisticas_llevan_icono():
    an, rt = read("app/analytics.py"), read("app/routers/analytics.py")
    assert 'icon: str = ""' in an and '"icon": icon' in an
    for label, icon in (("Primer registro", "flag-start"), ("Último registro", "flag-end"), ("Hora pico", "peak"), ("Ritmo promedio", "gauge"),
                        ("Vienen del Excel (base)", "sheet"), ("Nuevos digitados a mano", "hand"), ("Llegaron por formulario", "form")):
        assert re.search(rf'kpi\("{re.escape(label)}".*icon="{icon}"', rt), (label, icon)
    sprite = read("static/img/icons.svg")
    for name in ("sheet", "hand", "flag-start", "flag-end", "peak", "gauge", "form", "help"):
        assert f'id="i-{name}"' in sprite, name
    # los símbolos nuevos quedan DENTRO del sprite (no en el comentario del encabezado)
    assert sprite.index('id="i-sheet"') > sprite.index("-->")
    js = read("static/js/analytics-dashboard.js")
    assert "ad-kpi__icon" in js and "k.icon" in js and ".ad-kpi__icon--sheet" in js
    assert "icon(" in read("static/js/form-stats.js") and ".fs-kpi__icon" in read("static/css/form-stats.css")


def test_el_digitador_no_ve_la_puerta_de_estadisticas():
    sel = read("templates/kiosk_select.html")
    tile = sel.index('"/kiosk/%s/estadisticas"')
    assert 'staff_role != "digitador"' in sel[tile - 400:tile]
    assert 'exclude_roles=["digitador"]' in read("app/main.py")          # el servidor sigue negándolo igual


def test_el_disenador_de_persona_es_un_lienzo_como_el_de_formularios_web():
    js = read("static/js/person-form-designer.js")
    for token in ("draggable", "dragstart", "drop", "gw-pf-card", "gw-pf-gap", "pfPreview", "pfProps", "dropAt", "moveKey", "rowsOf", "Previsualizar"):
        assert token in js, token
    assert "<table" not in js and "'tbody'" not in js and "Junto al anterior" not in js          # se fue la tabla con «junto al anterior»
    css = read("static/css/parametros.css")
    for cls in (".gw-pf-grid", ".gw-pf-card", ".gw-pf-row--4", ".gw-pf-gap--over", ".gw-pf-props"):
        assert cls in css, cls
    assert "register({ key: 'personform'" in js and "id: 'pfSave'" in js        # el guardado global sigue igual


def test_una_sola_papelera_por_buscador_mas_grande_y_con_margen():
    css, ui = read("static/css/design-system.css"), read("static/js/gw-ui.js")
    assert not (ROOT / "static/js/gw-clear.js").exists() and "gw-clear.js" not in read("templates/_gw_head.html")
    assert "right: var(--gw-sp-4)" in css and re.search(r"\.gw-search__clear--in \.gw-icon \{ width: 1\.5rem", css)
    assert "data-gw-clear-btn" in ui


def test_los_iconos_de_las_cifras_tienen_su_color_y_los_tres_verdes_son_distintos():
    css = read("static/css/design-system.css")
    for tok in ("--gw-ico-lime", "--gw-ico-teal", "--gw-ico-forest", "--gw-ico-yellow", "--gw-req"):
        assert len(re.findall(rf"{tok}: #", css)) == 2, f"{tok} debe estar en el tema claro y en el oscuro"
    for line in re.findall(r"--gw-ico-lime:.*", css):          # una línea por tema: los tres verdes son tres colores distintos
        assert len(set(re.findall(r"--gw-ico-(?:lime|teal|forest): (#[0-9a-f]{6})", line))) == 3
    js = read("static/js/analytics-dashboard.js") + read("static/css/form-stats.css")
    for icon, tok in (("hand", "--gw-info-line"), ("flag-start", "--gw-ico-lime"), ("flag-end", "--gw-ico-yellow"), ("peak", "--gw-ico-teal"), ("gauge", "--gw-ico-forest"), ("sheet", "--gw-ok-line")):
        assert re.search(rf"__icon--{icon} \{{ color: var\({tok}\)", js), (icon, tok)


def test_el_asterisco_obligatorio_es_naranja_y_sale_en_toda_pantalla_del_personal():
    ui, css = read("static/js/gw-ui.js"), read("static/css/design-system.css")
    assert re.search(r"\.gw-req \{ color: var\(--gw-req\)", css) and "color: var(--gw-err-text)" not in re.search(r"\.gw-req \{[^}]*\}", css).group(0)
    assert "function scanReq" in ui and "watchReq();" in ui and "input[required], select[required], textarea[required]" in ui
    assert "attributeFilter: ['required']" in ui                      # si `required` se quita, el asterisco se quita
    pf = read("static/js/person-form.js")
    assert "star.className = 'gw-req'" in pf and "label.textContent = label.textContent.replace(" in pf
    d = read("static/js/directory.js")
    assert 'class="gw-req"' in d and 'class="gw-input" required>' in d          # el dato fijo del Editar es obligatorio de verdad, no solo marcado
    assert "gw-req" in read("static/js/person-form-designer.js")


def test_el_formulario_publico_no_lleva_asteriscos_sino_opcional():
    fr = read("static/js/form-render.js")
    assert "c0392b\">*" not in fr and "color:#c0392b\">*" not in fr
    assert "(opcional)" in fr and "g.required ? '' : OPTIONAL" in fr and "pf.required ? '' : OPTIONAL" in fr
    assert "Tienes que llenar este campo" in fr and "Este campo es obligatorio" not in fr
    # sigue sin cargar nada del personal: ni el diseño ni gw-ui.js (que es quien pone el asterisco naranja)
    assert "gw-ui.js" not in read("templates/form_public.html")


def test_celular_y_computador_muestran_lo_mismo_en_eventos_y_formularios():
    """Misma información, símbolos y colores en cualquier ancho (cambia solo la forma de presentarla)."""
    css = read("static/css/p-clientes.css")
    # «Ingresar» dorado fuera de cualquier @media
    assert "\n.gw-event-card .p-cli__acts > a.p-cli__act { background: var(--gw-gold-grad)" in css          # sin sangría = fuera de cualquier @media
    assert ".p-cli__rep--full { display: none" not in css and ".p-cli__morelbl { display: none" not in css      # el aviso del informe y «Más acciones» se leen completos también en computador
    assert re.search(r"\.gw-event-card \.p-cli__rep--dot \{ display: none; \}", css)
    forms = read("static/css/p-formularios.css")
    assert ".gw-stat__hint { display: none; }" not in forms and "gw-forms-lbl { position: absolute" not in forms
