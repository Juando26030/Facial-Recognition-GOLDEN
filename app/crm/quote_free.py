"""Diseño LIBRE del PDF de cotización y de proforma (v2; 26-nov-2026, pedido de Juan David: «armar el PDF como armo los certificados o las escarapelas»).

La hoja (A4 o Carta) lleva elementos que se ponen donde se quiera: textos (con datos como {{cliente}} o {{total}}), imágenes, rectángulos y líneas. Cada elemento sale en la
primera página, en todas o de la segunda en adelante (encabezados y pies que se repiten). El contenido que crece (datos, tabla de productos, totales, condiciones, PDF insertado)
va en UN recuadro, «flow», que también se mueve y se cambia de tamaño en la hoja: si no cabe, sigue en la página siguiente entre los márgenes de `next`.

Forma: {"v": 2, "page": "a4" | "letter",
        "flow": {"x", "y", "w", "h", "blocks": [bloques del diseño por bloques (app/crm/quote_layout.py)]},
        "next": {"top", "bottom"},                     # márgenes del contenido en las páginas siguientes
        "elements": [{"id", "type": "text" | "image" | "rect" | "line", "x", "y", "w", "h", "pages": "first" | "all" | "rest", ...}]}
Medidas en puntos (1 pt = 0,3528 mm), origen ARRIBA a la izquierda (como en la pantalla); al dibujar se pasa al origen de abajo de ReportLab.
Módulo PURO, como quote_layout: valida y dibuja; los archivos llegan con `fetch(clave) -> bytes`."""
import io
import logging
import re
from typing import Callable, Dict, List, Optional

from app.crm import quote_layout as ql
from app.crm.errors import CrmError

VERSION = 2
PAGES = {"a4": (595.28, 841.89), "letter": (612.0, 792.0)}
PAGE_LABELS = {"a4": "A4", "letter": "Carta"}
ELEMENT_TYPES = {"text": "Texto", "image": "Imagen", "rect": "Rectángulo", "line": "Línea"}
PAGE_RULES = {"first": "Solo la primera página", "all": "Todas las páginas", "rest": "De la segunda página en adelante"}
FONTS = {(False, False): "Helvetica", (True, False): "Helvetica-Bold", (False, True): "Helvetica-Oblique", (True, True): "Helvetica-BoldOblique"}
MAX_ELEMENTS = 80
MIN_FLOW = 60
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
log = logging.getLogger("golden.crm_layout")


# ------------------------------------------------------------------------------------------------------------------------------------ diseños de fábrica
def starter(name: str = "classic", kind: str = "quote") -> dict:
    """«classic»: encabezado con el nombre de la empresa y el número arriba y el contenido de siempre debajo; «blank»: la hoja vacía con el recuadro del contenido."""
    w, h = PAGES["letter"]
    label = "PROFORMA" if kind == "proforma" else "COTIZACIÓN"
    blocks = ql.starter("classic")["blocks"][3:] if kind != "proforma" else [
        {"id": "b4", "type": "fields", "items": ["cliente", "evento", "ciudad", "emision", "vence", "estado"]},
        {"id": "b5", "type": "spacer", "height": 8},
        {"id": "b7", "type": "table", "columns": ["pos", "nombre", "cantidad", "precio", "total"]},
        {"id": "b8", "type": "totals"}]
    flow = {"x": 40, "y": 120, "w": w - 80, "h": h - 120 - 60, "blocks": blocks}
    if name == "blank":
        return {"v": VERSION, "page": "letter", "flow": {**flow, "y": 60, "h": h - 120, "blocks": []}, "next": {"top": 40, "bottom": 40}, "elements": []}
    return {"v": VERSION, "page": "letter", "flow": flow, "next": {"top": 60, "bottom": 50}, "elements": [
        {"id": "e1", "type": "text", "x": 40, "y": 40, "w": 300, "h": 24, "pages": "first", "text": "Golden Eventos y Logística S.A.S.", "size": 14, "bold": True, "italic": False,
         "align": "left", "color": "#1b1f3b"},
        {"id": "e2", "type": "text", "x": w - 260, "y": 40, "w": 220, "h": 20, "pages": "first", "text": label + " N.º {{numero}}", "size": 12, "bold": True, "italic": False,
         "align": "right", "color": "#1b1f3b"},
        {"id": "e3", "type": "text", "x": w - 260, "y": 62, "w": 220, "h": 16, "pages": "first", "text": "{{hoy}}", "size": 9, "bold": False, "italic": False, "align": "right",
         "color": "#555555"},
        {"id": "e4", "type": "line", "x": 40, "y": 96, "w": w - 80, "h": 1.5, "pages": "first", "color": "#b8862b"},
        {"id": "e5", "type": "text", "x": 40, "y": h - 36, "w": w - 80, "h": 14, "pages": "all", "text": "Página {{pagina}}", "size": 8, "bold": False, "italic": False,
         "align": "center", "color": "#777777"},
    ]}


