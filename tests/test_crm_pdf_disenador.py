"""Diseñador de PDF de cotizaciones (16-nov-2026): validación del diseño, armado del PDF con logo, foto de producto y un PDF insertado a mitad. Pruebas puras (reportlab, pypdf y Pillow)."""
import io

import pytest
from PIL import Image
from pypdf import PdfReader

from app.crm import quote_layout as ql
from app.crm import quote_pdf
from app.crm.errors import CrmError


def _png(w=200, h=100):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(b, "PNG")
    return b.getvalue()


def _pdf(pages=2, tag="PORTAFOLIO"):
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b)
    for i in range(pages):
        c.drawString(100, 700, f"{tag} p{i + 1}")
        c.showPage()
    c.save()
    return b.getvalue()


def _text(pdf):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]


def test_starter_layouts_validate_and_render():
    for name in ("classic", "blank"):
        lay = ql.clean_layout(ql.starter(name))
        pdf = ql.render(lay, ql.SAMPLE_QUOTE, lambda k: b"")
        assert pdf.startswith(b"%PDF") and "1234" in _text(pdf)[0]
    assert "Stand modular" in _text(ql.render(ql.starter(), ql.SAMPLE_QUOTE, lambda k: b""))[0]


def test_variables_are_filled_and_unknown_ones_stay_visible():
    ctx = ql.context(ql.SAMPLE_QUOTE, "2026-11-16")
    assert ql.fill("N.º {{numero}} · {{ cliente }} · {{inventada}}", ctx) == "N.º 1234 · Cliente de ejemplo S.A.S. · {{inventada}}"
    assert ctx["total"] == "6.426.000,00 COP" and ctx["hoy"] == "16/11/2026"


def test_logo_product_photo_and_pdf_inserted_in_the_middle():
    files = {"crm/doc_assets/7/a.png": _png(), "crm/doc_assets/7/p.pdf": _pdf(3)}
    lay = ql.clean_layout({"blocks": [
        {"type": "logo", "asset": "crm/doc_assets/7/a.png", "width": 120}, {"type": "heading", "text": "COTIZACIÓN {{numero}}"},
        {"type": "table", "columns": ["pos", "foto", "nombre", "cantidad", "precio", "total"]}, {"type": "totals"},
        {"type": "pdf", "asset": "crm/doc_assets/7/p.pdf", "pages": "2-3"}, {"type": "text", "text": "Gracias por su confianza"}, {"type": "terms"}]}, template_id=7)
    q = dict(ql.SAMPLE_QUOTE, lines=[dict(ln, product_id=5) for ln in ql.SAMPLE_QUOTE["lines"]])
    pdf = ql.render(lay, q, lambda k: files[k], images={5: _png()}, today_iso="2026-11-16")
    pages = _text(pdf)
    assert len(pages) == 4 and "COTIZACIÓN 1234" in pages[0]
    assert "PORTAFOLIO p2" in pages[1] and "PORTAFOLIO p3" in pages[2] and "PORTAFOLIO p1" not in "".join(pages)          # el PDF entra a la mitad y solo con las páginas pedidas
    assert "Gracias por su confianza" in pages[3] and "Condiciones comerciales" in pages[3]


def test_a_broken_asset_does_not_break_the_pdf():
    lay = ql.clean_layout({"blocks": [{"type": "image", "asset": "crm/doc_assets/7/falta.png"}, {"type": "heading", "text": "Hola"}]}, template_id=7)

    def boom(key):
        raise FileNotFoundError(key)
    assert "Hola" in _text(ql.render(lay, ql.SAMPLE_QUOTE, boom))[0]


def test_a_broken_inserted_pdf_is_skipped_but_the_rest_stays():
    lay = ql.clean_layout({"blocks": [{"type": "heading", "text": "Antes"}, {"type": "pdf", "asset": "crm/doc_assets/7/x.pdf"}, {"type": "text", "text": "Después"}]}, template_id=7)
    out = _text(ql.render(lay, ql.SAMPLE_QUOTE, lambda k: b"%PDF-no-es-un-pdf"))
    assert "Antes" in out[0] and "Después" in out[-1]


