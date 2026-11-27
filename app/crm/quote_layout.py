"""Diseño por bloques del PDF de cotización (16-nov-2026, pedido de Juan David): la plantilla es una lista de bloques que se arrastran y ordenan (logo, textos, datos, tabla de productos con foto,
totales, condiciones, imagen, línea, espacio, salto de página y «insertar un PDF aquí»). Este módulo es PURO: valida el diseño y lo convierte en bytes de PDF; no toca la base ni el disco
(los archivos llegan con `fetch(clave) -> bytes`). Lo usa app/crm/quote_pdf.py cuando la plantilla tiene `layout_json`; sin diseño sigue el PDF sencillo de siempre.

Forma del diseño: {"v": 1, "blocks": [{"id": "b1", "type": "heading", "text": "COTIZACIÓN {{numero}}", ...}, ...]}.
Los textos aceptan variables {{numero}}, {{cliente}}, {{contacto}}, {{titulo}}, {{fecha_evento}}, {{valida_hasta}}, {{subtotal}}, {{impuestos}}, {{total}}, {{moneda}}, {{hoy}}.
Los archivos (logo, imágenes, PDF a insertar) se guardan antes con el diseñador; el diseño solo lleva su clave (`crm/doc_assets/<plantilla>/<archivo>`), validada aquí."""
import io
import re
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from app.crm.errors import CrmError

VERSION = 1
MAX_BLOCKS = 60
MAX_TEXT = 5000
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
ASSET_PREFIX = "crm/doc_assets/"
PRODUCT_IMAGE_PREFIX = "crm/product_images/"

BLOCK_TYPES = {
    "logo": "Logo",
    "image": "Imagen",
    "heading": "Título",
    "text": "Texto",
    "fields": "Datos de la cotización",
    "table": "Tabla de productos",
    "totals": "Totales",
    "terms": "Condiciones comerciales",
    "line": "Línea",
    "spacer": "Espacio",
    "pagebreak": "Salto de página",
    "pdf": "Insertar un PDF",
}
FIELD_KEYS = {"cliente": "Cliente", "contacto": "Atención", "titulo": "Asunto", "numero": "Número", "fecha_evento": "Fecha del evento", "valida_hasta": "Válida hasta", "fecha": "Fecha",
              # 26-nov-2026: datos de la PROFORMA (en una cotización salen vacíos y el renglón no se dibuja)
              "evento": "Evento", "ciudad": "Ciudad", "emision": "Fecha de emisión", "vence": "Vence", "estado": "Estado"}
TABLE_COLUMNS = {"pos": "#", "foto": "Foto", "nombre": "Descripción", "cantidad": "Cant.", "precio": "Precio", "descuento": "Desc. %", "total": "Total"}
VARIABLES = ("numero", "cliente", "contacto", "titulo", "fecha_evento", "valida_hasta", "subtotal", "impuestos", "total", "moneda", "hoy")
PROFORMA_VARIABLES = ("numero", "cliente", "evento", "ciudad", "emision", "vence", "estado", "subtotal", "impuestos", "total", "moneda", "hoy")          # 26-nov-2026
ALIGNS = ("left", "center", "right")
_VAR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# ------------------------------------------------------------------------------------------------------------------------------------ diseño de fábrica
def starter(name: str = "classic") -> dict:
    """«classic» reproduce el PDF sencillo de siempre con bloques que se pueden mover; «blank» deja solo un título."""
    if name == "blank":
        return {"v": VERSION, "blocks": [{"id": "b1", "type": "heading", "text": "COTIZACIÓN N.º {{numero}}", "size": 16, "align": "left", "bold": True}]}
    return {"v": VERSION, "blocks": [
        {"id": "b1", "type": "heading", "text": "Golden Eventos y Logística S.A.S.", "size": 14, "align": "left", "bold": True},
        {"id": "b2", "type": "text", "text": "COTIZACIÓN N.º {{numero}}", "size": 11, "align": "right", "bold": True, "gray": 30},
        {"id": "b3", "type": "line"},
        {"id": "b4", "type": "fields", "items": ["cliente", "contacto", "titulo", "fecha_evento", "valida_hasta"]},
        {"id": "b5", "type": "spacer", "height": 8},
        {"id": "b6", "type": "text", "text": "", "size": 10, "align": "left"},
        {"id": "b7", "type": "table", "columns": ["pos", "nombre", "cantidad", "precio", "descuento", "total"]},
        {"id": "b8", "type": "totals"},
        {"id": "b9", "type": "terms"},
    ]}


