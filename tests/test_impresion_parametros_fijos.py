"""Parámetros de impresión confirmados en la Brother QL-800 (28-oct-2026): ver docs/IMPRESION_PARAMETROS_INAMOVIBLES.md. Si esta prueba falla, NO se «arregla» la prueba: se respeta lo definido."""
from pathlib import Path

HTML = Path("templates/badge_print.html").read_text(encoding="utf-8")
COMPOSE = Path("static/js/label-compose.js").read_text(encoding="utf-8")


def test_normal_window_page_is_always_62_by_99_8mm_with_margin_zero():
    assert "const PAGE_W = 62, PAGE_LEFT_MM = 0.5, PAGE_H = 99.8, MAX_IMG_H = 96;" in HTML
    assert "const pageH = PAGE_H;" in HTML and "Math.min(1, MAX_IMG_H / spec.imageHeightMm)" in HTML      # página SIEMPRE 99,8 mm; la imagen mide como máximo 96 mm (la impresora no imprime los últimos mm) y una más alta se reduce
    assert "@page { size: ${PAGE_W}mm ${pageH}mm; margin: 0 }" in HTML and "margin-left:${imgLeft}mm" in HTML and "PAGE_LEFT_MM + (spec.imageWidthMm - imgW) / 2" in HTML


def test_end_mark_keeps_the_label_length_and_is_painted_over_the_image():
    assert "endMark.id = 'endMark'" in HTML and "position:relative; z-index:1; width:0.3mm; height:0.3mm;" in HTML and "background:#000" in HTML


def test_same_composed_label_as_usb_and_ink_width_58_93mm():
    assert "LabelCompose.composeBitmap(shot, template.width_mm, template.height_mm, p)" in HTML and "LabelCompose.pageSpec(out)" in HTML
    assert "58.93" in COMPOSE or "tapeDots" in COMPOSE
    assert "QLUsb.resolvePrefs(storage, printSettings()).prefs" in HTML                              # recorte, giro y margen de Parámetros y ⚙️


def test_denied_bar_and_no_shared_calls_when_off_stay():
    sp = Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "usb.busy || usb.denied ||" in sp and "if (!SHARED && !usb.ok) return auto ? original.maybeAutoPrint(userId) : original.openPrintWindow(userId);" in sp