def from_blocks(layout: dict) -> dict:
    """Pasa un diseño por bloques (v1) al formato libre SIN perder nada: todos sus bloques van, en el mismo orden, dentro del recuadro del contenido a toda la hoja A4
    (los márgenes de siempre, 40 pt). Así se ve igual que antes y desde ahí se puede mover."""
    w, h = PAGES["a4"]
    return {"v": VERSION, "page": "a4", "flow": {"x": 40, "y": 40, "w": w - 80, "h": h - 80, "blocks": list((layout or {}).get("blocks", []))},
            "next": {"top": 40, "bottom": 40}, "elements": []}


# ------------------------------------------------------------------------------------------------------------------------------------ validación
def _color(value, name: str, default: str = "") -> str:
    if value in (None, ""):
        return default
    if not isinstance(value, str) or not _HEX.match(value):
        raise CrmError(f"El color de «{name}» no es válido.")
    return value.lower()


def clean(data: dict, template_id: Optional[int] = None) -> dict:
    """Valida un diseño libre recibido del navegador (nunca confía en tipos ni tamaños). Lanza CrmError con un mensaje claro."""
    page = data.get("page") if data.get("page") in PAGES else "a4"
    pw, ph = PAGES[page]
    flow_raw = data.get("flow") if isinstance(data.get("flow"), dict) else {}
    fx = ql._num(flow_raw.get("x"), "Posición del contenido", 0, pw - MIN_FLOW, 40)
    fy = ql._num(flow_raw.get("y"), "Posición del contenido", 0, ph - MIN_FLOW, 40)
    fw = ql._num(flow_raw.get("w"), "Ancho del contenido", MIN_FLOW, pw, pw - 80)
    fh = ql._num(flow_raw.get("h"), "Alto del contenido", MIN_FLOW, ph, ph - 80)
    fw, fh = min(fw, pw - fx), min(fh, ph - fy)
    if fw < MIN_FLOW or fh < MIN_FLOW:
        raise CrmError("El recuadro del contenido quedó demasiado pequeño o fuera de la hoja.")
    blocks = ql.clean_layout({"blocks": flow_raw.get("blocks") if isinstance(flow_raw.get("blocks"), list) else []}, template_id)["blocks"]
    nxt = data.get("next") if isinstance(data.get("next"), dict) else {}
    top = ql._num(nxt.get("top"), "Margen de arriba en las páginas siguientes", 0, ph / 2, 40)
    bottom = ql._num(nxt.get("bottom"), "Margen de abajo en las páginas siguientes", 0, ph / 2, 40)
    if ph - top - bottom < MIN_FLOW:
        raise CrmError("Los márgenes de las páginas siguientes no dejan espacio para el contenido.")
    raw_elements = data.get("elements") if isinstance(data.get("elements"), list) else []
    if len(raw_elements) > MAX_ELEMENTS:
        raise CrmError(f"Una hoja admite hasta {MAX_ELEMENTS} elementos.")
    elements, seen = [], set()
    for i, raw in enumerate(raw_elements, 1):
        if not isinstance(raw, dict) or raw.get("type") not in ELEMENT_TYPES:
            raise CrmError(f"El elemento {i} no es de un tipo conocido.")
        t = raw["type"]
        eid = raw.get("id") if isinstance(raw.get("id"), str) and _ID.match(raw.get("id") or "") else f"e{i}"
        while eid in seen:
            eid += "x"
        seen.add(eid)
        e = {"id": eid, "type": t, "pages": raw.get("pages") if raw.get("pages") in PAGE_RULES else "first",
             "x": ql._num(raw.get("x"), "Posición", -pw, pw, 40), "y": ql._num(raw.get("y"), "Posición", -ph, ph, 40),
             "w": ql._num(raw.get("w"), "Ancho", 1, pw * 2, 120), "h": ql._num(raw.get("h"), "Alto", 0.3, ph * 2, 20)}
        if t == "text":
            e.update(text=ql._text(raw.get("text"), "Texto"), size=ql._num(raw.get("size"), "Tamaño de la letra", 5, 96, 11), bold=bool(raw.get("bold")), italic=bool(raw.get("italic")),
                     align=raw.get("align") if raw.get("align") in ql.ALIGNS else "left", color=_color(raw.get("color"), "Texto", "#000000"),
                     line=ql._num(raw.get("line"), "Interlineado", 0.8, 3, 1.25))
        elif t == "image":
            e["asset"] = ql._asset(raw.get("asset"), template_id, "Imagen")
            if not e["asset"].lower().endswith((".png", ".jpg")):
                raise CrmError("En la hoja solo van imágenes PNG o JPG (un PDF se inserta dentro del contenido).")
        elif t == "rect":
            e.update(fill=_color(raw.get("fill"), "Relleno"), stroke=_color(raw.get("stroke"), "Borde"), stroke_w=ql._num(raw.get("stroke_w"), "Grosor del borde", 0, 20, 0),
                     radius=ql._num(raw.get("radius"), "Esquinas redondeadas", 0, 100, 0))
        elif t == "line":
            e.update(color=_color(raw.get("color"), "Línea", "#000000"), vertical=bool(raw.get("vertical")))
        elements.append(e)
    return {"v": VERSION, "page": page, "flow": {"x": fx, "y": fy, "w": fw, "h": fh, "blocks": blocks}, "next": {"top": top, "bottom": bottom}, "elements": elements}


