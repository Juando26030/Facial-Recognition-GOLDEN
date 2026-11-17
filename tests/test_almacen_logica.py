"""Almacén · Pieza 1: lógica pura (app/almacen.py), sin base de datos ni servidor. Las pruebas de API están en tests/test_almacen_api.py (necesitan Postgres)."""
import re
from pathlib import Path

import pytest

from app import almacen

ROOT = Path(__file__).resolve().parent.parent


def test_flag_is_off_by_default_and_reads_the_env(monkeypatch):
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    assert almacen.almacen_enabled() is False
    for v in ("1", "true", "YES", " on "):
        monkeypatch.setenv("ALMACEN_ENABLED", v)
        assert almacen.almacen_enabled() is True
    for v in ("0", "", "no", "false"):
        monkeypatch.setenv("ALMACEN_ENABLED", v)
        assert almacen.almacen_enabled() is False


def test_checklist_rows_follow_the_geyl_format():
    rows = almacen.CHECKLIST_ROWS
    assert len(rows) == 43 and len({r["key"] for r in rows}) == 43          # 25 de hardware + 11 de papelería + 7 de varios (sin los 3 títulos)
    assert [r["excel_row"] for r in rows] == sorted(r["excel_row"] for r in rows)          # en el orden del Excel
    assert rows[0]["label"] == "Teclados" and rows[0]["excel_row"] == 9 and rows[-1]["excel_row"] == 53
    assert {r["section"] for r in rows} == {"hardware", "papeleria", "varios"}
    assert {r["key"] for r in rows if r["kind"] == "manual"} == {"listado_personal", "lista_telefonos", "listado_equipos_seriales", "plan_b", "encargado_acarreo"}
    assert set(almacen.inventory_row_keys()) == {r["key"] for r in rows if r["kind"] == "inv"} and "plan_b" not in almacen.inventory_row_keys()


def test_clean_tracking_and_checklist_row():
    assert almacen.clean_tracking(" Serial ") == "serial" and almacen.clean_tracking("modelo") == "modelo" and almacen.clean_tracking("CANTIDAD") == "cantidad"
    for bad in (None, "", "otro"):
        with pytest.raises(almacen.AlmacenError):
            almacen.clean_tracking(bad)
    assert almacen.clean_checklist_row(None) is None and almacen.clean_checklist_row("  ") is None
    assert almacen.clean_checklist_row("portatiles") == "portatiles"
    with pytest.raises(almacen.AlmacenError, match="no existe"):
        almacen.clean_checklist_row("inventada")
    with pytest.raises(almacen.AlmacenError, match="verificación manual"):
        almacen.clean_checklist_row("plan_b")


def test_clean_serial_count_and_ids():
    assert almacen.clean_serial(None) is None and almacen.clean_serial("  ") is None and almacen.clean_serial(" SN-123 ") == "SN-123"
    with pytest.raises(almacen.AlmacenError):
        almacen.clean_serial("x" * 81)
    with pytest.raises(almacen.AlmacenError):
        almacen.clean_serial("<b>")
    assert almacen.clean_count("5") == 5 and almacen.clean_count(100) == 100
    for bad in (0, 101, "x", None, -1):
        with pytest.raises(almacen.AlmacenError):
            almacen.clean_count(bad)
    assert almacen.clean_ids(None, "x") == [] and almacen.clean_ids([1, "2", 2, 1], "x") == [1, 2]
    with pytest.raises(almacen.AlmacenError):
        almacen.clean_ids("no es lista", "x")
    with pytest.raises(almacen.AlmacenError):
        almacen.clean_ids(["a"], "x")
    with pytest.raises(almacen.AlmacenError):
        almacen.clean_ids(list(range(1, 202)), "x")


def test_codes_are_uppercase_alphanumeric_without_ambiguous_characters():
    seen = set()
    for _ in range(2000):
        c = almacen.new_code()
        assert re.fullmatch(r"GW[A-Z2-9]{6}", c) and not set(c[2:]) & set("01OIL")
        assert almacen.normalize_scan(c) == c
        seen.add(c)
    assert len(seen) == 2000          # con 6 caracteres de 31 posibles no se repiten en una muestra así


def test_normalize_scan_cleans_what_the_usb_reader_types():
    assert almacen.normalize_scan("gwk7m2pa\r\n") == "GWK7M2PA" and almacen.normalize_scan("  gw k7 m2pa ") == "GWK7M2PA"
    for bad in (None, "", "abc", "GW-K7M2PA", "GWK7M2PA" * 5, "¡GWK7M2!"):
        assert almacen.normalize_scan(bad) is None


def test_unit_title():
    assert almacen.unit_title("Portátil Lenovo", 14) == "Portátil Lenovo #14"


def test_migration_0148_chains_after_0147_and_only_adds():
    text = (ROOT / "alembic" / "versions" / "0148_almacen_unidades.py").read_text(encoding="utf-8")
    assert 'revision = "0148_almacen_unidades"' in text and 'down_revision = "0147_legalizaciones_formato"' in text and len("0148_almacen_unidades") <= 32
    assert "drop_column" in text.split("def downgrade")[1] and "drop_column" not in text.split("def downgrade")[0]          # solo la bajada quita cosas
    assert 'server_default="cantidad"' in text          # los productos que ya existen quedan «por cantidad», como se comportaban


def test_the_new_screen_and_label_page_respect_the_house_rules():
    """Sin estilos en línea, colores escritos a mano, manejadores en línea ni emojis en lo nuevo; archivos estáticos solo por url_for."""
    hexc = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}(?![0-9a-zA-Z_-])")
    handler = re.compile(r"\son(?:click|change|submit|input|keydown|keyup|load|error)=", re.I)
    emoji = re.compile("[☀-➿\U0001F300-\U0001FAFF]")
    for name in ("_almacen_panel.html", "almacen_etiquetas.html"):
        html = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert not re.search(r'\sstyle="', html) and not hexc.search(html) and not handler.search(html) and not emoji.search(html), name
        assert not re.search(r'(?:src|href)="/static/', html), name
    for name in ("static/css/gw-almacen.css", "static/css/gw-almacen-etiquetas.css"):
        assert not hexc.search((ROOT / name).read_text(encoding="utf-8")), name


def test_label_page_does_not_touch_the_shared_printing():
    """La ventana de etiquetas es propia: no carga ni cambia la impresión compartida (escarapelas, USB, etiqueta compuesta)."""
    html = (ROOT / "templates" / "almacen_etiquetas.html").read_text(encoding="utf-8")
    for shared in ("ql-usb.js", "label-compose.js", "badge-render.js", "badge_print", "html2canvas"):
        assert shared not in html
    js = (ROOT / "static" / "js" / "almacen-etiquetas.js").read_text(encoding="utf-8")
    assert "62mm" in js and "kiosk-printing" not in js and "ql-usb" not in js
