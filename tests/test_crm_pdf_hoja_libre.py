"""Diseño LIBRE del PDF de cotización y de proforma (26-nov-2026, Juan David: «armar el PDF como los certificados o las escarapelas»). Pruebas puras (reportlab, pypdf, Pillow):
la hoja con elementos que se ubican donde se quiera, el recuadro del contenido que sigue en las páginas siguientes, proforma, paso del diseño por bloques, exportar e importar."""
import copy
import io
import json

import pytest
from PIL import Image
from pypdf import PdfReader

from app.crm import quote_free as qf
from app.crm import quote_layout as ql
from app.crm import quote_pdf
from app.crm.errors import CrmError


def _png(w=200, h=100):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(b, "PNG")
    return b.getvalue()


def _pages(pdf):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]


def _many_lines(n):
    q = copy.deepcopy(ql.SAMPLE_QUOTE)
    q["lines"] = [dict(q["lines"][0], position=i + 1) for i in range(n)]
    return q


def test_starters_validate_and_render_for_quote_and_proforma():
    for kind in ("quote", "proforma"):
        for name in ("classic", "blank"):
            lay = ql.clean_layout(qf.starter(name, kind), 7)
            assert lay["v"] == 2 and lay["page"] == "letter"
            assert quote_pdf.render_quote(ql.SAMPLE_QUOTE, {"layout": lay}, {}.get, {})[:5] == b"%PDF-"
    pro = ql.clean_layout(qf.starter("classic", "proforma"), 7)
    text = _pages(quote_pdf.render_proforma(ql.SAMPLE_PROFORMA, ql.SAMPLE_QUOTE, {"layout": pro}, {}.get, {}))[0]
    assert "PROFORMA" in text and "Bogotá" in text and "No pagado" in text and "Stand modular" in text and "6.426.000" in text


def test_elements_follow_their_page_rule_and_the_content_continues_on_next_pages():
    lay = qf.starter("classic", "quote")
    lay["elements"].append({"id": "solo2", "type": "text", "x": 40, "y": 20, "w": 300, "h": 14, "pages": "rest", "text": "CONTINUACIÓN {{numero}}", "size": 9})
    lay["elements"].append({"id": "logo", "type": "image", "x": 450, "y": 30, "w": 100, "h": 50, "pages": "all", "asset": "crm/doc_assets/7/logo.png"})
    lay = ql.clean_layout(lay, 7)
    pdf = quote_pdf.render_quote(_many_lines(60), {"layout": lay}, {"crm/doc_assets/7/logo.png": _png()}.__getitem__, {})
    pages = _pages(pdf)
    assert len(pages) >= 3
    assert "Golden Eventos" in pages[0] and "Golden Eventos" not in pages[1]          # «solo la primera página»
    assert "Página 1" in pages[0] and "Página 2" in pages[1]                         # «todas»: el pie y el número de página
    assert "CONTINUACIÓN" not in pages[0] and "CONTINUACIÓN 1234" in pages[1]       # «de la segunda en adelante»
    assert "Stand modular" in pages[1] and "TOTAL" in pages[-1]                       # la tabla sigue y los totales salen al final


def test_a_broken_image_does_not_break_the_pdf():
    lay = ql.clean_layout({**qf.starter("blank"), "elements": [{"type": "image", "x": 10, "y": 10, "w": 50, "h": 50, "asset": "crm/doc_assets/7/no.png"},
                                                                {"type": "text", "x": 10, "y": 80, "w": 200, "h": 14, "text": "Sigue {{cliente}}"}]}, 7)
    text = _pages(quote_pdf.render_quote(ql.SAMPLE_QUOTE, {"layout": lay}, {}.__getitem__, {}))[0]
    assert "Sigue Cliente de ejemplo" in text


@pytest.mark.parametrize("bad, fragment", [
    ({"v": 2, "elements": [{"type": "circulo"}]}, "tipo conocido"),
    ({"v": 2, "elements": [{"type": "text", "color": "rojo"}]}, "color"),
    ({"v": 2, "elements": [{"type": "image", "asset": "crm/doc_assets/9/a.png"}]}, "no es válido"),
    ({"v": 2, "elements": [{"type": "image", "asset": "crm/doc_assets/7/a.pdf"}]}, "PNG o JPG"),
    ({"v": 2, "next": {"top": 400, "bottom": 400}}, "márgenes"),
    ({"v": 2, "flow": {"x": 580, "y": 10, "w": 300, "h": 300}}, "Posición"),
    ({"v": 2, "elements": [{"type": "text"}] * 81}, "hasta 80"),
])
def test_invalid_free_layouts_are_rejected_with_a_clear_message(bad, fragment):
    with pytest.raises(CrmError) as e:
        ql.clean_layout(bad, 7)
    assert fragment in e.value.message