def asset_lists(layout: Optional[dict]) -> List[list]:
    """Las listas del diseño que tienen archivos (bloques del contenido y elementos de la hoja), para copiarlas, exportarlas o importarlas."""
    if not layout:
        return []
    if layout.get("v") == 2:
        return [layout.get("flow", {}).get("blocks", []), layout.get("elements", [])]
    return [layout.get("blocks", [])]


def used_assets(layout: Optional[dict]) -> List[str]:
    return [item["asset"] for lst in asset_lists(layout) for item in lst if isinstance(item, dict) and item.get("asset")]


# ------------------------------------------------------------------------------------------------------------------------------------ PDF
def _rgb(hex_color: str):
    from reportlab.lib import colors
    return colors.HexColor(hex_color)


def _draw_elements(c, layout: dict, ctx: Dict[str, str], fetch: Callable[[str], bytes], page_no: int, cache: dict) -> None:
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Paragraph
    _, ph = PAGES[layout["page"]]
    al = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
    for e in layout.get("elements", []):
        rule = e.get("pages", "first")
        if (rule == "first" and page_no != 1) or (rule == "rest" and page_no == 1):
            continue
        x, y, w, h = e["x"], e["y"], e["w"], e["h"]
        try:
            c.saveState()
            if e["type"] == "text":
                text = ql.fill(e.get("text", ""), {**ctx, "pagina": str(page_no)})
                if text.strip():
                    st = ParagraphStyle(f"e{e['id']}", fontName=FONTS[(bool(e.get("bold")), bool(e.get("italic")))], fontSize=e["size"], leading=e["size"] * e.get("line", 1.25),
                                        alignment=al[e.get("align", "left")], textColor=_rgb(e.get("color") or "#000000"))
                    p = Paragraph(ql._esc(text), st)
                    _, th = p.wrap(w, 10_000)
                    p.drawOn(c, x, ph - y - th)
            elif e["type"] == "image":
                key = e["asset"]
                if key not in cache:
                    cache[key] = ImageReader(io.BytesIO(fetch(key)))
                c.drawImage(cache[key], x, ph - y - h, w, h, preserveAspectRatio=True, anchor="c", mask="auto")
            elif e["type"] == "rect":
                fill, stroke, sw = e.get("fill"), e.get("stroke"), e.get("stroke_w", 0)
                if fill:
                    c.setFillColor(_rgb(fill))
                if stroke and sw:
                    c.setStrokeColor(_rgb(stroke))
                    c.setLineWidth(sw)
                if fill or (stroke and sw):
                    c.roundRect(x, ph - y - h, w, h, min(e.get("radius", 0), w / 2, h / 2), stroke=1 if (stroke and sw) else 0, fill=1 if fill else 0)
            elif e["type"] == "line":
                c.setFillColor(_rgb(e.get("color") or "#000000"))
                c.rect(x, ph - y - h, w, h, stroke=0, fill=1)          # una línea es un rectángulo delgado: grueso = alto (horizontal) o ancho (vertical)
        except Exception:          # noqa: BLE001 - un archivo roto no tumba el PDF
            log.error("elemento %s (%s) omitido en el PDF", e.get("id"), e.get("type"), exc_info=True)
        finally:
            c.restoreState()


