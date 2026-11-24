"""Usabilidad del digitador y del cliente (revisión 22-nov-2026, docs/revision_2026-11-22/15_usabilidad_digitador_correcciones.md).

Pruebas de texto (sin base): fijan que el sistema AVISA lo que hace solo (Editar registra) y que el digitador y el cliente no ven puertas cerradas.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COND = '{% if staff_role not in ["digitador", "cliente"] %}'


def _t(name):
    return (ROOT / "templates" / name).read_text(encoding="utf-8")


def _s(path):
    return (ROOT / "static" / path).read_text(encoding="utf-8")


def test_editar_avisa_que_guardar_registra_y_no_existe_guardar_sin_registrar():
    js = _s("js/directory.js")
    assert "Al guardar, esta persona queda Registrada" in js and "y se imprime su escarapela" in js and "window.EVENT_AUTO_PRINT ?" in js
    assert 'id="editModalRegNote"' in js and "'Guardar y registrar'" in js
    # 24-nov-2026 (Juan David): «Guardar sin registrar» no existe para nadie; corregir un dato sin registrar = coordinador+ cambiando el estado
    assert "editModalSaveOnly" not in js and 'Guardar sin registrar</button>' not in js and "skipRegister" not in js
    assert "if (!canManageStatus && !isRegistered) {" in js
    # coordinador o superior: el aviso y el nombre del botón siguen al selector de estado; el valor por defecto (23-sep-2026) no cambia
    assert "const defaultStatus = 'registrado';" in js and "regNote.hidden = !will;" in js


def test_digitador_y_cliente_sin_menu_lateral_en_las_pantallas_del_quiosco():
    for name in ("kiosk_inventario.html", "kiosk_areas.html", "kiosk_turnos.html", "kiosk_alistamiento.html", "kiosk_registro.html", "kiosk_select.html", "kiosk_estadisticas.html"):
        html = _t(name)
        assert COND + '{% include "_sidebar.html" %}{% endif %}' in html, name
        assert html.count('{% include "_sidebar.html" %}') == 1, name
        body = re.search(r"<body[^>]*(?:\{%.*?%\}[^>]*)*>", html).group(0)
        assert "has-sidebar{% endif %}" in body, name          # la clase que corre el contenido también depende del rol
    for name in ("kiosk_inventario.html", "kiosk_areas.html", "kiosk_turnos.html", "kiosk_alistamiento.html"):
        html = _t(name)
        assert 'id="kioskBackLink" href="/kiosk/{{ event.id }}"' in html and "Elegir tarea" in html, name          # la salida que le queda: Elegir tarea y Salir
        assert 'action="/logout"' in html, name
    for name in ("kiosk_tv.html", "kiosk_turnos_tv.html"):          # las pantallas de TV nunca llevan menú
        assert "_sidebar.html" not in _t(name), name


def test_imprimir_y_editar_miden_el_minimo_tactil_entre_901_y_1499():
    css = _s("css/p-registro-puerta.css")
    block = css.split("@media (min-width: 901px) {", 1)[1].split("@media (min-width: 1500px)", 1)[0]
    assert "min-height: var(--gw-tap) !important; height: var(--gw-tap); min-width: var(--gw-tap);" in block
    assert "[title='Imprimir escarapela'] { width: var(--gw-tap); padding: 0 !important; }" in block
    assert ".gw-menu__btn--kebab { width: var(--gw-tap); padding: 0 !important; }" in block
    assert "2.5rem" not in "".join(ln for ln in block.splitlines() if "action" in ln)
    assert block.count("flex: 0 0 19.25rem") == 2          # la columna de acciones crece lo mismo que los botones (encabezado y fila alineados)


def test_campana_compacta_en_celular_y_pagina_con_aire_abajo():
    css = _s("css/gw-notifications.css")
    mobile = css.split("body:has(.gw-savebar) .gw-bell { bottom: calc(var(--gw-sp-4) + 8rem); }", 1)[1]
    assert ".gw-bell__btn { width: var(--gw-tap); height: var(--gw-tap); padding: 0; }" in mobile
    assert ".gw-page:has(.gw-bell) .golden-main { padding-bottom:" in css
    assert "display: none" not in mobile          # se reubica y se achica; no se oculta


def test_cliente_lee_quien_le_entrega_el_reporte():
    html = _t("kiosk_estadisticas.html")
    assert 'id="clientReportNote"' in html and "Desde esta cuenta no se descarga el reporte" in html and "asesor comercial de Golden" in html
    assert '{% if staff_role == "cliente" and not public_view %}' in html
    assert '{% if not public_view and staff_role != "cliente" %}, con el reporte completo para descargar{% endif %}' in html
    assert '{% if staff_role != "cliente" %}<button type="button" id="exportBtn"' in html          # la decisión del 17-sep-2026 no cambia


def test_autorregistro_deja_volver_al_personal_sin_javascript():
    html = _t("kiosk_autoregistro.html")
    assert '<details class="gw-autoreg__legal" id="autoregStaff">' in html and "<summary>Personal del evento</summary>" in html
    assert 'href="/kiosk/{{ event.id }}/registro">Volver al Registro</a>' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)          # sin JS en línea (trinquete del CSP)
