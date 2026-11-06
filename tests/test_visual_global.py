"""Fase 1.5 · candado visual (docs/ux/FASE_1_5_PLAN.md, R10). Cada plantilla que termina su rediseño se agrega a MIGRADAS y desde ese momento no puede volver a traer
estilos en línea, colores escritos a mano, manejadores en línea ni emojis, y debe usar el diseño nuevo (gw-page). Las pantallas congeladas (lo que ven las personas) NO van aquí."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRADAS = ["kiosk_registro.html", "kiosk_roster.html", "kiosk_parametros.html", "kiosk_select.html", "kiosk_rostro.html", "sistema.html", "dashboard.html", "password.html", "login.html", "kiosk_formularios.html", "kiosk_usuarios.html", "kiosk_documentos.html", "kiosk_legalizaciones.html", "kiosk_certificados.html", "nuevo_evento.html", "kiosk_areas.html", "kiosk_inventario.html", "kiosk_ruleta.html", "kiosk_ruleta_visual.html", "clientes.html", "configuracion.html", "staff.html", "kiosk_estadisticas.html", "form_stats.html", "eventos.html", "calendario.html", "_event_edit_modal.html", "kiosk_formulario_editor.html", "badge_editor.html", "impresion_usb.html"]          # cada PR de la Fase 1.5 agrega las suyas
EMOJI = re.compile("[☀-➿\U0001F300-\U0001FAFF]")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}(?![0-9a-zA-Z_-])")
INLINE_HANDLER = re.compile(r"\son(?:click|change|submit|input|keydown|keyup|load|error)=", re.I)


def _html(name):
    return (ROOT / "templates" / name).read_text(encoding="utf-8")


def test_migrated_templates_use_the_new_design_only():
    problems = []
    for name in MIGRADAS:
        html = _html(name)
        if "gw-page" not in html and "_gw_head" not in html:
            problems.append(f"{name}: sin gw-page / _gw_head")
        if re.search(r'\sstyle="', html):
            problems.append(f"{name}: style= en línea")
        if HEX.search(html):
            problems.append(f"{name}: color escrito a mano")
        if INLINE_HANDLER.search(html):
            problems.append(f"{name}: manejador en línea (usar delegación)")
        if EMOJI.search(html):
            problems.append(f"{name}: emoji (usar los íconos del sprite)")
    assert not problems, "; ".join(problems)


def test_icon_only_buttons_have_a_name():
    for name in MIGRADAS:
        for tag in re.findall(r"<button\b[^>]*>(?:\s*<svg[^>]*>.*?</svg>\s*)</button>", _html(name), flags=re.S):
            assert "aria-label" in tag or "title=" in tag, f"{name}: botón solo-ícono sin nombre accesible"


def test_every_screen_with_a_savebar_has_exactly_one():
    # R1: un solo botón «Guardar» global por pantalla
    for name in MIGRADAS:
        assert _html(name).count('class="gw-savebar"') + _html(name).count("class=\"gw-savebar ") <= 1, name