def render(layout: dict, q: dict, fetch: Callable[[str], bytes], images: Optional[Dict[int, bytes]] = None, today_iso: str = "", ctx: Optional[Dict[str, str]] = None) -> bytes:
    """Arma el PDF: la hoja diseñada en cada página (según la regla de cada elemento) y el contenido dentro de su recuadro; lo que no cabe sigue en las páginas siguientes."""
    from reportlab.platypus import BaseDocTemplate, Frame, NextPageTemplate, PageTemplate
    ctx = ctx if ctx is not None else ql.context(q, today_iso)
    pw, ph = PAGES[layout["page"]]
    flow, nxt = layout["flow"], layout.get("next") or {"top": 40, "bottom": 40}
    title = f"Cotización {q.get('number', '')}"
    cache: dict = {}

    def segment(story: list, first: bool) -> bytes:
        buf = io.BytesIO()
        f1 = Frame(flow["x"], ph - flow["y"] - flow["h"], flow["w"], flow["h"], 0, 0, 0, 0, id="first")
        f2 = Frame(flow["x"], nxt["bottom"], flow["w"], ph - nxt["top"] - nxt["bottom"], 0, 0, 0, 0, id="next")
        offset = 0 if first else 1          # un tramo después de un PDF insertado ya no es la primera página

        def on_page(c, doc):
            _draw_elements(c, layout, ctx, fetch, c.getPageNumber() + offset, cache)
        templates = ([PageTemplate("first", [f1], onPage=on_page)] if first else []) + [PageTemplate("next", [f2], onPage=on_page)]
        doc = BaseDocTemplate(buf, pagesize=(pw, ph), pageTemplates=templates, title=title, author="Golden Eventos y Logística S.A.S.")
        body = ([NextPageTemplate("next")] if first else []) + (story or [ql._spacer(1)])
        doc.build(body)
        return buf.getvalue()
    height = min(flow["h"], ph - nxt["top"] - nxt["bottom"])
    return ql.render_blocks(flow.get("blocks", []), q, fetch, images, today_iso, ctx, width=flow["w"], make_segment=segment, max_height=height)