def test_old_block_designs_open_as_free_designs_without_losing_anything():
    v1 = ql.starter("classic")
    v2 = ql.clean_layout(qf.from_blocks(v1), 7)
    assert v2["v"] == 2 and v2["flow"]["blocks"] == ql.clean_layout(v1, 7)["blocks"] and v2["elements"] == []
    assert "Golden Eventos" in _pages(quote_pdf.render_quote(ql.SAMPLE_QUOTE, {"layout": v2}, {}.get, {}))[0]
    assert quote_pdf.render_quote(ql.SAMPLE_QUOTE, {"layout": ql.clean_layout(v1)}, {}.get, {})[:5] == b"%PDF-"          # un diseño viejo sin convertir sigue saliendo


def test_used_assets_cover_the_sheet_and_the_content():
    lay = ql.clean_layout({**qf.starter("blank"), "elements": [{"type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "asset": "crm/doc_assets/7/a.png"}],
                           "flow": {"x": 40, "y": 40, "w": 400, "h": 600, "blocks": [{"type": "logo", "asset": "crm/doc_assets/7/b.png"}]}}, 7)
    assert sorted(ql.used_assets(lay)) == ["crm/doc_assets/7/a.png", "crm/doc_assets/7/b.png"]


def test_export_and_import_carry_the_images_into_another_template(monkeypatch):
    pytest.importorskip("sqlalchemy")
    from types import SimpleNamespace
    from app.crm import doc_assets

    class Mem:
        def __init__(self):
            self.d = {}
        def put(self, k, b): self.d[k] = b
        def get(self, k): return self.d[k]
        def exists(self, k): return k in self.d
    mem = Mem()
    monkeypatch.setattr(doc_assets, "get_storage", lambda: mem)
    mem.d["crm/doc_assets/5/a.png"] = _png()
    lay = ql.clean_layout({**qf.starter("classic"), "elements": [{"type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "asset": "crm/doc_assets/5/a.png", "pages": "all"}]}, 5)
    pkg = doc_assets.export_package(SimpleNamespace(id=5, kind="quote", name="Golden"), lay)
    assert pkg["formato"] == "golden-plantilla-pdf" and list(pkg["archivos"]) == ["crm/doc_assets/5/a.png"]
    out = doc_assets.import_package(SimpleNamespace(id=9, kind="quote"), json.dumps(pkg).encode())
    new = out["layout"]["elements"][0]["asset"]
    assert new.startswith("crm/doc_assets/9/") and mem.d[new] == mem.d["crm/doc_assets/5/a.png"] and out["kind"] == "quote"
    with pytest.raises(CrmError):
        doc_assets.import_package(SimpleNamespace(id=9, kind="quote"), b'{"formato": "otro"}')
    pkg["archivos"]["crm/doc_assets/5/a.png"] = "bm8gZXMgdW5hIGltYWdlbg=="          # «no es una imagen»: se revisa por su contenido, como al subirla
    with pytest.raises(CrmError):
        doc_assets.import_package(SimpleNamespace(id=9, kind="quote"), json.dumps(pkg).encode())
    copied = doc_assets.copy_layout(SimpleNamespace(id=5, layout_json=json.dumps(lay)), SimpleNamespace(id=11))
    assert copied["elements"][0]["asset"].startswith("crm/doc_assets/11/")          # duplicar / «usar el diseño de otra plantilla» también con el diseño libre


def test_designer_page_and_list_wiring():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates/crm_plantilla.html").read_text(encoding="utf-8")
    hoja = (root / "static/js/crm_plantilla_hoja.js").read_text(encoding="utf-8")
    js = (root / "static/js/crm_plantilla.js").read_text(encoding="utf-8")
    prod = (root / "static/js/crm_productos.js").read_text(encoding="utf-8")
    assert html.index("js/crm_plantilla_hoja.js") < html.index("js/crm_plantilla.js")
    for piece in ('id="pdxPage"', 'id="pdxAddText"', 'id="pdxAddVar"', 'id="pdxAddImage"', 'id="pdxAddRect"', 'id="pdxAddLine"', 'id="pdxPageSize"', 'id="plExport"', 'id="plImport"', 'id="plImportStart"'):
        assert piece in html
    assert "pointerdown" in hoja and "pdx-handle" in hoja and "ArrowLeft" in hoja and "page_rules" in hoja
    assert "/export" in js and "/import" in js and "/doc-layout/from-blocks" in js and "PlSheet.mount" in js
    assert '"/crm/plantillas/" + made.id + "/disenar"' in prod          # una plantilla nueva abre el diseñador
    assert 't.kind === "quote" ? "/crm/plantillas/"' not in prod          # y las proformas también se diseñan