@pytest.mark.parametrize("bad, fragment", [
    ({"blocks": "x"}, "formato"),
    ({"blocks": [{"type": "magia"}]}, "tipo conocido"),
    ({"blocks": [{"type": "logo", "asset": "../../etc/passwd"}]}, "no es válido"),
    ({"blocks": [{"type": "logo", "asset": "crm/doc_assets/9/a.png"}]}, "no es válido"),          # de otra plantilla
    ({"blocks": [{"type": "logo"}]}, "Falta el archivo"),
    ({"blocks": [{"type": "text", "text": "x" * 6000}]}, "demasiado largo"),
    ({"blocks": [{"type": "heading", "text": "x", "size": 500}]}, "entre"),
    ({"blocks": [{"type": "pdf", "asset": "crm/doc_assets/7/a.pdf", "pages": "uno"}]}, "páginas del PDF"),
    ({"blocks": [{"type": "line"}] * 61}, "hasta 60"),
])
def test_invalid_layouts_are_rejected_with_a_clear_message(bad, fragment):
    with pytest.raises(CrmError) as e:
        ql.clean_layout(bad, template_id=7)
    assert fragment in e.value.message


def test_clean_layout_drops_unknown_columns_fields_and_keeps_description_column():
    lay = ql.clean_layout({"blocks": [{"type": "table", "columns": ["total", "raro", "foto", "total"]}, {"type": "fields", "items": ["cliente", "secreto"]}]})
    assert lay["blocks"][0]["columns"] == ["nombre", "total", "foto"] and lay["blocks"][1]["items"] == ["cliente"]


def test_uploaded_files_are_checked_by_content():
    assert ql.check_image(_png())["ext"] == "png"
    with pytest.raises(CrmError):
        ql.check_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    with pytest.raises(CrmError):
        ql.check_image(b"x" * (ql.MAX_IMAGE_BYTES + 1))
    assert ql.check_pdf(_pdf(2)) == {"pages": 2}
    with pytest.raises(CrmError):
        ql.check_pdf(b"%PDF-roto")
    with pytest.raises(CrmError):
        ql.check_pdf(b"GIF89a")


def test_page_numbers():
    assert ql.page_numbers("", 3) == [0, 1, 2] and ql.page_numbers("2-3", 5) == [1, 2] and ql.page_numbers("1,3,9", 4) == [0, 2] and ql.page_numbers("3-1", 4) == []


def test_template_with_layout_uses_the_designer_and_without_it_the_classic_pdf():
    tpl = {"id": 1, "header_text": "", "greeting_text": "", "footer_text": "", "layout": ql.starter("blank")}
    assert "COTIZACIÓN N.º 1234" in _text(quote_pdf.render_quote(ql.SAMPLE_QUOTE, tpl, lambda k: b""))[0]
    assert "COTIZACI" in _text(quote_pdf.render_quote(dict(ql.SAMPLE_QUOTE, version=1)))[0]          # sin diseño: el PDF sencillo de siempre


def test_template_signature_changes_with_the_design_and_the_photos():
    a = {"id": 1, "layout": ql.starter("blank")}
    b = {"id": 1, "layout": ql.starter("classic")}
    assert quote_pdf.template_sig(a) != quote_pdf.template_sig(b) and quote_pdf.template_sig(a) == quote_pdf.template_sig(dict(a))
    assert quote_pdf.template_sig(a, "foto1") != quote_pdf.template_sig(a, "foto2") and quote_pdf.template_sig(None) == ""
    assert quote_pdf.quote_key(type("Q", (), {"id": 3, "number": 5, "version": 1})()).endswith(f"-d{quote_pdf.LAYOUT}.pdf")
