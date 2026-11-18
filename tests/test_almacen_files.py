"""Almacén · Pieza 3 (sin base de datos): archivos adjuntos de las novedades."""
import io

import pytest
from PIL import Image

from app import almacen_files as f
from app.almacen import AlmacenError


def _png():
    b = io.BytesIO()
    Image.new("RGB", (50, 40), (1, 2, 3)).save(b, format="PNG")
    return b.getvalue()


def test_photos_are_recoded_to_jpeg_and_pdf_and_video_are_checked_by_content():
    img = f.classify("daño.PNG", _png())
    assert img["kind"] == "image" and img["ext"] == ".jpg" and img["data"][:3] == b"\xff\xd8\xff"
    assert f.classify("acta.pdf", b"%PDF-1.7 ...")["content_type"] == "application/pdf"
    assert f.classify("clip.MOV", b"\x00\x00\x00\x14ftypqt  rest")["content_type"] == "video/quicktime"
    assert f.classify("clip.mp4", b"\x00\x00\x00\x18ftypmp42rest")["ext"] == ".mp4"


def test_wrong_content_or_type_is_refused():
    for name, data in (("x.pdf", b"no soy pdf"), ("x.mp4", b"nada"), ("x.exe", b"MZ"), ("x.png", b"no es imagen"), ("vacio.pdf", b"")):
        with pytest.raises(AlmacenError):
            f.classify(name, data)
    with pytest.raises(AlmacenError, match="pesa más"):
        f.classify("grande.pdf", b"%PDF" + b"0" * f.MAX_FILE_BYTES)


def test_a_submission_needs_at_least_one_file_and_respects_the_limits():
    with pytest.raises(AlmacenError, match="al menos un archivo"):
        f.classify_all([], required=True, what="la foto del daño")
    with pytest.raises(AlmacenError, match="al menos un archivo"):
        f.classify_all([("", b"")], required=True, what="la foto del daño")
    assert f.classify_all([], required=False, what="x") == []
    with pytest.raises(AlmacenError, match="hasta"):
        f.classify_all([("a.pdf", b"%PDF-1")] * (f.MAX_FILES + 1), required=True, what="x")
    big = b"%PDF" + b"0" * 9_000_000
    with pytest.raises(AlmacenError, match="en total"):
        f.classify_all([("a.pdf", big), ("b.pdf", big), ("c.pdf", big)], required=True, what="x")
    assert len(f.classify_all([("a.pdf", b"%PDF-1"), ("b.png", _png())], required=True, what="x")) == 2


def test_names_are_cleaned():
    assert f.safe_name("../../etc/pas<s>wd.pdf") == "passwd.pdf" and f.safe_name("") == "archivo"


def test_novedades_permiten_tomar_foto_con_la_camara():
    """18-nov-2026: además de elegir archivos, reportar y resolver una novedad ofrecen «Tomar foto con la cámara» (input capture=environment) y la foto queda adjunta a la lista."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    panel = (root / "templates" / "_almacen_novedades_panel.html").read_text(encoding="utf8")
    js = (root / "static" / "js" / "almacen-novedades.js").read_text(encoding="utf8")
    assert 'id="almNovCam"' in panel and 'id="almNovCamIn"' in panel and 'capture="environment"' in panel
    assert "data-nov-cam=" in js and "data-nov-camin=" in js and 'capture="environment"' in js and "shots(" in js
    assert "card.querySelector" not in js          # el manejador de «resolver» ya no usa una variable que no existía