# ------------------------------------------------------------------------------------------------------------------------------------ validación
def _num(value, name: str, low: float, high: float, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise CrmError(f"«{name}» debe ser un número.")
    if n != n or n < low or n > high:
        raise CrmError(f"«{name}» debe estar entre {low:g} y {high:g}.")
    return n


def _text(value, name: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CrmError(f"«{name}» debe ser texto.")
    v = value.replace("\r", "").strip("\n")
    if len(v) > limit:
        raise CrmError(f"«{name}» es demasiado largo (máximo {limit} caracteres).")
    return v


def _asset(value, template_id: Optional[int], what: str) -> str:
    if not isinstance(value, str) or not value:
        raise CrmError(f"Falta el archivo de «{what}».")
    ok = value.startswith(ASSET_PREFIX) and ".." not in value and (template_id is None or value.startswith(f"{ASSET_PREFIX}{template_id}/"))
    if not ok or len(value) > 300:
        raise CrmError(f"El archivo de «{what}» no es válido: súbelo de nuevo desde el diseñador.")
    return value


def clean_layout(data, template_id: Optional[int] = None) -> dict:
    """Valida y normaliza un diseño recibido del navegador. Lanza CrmError con un mensaje claro; nunca confía en tipos ni tamaños."""
    if isinstance(data, dict) and data.get("v") == 2:          # 26-nov-2026: diseño libre sobre la hoja (app/crm/quote_free.py)
        from app.crm import quote_free
        return quote_free.clean(data, template_id)
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        raise CrmError("El diseño no tiene el formato correcto.")
    if len(data["blocks"]) > MAX_BLOCKS:
        raise CrmError(f"Un diseño admite hasta {MAX_BLOCKS} bloques.")
    out, seen = [], set()
    for i, raw in enumerate(data["blocks"], 1):
        if not isinstance(raw, dict) or raw.get("type") not in BLOCK_TYPES:
            raise CrmError(f"El bloque {i} no es de un tipo conocido.")
        t = raw["type"]
        bid = raw.get("id") if isinstance(raw.get("id"), str) and _ID.match(raw.get("id") or "") else f"b{i}"
        while bid in seen:
            bid += "x"
        seen.add(bid)
        b: dict = {"id": bid, "type": t}
        align = raw.get("align") if raw.get("align") in ALIGNS else "left"
        if t in ("heading", "text"):
            b.update(text=_text(raw.get("text"), "Texto"), size=_num(raw.get("size"), "Tamaño", 6, 48, 16 if t == "heading" else 10), align=align,
                     bold=bool(raw.get("bold", t == "heading")), gray=int(_num(raw.get("gray"), "Gris", 0, 80, 0)))
        elif t in ("logo", "image"):
            b.update(asset=_asset(raw.get("asset"), template_id, BLOCK_TYPES[t]), width=_num(raw.get("width"), "Ancho", 20, 515, 140 if t == "logo" else 300), align=align)
        elif t == "fields":
            items = raw.get("items") if isinstance(raw.get("items"), list) else []
            b["items"] = [k for k in items if k in FIELD_KEYS][:10]
        elif t == "table":
            cols = raw.get("columns") if isinstance(raw.get("columns"), list) else []
            cols = [c for i2, c in enumerate(cols) if c in TABLE_COLUMNS and c not in cols[:i2]]
            if "nombre" not in cols:
                cols.insert(0, "nombre")
            b.update(columns=cols, photo_size=_num(raw.get("photo_size"), "Tamaño de la foto", 24, 120, 56))
        elif t == "terms":
            b["title"] = _text(raw.get("title"), "Título de las condiciones", 120) or "Condiciones comerciales"
        elif t == "spacer":
            b["height"] = _num(raw.get("height"), "Alto", 2, 200, 12)
        elif t == "pdf":
            pages = _text(raw.get("pages"), "Páginas", 40)
            if pages and not re.match(r"^\d+(-\d+)?(,\s*\d+(-\d+)?)*$", pages):
                raise CrmError("Las páginas del PDF se escriben así: 1-3 o 1,3,5 (déjalo vacío para todas).")
            b.update(asset=_asset(raw.get("asset"), template_id, "PDF a insertar"), pages=pages, name=_text(raw.get("name"), "Nombre del PDF", 120))
        out.append(b)
    return {"v": VERSION, "blocks": out}


def used_assets(layout: Optional[dict]) -> List[str]:
    from app.crm import quote_free
    return quote_free.used_assets(layout)


# ------------------------------------------------------------------------------------------------------------------------------------ archivos subidos
def check_image(raw: bytes) -> dict:
    """Valida una imagen subida (PNG o JPEG real, no más de 3 MB) y devuelve {ext, width, height}. No acepta SVG ni otros formatos."""
    from PIL import Image, UnidentifiedImageError
    if len(raw) > MAX_IMAGE_BYTES:
        raise CrmError("La imagen pesa más de 3 MB: usa una más liviana.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.verify()
        with Image.open(io.BytesIO(raw)) as im:
            fmt, w, h = im.format, im.width, im.height
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise CrmError("No se pudo leer la imagen: sube un archivo PNG o JPG.")
    if fmt not in ("PNG", "JPEG"):
        raise CrmError("Solo se aceptan imágenes PNG o JPG.")
    if w * h > 40_000_000:
        raise CrmError("La imagen es demasiado grande (más de 40 megapíxeles).")
    return {"ext": "png" if fmt == "PNG" else "jpg", "width": w, "height": h}


def check_pdf(raw: bytes) -> dict:
    """Valida un PDF subido para insertarlo: formato real, sin contraseña, hasta 10 MB y 100 páginas. Devuelve {pages}."""
    if len(raw) > MAX_PDF_BYTES:
        raise CrmError("El PDF pesa más de 10 MB: usa uno más liviano.")
    if not raw.lstrip()[:5] == b"%PDF-":
        raise CrmError("El archivo no es un PDF.")
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise CrmError("El PDF tiene contraseña: quítale la protección para poder insertarlo.")
        pages = len(reader.pages)
    except CrmError:
        raise
    except Exception:          # noqa: BLE001 - cualquier PDF dañado se explica igual
        raise CrmError("No se pudo leer el PDF: puede estar dañado.")
    if pages < 1 or pages > MAX_PDF_PAGES:
        raise CrmError(f"El PDF debe tener entre 1 y {MAX_PDF_PAGES} páginas.")
    return {"pages": pages}


def page_numbers(spec: str, total: int) -> List[int]:
    """«1-3, 5» → [0, 1, 2, 4] (índices base 0, sin pasarse del total). Vacío = todas."""
    if not spec:
        return list(range(total))
    out: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
        else:
            lo = hi = int(part)
        for n in range(max(1, lo), min(total, hi) + 1):
            if n - 1 not in out:
                out.append(n - 1)
    return out


# ------------------------------------------------------------------------------------------------------------------------------------ variables
def money(value, currency: str = "COP") -> str:
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, frac = f"{abs(d):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return ("-" if d < 0 else "") + ".".join(groups) + "," + frac + (" " + currency if currency else "")


def qty(value) -> str:
    d = Decimal(str(value))
    return str(int(d)) if d == d.to_integral() else f"{d:.2f}".replace(".", ",")


def day(iso: Optional[str]) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def context(q: dict, today_iso: str) -> Dict[str, str]:
    cur = q.get("currency") or "COP"
    return {"numero": str(q.get("number", "")) + (f" (versión {q['version']})" if (q.get("version") or 1) > 1 else ""), "cliente": q.get("account_name") or "", "contacto": q.get("contact_name") or "",
            "titulo": q.get("title") or "", "fecha_evento": day(q.get("event_start")), "valida_hasta": day(q.get("valid_until")), "subtotal": money(q.get("subtotal", 0), cur),
            "impuestos": money(q.get("tax_total", 0), cur), "total": money(q.get("total", 0), cur), "moneda": cur, "hoy": day(today_iso)}


def fill(text: str, ctx: Dict[str, str]) -> str:
    """Reemplaza {{variables}}; una variable desconocida se deja tal cual (así el error se ve en la vista previa)."""
    return _VAR.sub(lambda m: ctx.get(m.group(1), m.group(0)), text or "")


# ------------------------------------------------------------------------------------------------------------------------------------ PDF
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _image(raw: bytes, width: float, max_h: float = 700, max_w: float = 515):
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image
    iw, ih = ImageReader(io.BytesIO(raw)).getSize()
    w = min(width, max_w)
    h = w * ih / iw if iw else w
    if h > max_h:
        w, h = w * max_h / h, max_h
    return Image(io.BytesIO(raw), width=w, height=h)


def _segment(story: list, title: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40, title=title, author="Golden Eventos y Logística S.A.S.").build(story or [_spacer(1)])
    return buf.getvalue()


def _spacer(h: float):
    from reportlab.platypus import Spacer
    return Spacer(1, h)


def render(layout: dict, q: dict, fetch: Callable[[str], bytes], images: Optional[Dict[int, bytes]] = None, today_iso: str = "", ctx: Optional[Dict[str, str]] = None) -> bytes:
    """Diseño por bloques (v1) o diseño libre sobre la hoja (v2, app/crm/quote_free.py)."""
    if (layout or {}).get("v") == 2:
        from app.crm import quote_free
        return quote_free.render(layout, q, fetch, images, today_iso, ctx)
    return render_blocks(layout.get("blocks", []), q, fetch, images, today_iso, ctx)


def render_blocks(blocks: list, q: dict, fetch: Callable[[str], bytes], images: Optional[Dict[int, bytes]] = None, today_iso: str = "", ctx: Optional[Dict[str, str]] = None,
                  width: float = 515, make_segment: Optional[Callable] = None, max_height: float = 700) -> bytes:
    """Arma el PDF. `q`: detalle de la cotización (quotes.quote_detail). `fetch(clave)`: bytes de un archivo guardado. `images`: {id de producto: bytes de su foto}. Los fallos de UN archivo
    (borrado, dañado) no tumban el PDF: ese bloque se omite."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Table, TableStyle
    import logging
    log = logging.getLogger("golden.crm_layout")
    ctx = ctx if ctx is not None else context(q, today_iso)
    images = images or {}
    title = f"Cotización {q.get('number', '')}"
    first = [True]

    def flush(story_part: list) -> bytes:          # cada tramo de bloques entre PDF insertados es un PDF; v2 dibuja la hoja diseñada solo en el primero
        out = make_segment(story_part, first[0]) if make_segment else _segment(story_part, title)
        first[0] = False
        return out
    al = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
    base = {}

    def style(size: float, bold: bool = False, align: str = "left", gray: int = 0) -> ParagraphStyle:
        key = (size, bold, align, gray)
        if key not in base:
            base[key] = ParagraphStyle(f"s{len(base)}", fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size * 1.3, alignment=al[align], textColor=colors.Color(gray / 100, gray / 100, gray / 100))
        return base[key]

    segments: List[bytes] = []
    story: list = []
    for b in blocks:
        t = b["type"]
        try:
            if t in ("heading", "text"):
                txt = fill(b.get("text", ""), ctx)
                if txt.strip():
                    story.append(Paragraph(_esc(txt), style(b.get("size", 10), b.get("bold", False), b.get("align", "left"), b.get("gray", 0))))
                    story.append(_spacer(4))
            elif t in ("logo", "image"):
                img = _image(fetch(b["asset"]), b.get("width", 200), min(700, max_height - 12), max_w=width)
                img.hAlign = b.get("align", "left").upper()
                story.append(img)
                story.append(_spacer(6))
            elif t == "fields":
                rows = []
                for k in b.get("items", []):
                    v = ctx.get("numero") if k == "numero" else ctx.get("hoy") if k == "fecha" else ctx.get(k)
                    if v:
                        rows.append([Paragraph(_esc(FIELD_KEYS[k]), style(9, True, gray=30)), Paragraph(_esc(v), style(10))])
                if rows:
                    tb = Table(rows, colWidths=[110, max(60, width - 110)])
                    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
                    story.append(tb)
                    story.append(_spacer(6))
            elif t == "table":
                story.append(_lines_table(b, q, images, style, colors, Paragraph, Table, TableStyle, width))
                story.append(_spacer(8))
            elif t == "totals":
                cur = q.get("currency") or "COP"
                rows = [[Paragraph(_esc(lbl), style(10, bold, "right")), Paragraph(_esc(money(q.get(key, 0), cur)), style(10, bold, "right"))]
                        for lbl, key, bold in (("Subtotal con descuento", "subtotal", False), ("Impuestos", "tax_total", False), ("TOTAL", "total", True))]
                tb = Table(rows, colWidths=[max(60, width - 170), 170])
                tb.setStyle(TableStyle([("LINEABOVE", (0, 2), (-1, 2), 0.6, colors.grey), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
                story.append(tb)
                story.append(_spacer(8))
            elif t == "terms":
                if q.get("terms_text"):
                    story.append(Paragraph(_esc(b.get("title") or "Condiciones comerciales"), style(10, True)))
                    story.append(Paragraph(_esc(q["terms_text"]), style(9)))
                    story.append(_spacer(8))
            elif t == "line":
                story.append(HRFlowable(width="100%", thickness=0.8, color=colors.Color(0.5, 0.5, 0.5), spaceBefore=4, spaceAfter=8))
            elif t == "spacer":
                story.append(_spacer(b.get("height", 12)))
            elif t == "pagebreak":
                story.append(PageBreak())
            elif t == "pdf":
                segments.append(flush(story))
                story = []
                segments.append(("pdf", fetch(b["asset"]), b.get("pages", "")))
        except Exception:          # noqa: BLE001 - un archivo roto no tumba el PDF
            log.error("bloque %s (%s) omitido en el PDF de la cotización", b.get("id"), t, exc_info=True)
    if story or not segments:
        segments.append(flush(story))
    if len(segments) == 1 and isinstance(segments[0], bytes):
        return segments[0]
    return _merge(segments, log)


def _merge(segments: list, log) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for seg in segments:
        try:
            if isinstance(seg, bytes):
                r = PdfReader(io.BytesIO(seg))
                for p in r.pages:
                    w.add_page(p)
            else:
                r = PdfReader(io.BytesIO(seg[1]))
                for i in page_numbers(seg[2], len(r.pages)):
                    w.add_page(r.pages[i])
        except Exception:          # noqa: BLE001
            log.error("no se pudo unir un PDF insertado", exc_info=True)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _lines_table(b: dict, q: dict, images: Dict[int, bytes], style, colors, Paragraph, Table, TableStyle, width: float = 515):
    cols = b.get("columns") or ["pos", "nombre", "cantidad", "precio", "descuento", "total"]
    ps = float(b.get("photo_size", 56))
    weights = {"pos": 22, "foto": ps + 8, "nombre": 0, "cantidad": 40, "precio": 70, "descuento": 42, "total": 78}
    fixed = sum(weights[c] for c in cols if c != "nombre")
    weights["nombre"] = max(80, width - fixed)
    widths = [weights[c] for c in cols]
    right = {"cantidad", "precio", "descuento", "total"}

    def cell(c, ln):
        if c == "pos":
            return Paragraph(str(ln["position"]), style(9))
        if c == "foto":
            raw = images.get(ln.get("product_id")) if ln.get("product_id") else None
            return _image(raw, ps, ps) if raw else ""
        if c == "nombre":
            return Paragraph("<b>" + _esc(ln["name"]) + "</b>" + (("<br/>" + _esc(ln["description"])) if ln.get("description") else ""), style(9))
        if c == "cantidad":
            return Paragraph(qty(ln["qty"]), style(9, align="right"))
        if c == "precio":
            return Paragraph(money(ln["unit_price"], ""), style(9, align="right"))
        if c == "descuento":
            return Paragraph(qty(ln["discount_percent"]), style(9, align="right"))
        return Paragraph(money(ln["line_total"], ""), style(9, align="right"))
    head = [Paragraph(TABLE_COLUMNS[c], style(9, True, "right" if c in right else "left")) for c in cols]
    rows = [head] + [[cell(c, ln) for c in cols] for ln in q.get("lines", [])]
    tb = Table(rows, colWidths=widths, repeatRows=1)
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return tb


SAMPLE_QUOTE = {
    "number": 1234, "version": 1, "title": "Congreso empresarial 2027", "account_name": "Cliente de ejemplo S.A.S.", "contact_name": "Ana Pérez", "event_start": "2027-03-15", "valid_until": "2027-01-31",
    "currency": "COP", "subtotal": "5400000.00", "tax_total": "1026000.00", "total": "6426000.00", "terms_text": "50% de anticipo y 50% contra entrega. Los precios incluyen montaje y desmontaje.",
    "lines": [
        {"position": 1, "product_id": None, "name": "Stand modular 3x3", "description": "Estructura, iluminación y rótulo", "qty": "2", "unit_price": "1800000.00", "discount_percent": "0", "line_total": "3600000.00"},
        {"position": 2, "product_id": None, "name": "Personal de apoyo", "description": "Atención y registro de asistentes", "qty": "6", "unit_price": "300000.00", "discount_percent": "0", "line_total": "1800000.00"},
    ],
}


# ------------------------------------------------------------------------------------------------------------------------------------ proforma (26-nov-2026)
PROFORMA_STATUS = {"no_pagado": "No pagado", "pagado": "Pagado", "anulado": "Anulado"}


def proforma_doc(p: dict, q: Optional[dict] = None) -> dict:
    """La proforma con la forma de una cotización (así sirven los mismos bloques: datos, tabla de productos, totales). Los productos vienen de su cotización, si tiene."""
    q = q or {}
    return {"number": p.get("number", ""), "version": 1, "title": p.get("event_name") or "", "account_name": p.get("account_name") or "", "currency": p.get("currency") or "COP",
            "subtotal": q.get("subtotal", p.get("total", 0)), "tax_total": q.get("tax_total", 0), "total": p.get("total", 0), "terms_text": "", "lines": q.get("lines", [])}


def proforma_context(p: dict, q: Optional[dict], today_iso: str) -> Dict[str, str]:
    doc = proforma_doc(p, q)
    ctx = context(doc, today_iso)
    ctx.update({"evento": p.get("event_name") or "", "ciudad": p.get("city") or "", "emision": day(p.get("issued_at")), "vence": day(p.get("due_at")),
                "estado": PROFORMA_STATUS.get(p.get("status"), p.get("status") or ""), "titulo": "", "contacto": "", "fecha_evento": "", "valida_hasta": ""})
    return ctx


SAMPLE_PROFORMA = {"number": 567, "account_name": "Cliente de ejemplo S.A.S.", "event_name": "Congreso empresarial 2027", "city": "Bogotá", "issued_at": "2027-01-10", "due_at": "2027-02-10",
                   "status": "no_pagado", "currency": "COP", "total": "6426000.00"}
