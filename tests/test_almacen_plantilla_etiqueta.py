"""Almacén: plantilla editable de la etiqueta QR (app/almacen_label.py y su ventana). Sin base de datos."""
from pathlib import Path

from app import almacen_label as a

ROOT = Path(__file__).resolve().parent.parent


def test_clean_always_returns_a_full_template_within_limits():
    t = a.clean({"height_mm": 500, "qr_pos": "otro", "title_mm": "x", "copies": 99, "show_code": 0, "extra_text": "  hola   mundo "})
    assert t["height_mm"] == 100 and t["qr_pos"] == "left" and t["title_mm"] == a.DEFAULTS["title_mm"] and t["copies"] == 10
    assert t["show_code"] is False and t["show_title"] is True and t["extra_text"] == "hola mundo"
    assert set(t) == set(a.DEFAULTS)
    assert a.clean(None) == a.DEFAULTS and a.load("no es json") == a.DEFAULTS


def test_the_window_edits_the_template_and_keeps_the_roll_width():
    js = (ROOT / "static/js/almacen-etiquetas.js").read_text(encoding="utf-8")
    html = (ROOT / "templates/almacen_etiquetas.html").read_text(encoding="utf-8")
    assert "62mm" in js and "label-template" in js and "kiosk-printing" not in js
    for el in ("tplHeight", "tplQrPos", "tplSave", "tplReset", "tplExtra", "tplCopies"):
        assert f'id="{el}"' in html
    assert "label-template" in (ROOT / "app/routers/almacen.py").read_text(encoding="utf-8")
    assert "etiquetas" in (ROOT / "templates/_inventory_catalog_admin.html").read_text(encoding="utf-8")
