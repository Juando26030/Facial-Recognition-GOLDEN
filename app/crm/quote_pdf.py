"""PDF de cotización y de proforma (C3). `render_quote` y `render_proforma` son PURAS (reciben dicts, devuelven bytes); `store_*` guardan el resultado con `get_storage()` bajo `crm/` y lo recuerdan en la fila.
DECISIÓN: plantilla sencilla (encabezado, saludo, tabla de líneas, totales, condiciones, pie) con los textos de `crm_doc_templates`; sin logo hasta que Juan David lo entregue; sin Word (.docx)."""
from decimal import Decimal
from typing import Optional

from app.crm.pdfdoc import MARGIN, PAGE_W, Doc, text_width, wrap
from app.timeutil import utcnow

COMPANY = "Golden Eventos y Logística S.A.S."
CONTENT_W = PAGE_W - 2 * MARGIN


def fmt_money(value, currency: str = "COP") -> str:
    """1234567.5 → «1.234.567,50» (separador de miles punto, decimal coma) con el código de moneda."""
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, frac = f"{abs(d):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return ("-" if d < 0 else "") + ".".join(groups) + "," + frac + " " + currency


def fmt_qty(value) -> str:
    d = Decimal(str(value))
    return str(int(d)) if d == d.to_integral() else f"{d:.2f}".replace(".", ",")


def fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def _head(doc: Doc, kind_label: str, number_text: str, tpl: Optional[dict]) -> None:
    doc.text(MARGIN, doc.y - 14, COMPANY, 14, bold=True)
    doc.text(PAGE_W - MARGIN - text_width(kind_label, 14, True), doc.y - 14, kind_label, 14, bold=True)
    doc.y -= 30
    doc.text(PAGE_W - MARGIN - text_width(number_text, 10), doc.y, number_text, 10, gray=0.3)
    if tpl and tpl.get("header_text"):
        doc.paragraph(tpl["header_text"], 9, gray=0.3, gap=2)
    doc.line(MARGIN, doc.y - 4, PAGE_W - MARGIN, doc.y - 4, 0.8, 0.5)
    doc.y -= 14


def _pair(doc: Doc, label: str, value: Optional[str]) -> None:
    if not value:
        return
    for i, ln in enumerate(wrap(str(value), 10, CONTENT_W - 110)):
        doc.need(14)
        doc.y -= 13
        if i == 0:
            doc.text(MARGIN, doc.y, label, 9, bold=True, gray=0.3)
        doc.text(MARGIN + 110, doc.y, ln, 10)


def render_quote(q: dict, tpl: Optional[dict] = None) -> bytes:
    """`q`: el detalle de la cotización (quotes.quote_detail). El nombre del contacto solo aparece si la cotización todavía lo tiene."""
    doc = Doc(f"Cotización {q['number']}")
    _head(doc, "COTIZACIÓN", f"N.º {q['number']}" + (f" · versión {q['version']}" if q["version"] > 1 else ""), tpl)
    _pair(doc, "Cliente", q.get("account_name"))
    _pair(doc, "Atención", q.get("contact_name"))
    _pair(doc, "Asunto", q["title"])
    _pair(doc, "Fecha del evento", fmt_date(q.get("event_start")))
    _pair(doc, "Válida hasta", fmt_date(q.get("valid_until")))
    doc.y -= 8
    if tpl and tpl.get("greeting_text"):
        doc.paragraph(tpl["greeting_text"], 10, gap=8)
    widths = [26, 215, 50, 80, 40, 90]
    aligns = ["l", "l", "r", "r", "r", "r"]
    doc.table_row(["#", "Descripción", "Cant.", "Precio", "Desc.%", "Total"], widths, aligns, 9, True, shade=True)
    for ln in q["lines"]:
        name = ln["name"] + (("\n" + ln["description"]) if ln.get("description") else "")
        doc.table_row([ln["position"], name, fmt_qty(ln["qty"]), fmt_money(ln["unit_price"], ""), fmt_qty(ln["discount_percent"]), fmt_money(ln["line_total"], "")], widths, aligns, 9)
    doc.y -= 8
    cur = q["currency"]
    for label, key, bold in (("Subtotal con descuento", "subtotal", False), ("Impuestos", "tax_total", False), ("TOTAL", "total", True)):
        doc.need(16)
        doc.y -= 14
        txt = fmt_money(q[key], cur)
        doc.text(PAGE_W - MARGIN - text_width(txt, 10, bold), doc.y, txt, 10, bold)
        doc.text(PAGE_W - MARGIN - 190, doc.y, label, 10, bold)
    doc.y -= 12
    if q.get("terms_text"):
        doc.paragraph("Condiciones comerciales", 10, True, gap=2)
        doc.paragraph(q["terms_text"], 9, gap=8)
    if tpl and tpl.get("footer_text"):
        doc.paragraph(tpl["footer_text"], 9, gray=0.3)
    return doc.render()


def render_proforma(p: dict, q: Optional[dict] = None, tpl: Optional[dict] = None) -> bytes:
    doc = Doc(f"Proforma {p['number']}")
    _head(doc, "PROFORMA", f"N.º {p['number']}", tpl)
    _pair(doc, "Cliente", p.get("account_name"))
    _pair(doc, "Evento", p.get("event_name"))
    _pair(doc, "Ciudad", p.get("city"))
    _pair(doc, "Fecha de emisión", fmt_date(p.get("issued_at")))
    _pair(doc, "Vence", fmt_date(p.get("due_at")))
    _pair(doc, "Estado", {"no_pagado": "No pagado", "pagado": "Pagado", "anulado": "Anulado"}.get(p["status"], p["status"]))
    doc.y -= 8
    if tpl and tpl.get("greeting_text"):
        doc.paragraph(tpl["greeting_text"], 10, gap=8)
    if q:
        widths = [26, 285, 50, 80, 90]
        aligns = ["l", "l", "r", "r", "r"]
        doc.table_row(["#", "Descripción", "Cant.", "Precio", "Total"], widths, aligns, 9, True, shade=True)
        for ln in q["lines"]:
            doc.table_row([ln["position"], ln["name"], fmt_qty(ln["qty"]), fmt_money(ln["unit_price"], ""), fmt_money(ln["line_total"], "")], widths, aligns, 9)
        doc.y -= 8
    txt = fmt_money(p["total"], p["currency"])
    doc.need(20)
    doc.y -= 16
    doc.text(PAGE_W - MARGIN - text_width(txt, 11, True), doc.y, txt, 11, True)
    doc.text(PAGE_W - MARGIN - 190, doc.y, "TOTAL A PAGAR", 11, True)
    doc.y -= 12
    if tpl and tpl.get("footer_text"):
        doc.paragraph(tpl["footer_text"], 9, gray=0.3)
    return doc.render()


LAYOUT = 2          # súbelo cuando cambie el diseño o los rótulos del PDF: los guardados con otro número se regeneran solos (v2: «Subtotal con descuento»)


def quote_key(q) -> str:
    return f"crm/quotes/{q.id}/cotizacion-{q.number}-v{q.version}-d{LAYOUT}.pdf"


def proforma_key(p) -> str:
    return f"crm/proformas/{p.id}/proforma-{p.number}-d{LAYOUT}.pdf"


def stamp() -> object:
    return utcnow()
