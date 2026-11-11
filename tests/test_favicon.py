"""Ícono de la pestaña (9-nov-2026, pedido de Juan David): el logo de Golden en todas las páginas y en /favicon.ico (los tres servicios)."""
from pathlib import Path

from app import appmode

ROOT = Path(__file__).resolve().parent.parent
SIN_ICONO = {"badge_print.html", "pledge_document.html"}       # ventana de impresión (parámetros inamovibles) y documento que se arma sin request


def test_every_page_links_the_golden_icon():
    faltan = [p.name for p in sorted((ROOT / "templates").glob("*.html"))
              if "</head>" in p.read_text(encoding="utf-8") and p.name not in SIN_ICONO and "path='favicon.ico'" not in p.read_text(encoding="utf-8")]
    assert not faltan, f"Páginas sin el ícono de Golden: {faltan}"


def test_icon_files_exist_and_are_small():
    for rel, top in (("static/favicon.ico", 40_000), ("static/img/favicon-32.png", 20_000), ("static/img/apple-touch-icon.png", 40_000)):
        size = (ROOT / rel).stat().st_size
        assert 0 < size < top, rel


def test_favicon_route_is_served_by_every_service():
    for mode in ("publico", "web", "biometria", "all"):
        assert appmode.route_allowed("/favicon.ico", mode=mode)


def test_favicon_route_answers_without_login(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/") and r.content[:4] == b"\x00\x00\x01\x00"
