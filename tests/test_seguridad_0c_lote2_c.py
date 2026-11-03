"""0C lote 2, grupo C: topes de ZIP (B3), píxeles de imágenes (B-N1) y librerías externas con `integrity` (D9).
Pruebas puras (sin base de datos ni motor facial)."""
import io
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app import safe_limits

ROOT = Path(__file__).resolve().parent.parent


def _zip(entries: dict, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_zip_normal_se_acepta():
    zf = safe_limits.open_checked_zip(_zip({"1001.jpg": b"abc", "1002.jpg": b"def"}))
    assert len(zf.infolist()) == 2


def test_zip_demasiadas_entradas(monkeypatch):
    monkeypatch.setenv("ZIP_MAX_ENTRIES", "3")
    with pytest.raises(safe_limits.LimitError, match="demasiados archivos"):
        safe_limits.open_checked_zip(_zip({f"{i}.jpg": b"x" for i in range(4)}))


def test_zip_entrada_demasiado_grande(monkeypatch):
    monkeypatch.setenv("ZIP_MAX_ENTRY_MB", "1")
    monkeypatch.setenv("ZIP_MAX_RATIO", "100000")
    with pytest.raises(safe_limits.LimitError) as e:
        safe_limits.open_checked_zip(_zip({"a.jpg": b"\0" * (2 * 1024 * 1024)}))
    assert e.value.status == 413 and "descomprimido" in e.value.message


def test_zip_total_descomprimido(monkeypatch):
    monkeypatch.setenv("ZIP_MAX_UNCOMPRESSED_MB", "1")
    monkeypatch.setenv("ZIP_MAX_RATIO", "100000")
    with pytest.raises(safe_limits.LimitError, match="una vez descomprimido"):
        safe_limits.open_checked_zip(_zip({"a.bin": b"\0" * 700_000, "b.bin": b"\0" * 700_000}))


def test_zip_bomba_por_razon_de_compresion():
    bomba = _zip({"a.bin": b"\0" * (30 * 1024 * 1024)})
    with pytest.raises(safe_limits.LimitError, match="sospechosa"):
        safe_limits.open_checked_zip(bomba)


def test_zip_invalido():
    with pytest.raises(safe_limits.LimitError, match="no es válido"):
        safe_limits.open_checked_zip(b"esto no es un zip")


def test_read_entry_tope_real(monkeypatch):
    monkeypatch.setenv("ZIP_MAX_ENTRY_MB", "1")
    zf = zipfile.ZipFile(io.BytesIO(_zip({"a.bin": b"\0" * (2 * 1024 * 1024)})))
    with pytest.raises(safe_limits.LimitError):
        safe_limits.read_entry(zf, "a.bin")


def _png(w, h) -> bytes:
    b = io.BytesIO()
    Image.new("1", (w, h)).save(b, "PNG")
    return b.getvalue()


def test_imagen_normal_pasa():
    safe_limits.check_image_dimensions(_png(200, 100))


def test_imagen_con_demasiados_pixeles(monkeypatch):
    monkeypatch.setenv("IMAGE_MAX_PIXELS", "10000")
    with pytest.raises(safe_limits.LimitError) as e:
        safe_limits.check_image_dimensions(_png(200, 100))
    assert e.value.status == 413 and "megapíxeles" in e.value.message


def test_imagen_invalida():
    with pytest.raises(safe_limits.LimitError, match="no es una imagen"):
        safe_limits.check_image_dimensions(b"nada")


def test_max_image_pixels_de_pillow_fijado():
    assert Image.MAX_IMAGE_PIXELS is not None and Image.MAX_IMAGE_PIXELS <= 100_000_000


def test_subidas_de_imagen_usan_el_tope():
    for rel in ("app/biometrics.py", "app/routers/event_docs.py", "app/routers/forms_public.py", "app/routers/parametros.py",
                "app/routers/signatures.py", "app/routers/form_transfer.py"):
        assert "check_image_dimensions" in (ROOT / rel).read_text(encoding="utf-8"), rel
    assert "open_checked_zip" in (ROOT / "app/routers/api.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- D9
_EXT = re.compile(r"<(script|link)\b[^>]*?(?:src|href)=[\"'](https?://[^\"']+)[\"'][^>]*>", re.I)
# Google Fonts (hoja de estilos dinámica, sin hash estable) queda fuera: no ejecuta código.
_SIN_INTEGRITY_OK = ("fonts.googleapis.com", "fonts.gstatic.com")


# Vacía: SheetJS y Chart.js ya llevan integrity (hash sha384 calculado en el navegador de Juan David y contrastado con el sha512 que publica la API de cdnjs).
PENDIENTES_INTEGRITY = ()


def test_jszip_se_aloja_en_static_y_no_en_cdn():
    assert (ROOT / "static/vendor/jszip-3.10.1.min.js").exists() and (ROOT / "static/vendor/jszip-LICENSE.txt").exists()
    for t in ("kiosk_certificados.html", "kiosk_roster.html"):
        txt = (ROOT / "templates" / t).read_text(encoding="utf-8")
        assert "vendor/jszip-3.10.1.min.js" in txt and "jszip/3.10.1" not in txt
    assert "JSZip v3.10.1" in (ROOT / "static/vendor/jszip-3.10.1.min.js").read_text(encoding="utf-8")


def test_riesgo_del_traductor_documentado():
    assert "translate.google.com" in (ROOT / "docs/0C_d9_librerias_externas.md").read_text(encoding="utf-8")


def test_todo_script_externo_lleva_integrity():
    faltan = []
    for p in list((ROOT / "templates").rglob("*.html")) + list((ROOT / "static").rglob("*.js")):
        for m in _EXT.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            url, tag = m.group(2), m.group(0)
            if any(h in url for h in _SIN_INTEGRITY_OK):
                continue
            if m.group(1).lower() == "link" and "stylesheet" not in tag.lower():
                continue
            if any(x in url for x in PENDIENTES_INTEGRITY):
                continue
            if "integrity=" not in tag or "crossorigin" not in tag:
                faltan.append(f"{p.relative_to(ROOT)}: {url}")
    assert not faltan, faltan
