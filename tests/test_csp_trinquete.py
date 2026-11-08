"""Trinquete hacia el CSP estricto (8-nov-2026, ver docs/FASE_3_SEGURIDAD.md).

Hoy las plantillas traen 51 bloques de JavaScript en línea y 1 manejador en línea. Para poder activar algún día `script-src 'self'` sin romper
pantallas, la deuda solo puede BAJAR: una plantilla nueva nace sin JS en línea (va a static/js/) y ninguna existente puede sumar bloques.
Cuando migres uno, baja su número aquí (nunca lo subas). Los bloques `application/json` (datos) no cuentan.
"""
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# plantilla -> (bloques <script> en línea, manejadores onclick= y similares)
BASE = {
    "_event_edit_modal.html": (1, 0),
    "_gw_head.html": (3, 0),
    "_sidebar.html": (1, 0),
    "aceptar.html": (1, 0),
    "badge_editor.html": (3, 0),
    "badge_print.html": (1, 1),
    "calendario.html": (1, 0),
    "certificate_public.html": (1, 0),
    "configuracion.html": (1, 0),
    "digital_badge.html": (1, 0),
    "eventos.html": (1, 0),
    "form_public.html": (1, 0),
    "impresion_usb.html": (1, 0),
    "kiosk_areas.html": (1, 0),
    "kiosk_certificados.html": (1, 0),
    "kiosk_documentos.html": (1, 0),
    "kiosk_estadisticas.html": (2, 0),
    "kiosk_formulario_editor.html": (2, 0),
    "kiosk_formularios.html": (1, 0),
    "kiosk_inventario.html": (1, 0),
    "kiosk_legalizaciones.html": (1, 0),
    "kiosk_parametros.html": (6, 0),
    "kiosk_registro.html": (8, 0),
    "kiosk_roster.html": (2, 0),
    "kiosk_rostro.html": (1, 0),
    "kiosk_ruleta.html": (2, 0),
    "kiosk_ruleta_visual.html": (2, 0),
    "kiosk_select.html": (1, 0),
    "kiosk_usuarios.html": (1, 0),
    "roulette_display.html": (1, 0),
}

SCRIPT = re.compile(r'<script(?![^>]*\bsrc=)(?![^>]*type=["\']application/(?:ld\+)?json)[^>]*>', re.I)
HANDLER = re.compile(r'\son(?:click|change|submit|input|load|error|keyup|keydown|focus|blur)\s*=', re.I)


def _count():
    out = {}
    for f in sorted(glob.glob(str(ROOT / "templates" / "**" / "*.html"), recursive=True)):
        t = Path(f).read_text(encoding="utf-8")
        out[str(Path(f).relative_to(ROOT / "templates")).replace("\\", "/")] = (len(SCRIPT.findall(t)), len(HANDLER.findall(t)))
    return out


def test_inline_js_debt_never_grows():
    now = _count()
    for name, (scripts, handlers) in now.items():
        base_s, base_h = BASE.get(name, (0, 0))
        assert scripts <= base_s, f"{name}: {scripts} bloques <script> en línea (máx. {base_s}); mueve el código a static/js/ y usa url_for('static', ...)"
        assert handlers <= base_h, f"{name}: {handlers} manejadores en línea (máx. {base_h}); usa delegación de eventos"
