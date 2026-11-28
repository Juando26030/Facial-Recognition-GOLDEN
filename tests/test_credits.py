"""Pie de créditos de autoría (app/credits.py, 28-nov-2026): sale en las páginas HTML completas, se puede evitar, no se duplica y no toca lo que no es una página."""
from pathlib import Path

from app import credits

PAGE = b'<html><head><title>x</title></head><body class="a"><p>hola</p></body></html>'
ROOT = Path(__file__).resolve().parent.parent


def test_footer_and_meta_are_added_once_in_both_languages():
    out = credits.inject(PAGE)
    assert out.count(b"<footer data-gw-credit") == 1 and b'<meta name="author" content="Juan David Ram' in out
    assert "Software diseñado y creado por Juan David".encode() in out and b"Software designed &amp; built by Juan David" in out
    assert out.endswith(b"</footer></body></html>") and credits.inject(out) == out


def test_print_screens_and_non_pages_are_left_alone():
    assert credits.inject(b"<html><body data-gw-no-credit></body></html>") == b"<html><body data-gw-no-credit></body></html>"
    assert credits.inject(b'{"ok": true}') == b'{"ok": true}' and credits.inject(b"") == b""
    for name in ("kiosk_tv", "roulette_display", "badge_print", "impresion_usb", "certificado_local"):
        assert "data-gw-no-credit" in (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")


def test_footer_is_small_responsive_and_not_printed():
    css = credits._FOOTER.decode()
    assert "@media (max-width:480px)" in css and "@media print{[data-gw-credit]{display:none}}" in css and "font:400 11px" in css


def test_authorship_files_exist():
    assert "Juan David Ramírez Juzga" in (ROOT / "NOTICE.md").read_text(encoding="utf-8") and "Juan David Ramírez Juzga" in (ROOT / "AUTHORS.md").read_text(encoding="utf-8")
    assert "Juan David Ramírez Juzga" in (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")


def test_orum_logo_switches_by_background_not_only_by_theme():
    js = (ROOT / "static" / "js" / "gw-orum.js").read_text(encoding="utf-8")
    assert "backgroundColor" in js and "data-src-oscuro" in js and "MutationObserver" in js
    for name in ("login", "password", "ingreso_espera"):
        html = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        assert "data-gw-orum" in html and "orum-logo-oscuro.svg" in html and "js/gw-orum.js" in html
