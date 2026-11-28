"""Acta de novedades del evento (Fase 10): lógica pura (validación, estado, huella y documento imprimible). Sin HTTP; lo que toca la base está en app/routers/event_acts.py.

Reglas: el coordinador (o admin / super_admin) escribe el acta y firma la suya; el cliente (rol «cliente» autorizado al evento) firma SOLO la suya. Con las dos firmas el acta queda
«firmada» y el texto ya no se puede cambiar. No hay biblioteca de PDF instalada: el documento es HTML imprimible (con las firmas dentro) que se guarda como PDF desde el cuadro de impresión."""
import base64
import hashlib
import html
import io
from datetime import datetime
from typing import Optional

from PIL import Image

from app import safe_limits

TITLE_MAX = 160
BODY_MAX = 10000
FORMATS = ("text", "list")
MAX_SIGNATURE_BYTES = 600_000
STATUS_LABEL = {"borrador": "Borrador (sin firmas)", "firma_pendiente": "Falta una firma", "firmada": "Firmada por ambas partes"}


def clean_fields(data: dict) -> dict:
    """{title, format, body} limpios o ValueError con un mensaje legible."""
    title = " ".join(str(data.get("title") or "").split())
    if not title:
        raise ValueError("Escribe un título para el acta")
    if len(title) > TITLE_MAX:
        raise ValueError(f"El título admite máximo {TITLE_MAX} caracteres")
    fmt = data.get("format") or "text"
    if fmt not in FORMATS:
        raise ValueError("El formato debe ser párrafo o lista")
    body = str(data.get("body") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        raise ValueError("Escribe lo ocurrido en el evento")
    if len(body) > BODY_MAX:
        raise ValueError(f"El texto admite máximo {BODY_MAX} caracteres")
    if fmt == "list":
        body = "\n".join(line.strip().lstrip("-•*·").strip() for line in body.split("\n") if line.strip().lstrip("-•*·").strip())
        if not body:
            raise ValueError("Escribe al menos un punto en la lista")
    return {"title": title, "format": fmt, "body": body}


def status_of(act) -> str:
    n = bool(act.coordinator_sig_key) + bool(act.client_sig_key)
    return "firmada" if n == 2 else ("firma_pendiente" if n == 1 else "borrador")


def content_hash(title: str, fmt: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{fmt}\n{body}".encode("utf-8")).hexdigest()


def decode_signature(raw) -> bytes:
    """PNG de la firma dibujada (data URL) -> bytes, o ValueError. Rechaza imágenes que no sean PNG, enormes o vacías (todo transparente)."""
    raw = str(raw or "")
    if not raw.startswith("data:image/png;base64,"):
        raise ValueError("La firma debe enviarse como imagen PNG")
    try:
        blob = base64.b64decode(raw.split(",", 1)[1], validate=True)
    except Exception:
        raise ValueError("La imagen de la firma no es válida")
    if len(blob) > MAX_SIGNATURE_BYTES or len(blob) < 100:
        raise ValueError("La imagen de la firma no es válida")
    try:
        safe_limits.check_image_dimensions(blob)
        img = Image.open(io.BytesIO(blob))
        img.load()
        if img.format != "PNG":
            raise ValueError("formato")
        if img.convert("RGBA").getchannel("A").getextrema()[1] == 0:          # todo transparente = no dibujó nada
            raise ValueError("vacía")
    except Exception:
        raise ValueError("La firma está vacía o no es válida: dibújala de nuevo")
    return blob


def sig_key(tenant_id: str, event_id: int, act_id: int, who: str, token: str) -> str:
    from app.storage import key_of
    return key_of(tenant_id, "event_acts", event_id, f"{act_id}_{who}_{token}.png")


def _fmt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    from app.timeutil import to_local
    return to_local(dt).strftime("%d/%m/%Y %I:%M %p")


def _body_html(act) -> str:
    if act.format == "list":
        return "<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in act.body.split("\n") if line.strip()) + "</ul>"
    return "".join(f"<p>{html.escape(par).replace(chr(10), '<br>')}</p>" for par in act.body.split("\n\n") if par.strip())


def _sig_box(label: str, name: Optional[str], at: Optional[datetime], png: Optional[bytes]) -> str:
    if png:
        img = f'<img alt="Firma" src="data:image/png;base64,{base64.b64encode(png).decode()}">'
        meta = f"<div class=\"n\">{html.escape(name or '')}</div><div class=\"d\">{html.escape(_fmt(at))}</div>"
    else:
        img, meta = '<div class="pend">Pendiente de firma</div>', ""
    return f'<div class="sig"><div class="box">{img}</div><div class="line"></div><b>{html.escape(label)}</b>{meta}</div>'


def render_html(event, act, coordinator_png: Optional[bytes], client_png: Optional[bytes], company: str = "") -> str:
    """Documento imprimible (HTML autónomo, apto para guardar como PDF desde el cuadro de impresión)."""
    status = STATUS_LABEL[status_of(act)]
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(act.title)} - Acta de novedades</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;color:#111;margin:0;padding:24px;line-height:1.5}}
.wrap{{max-width:780px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#555;margin:0 0 16px}}
.meta{{border:1px solid #bbb;border-radius:6px;padding:10px 14px;margin-bottom:18px;font-size:14px}}
.body{{border-top:2px solid #111;padding-top:12px;min-height:160px;font-size:15px}} ul{{padding-left:22px}}
.sigs{{display:flex;gap:32px;margin-top:40px;page-break-inside:avoid}} .sig{{flex:1;text-align:center;font-size:13px}}
.box{{height:110px;display:flex;align-items:flex-end;justify-content:center}} .box img{{max-height:105px;max-width:100%}}
.line{{border-top:1px solid #111;margin:4px 0 6px}} .pend{{color:#999;font-style:italic}} .d{{color:#555}}
.foot{{margin-top:28px;color:#777;font-size:11px}} @media print{{body{{padding:0}}}}
</style></head><body><div class="wrap">
<h1>{html.escape(act.title)}</h1><p class="sub">Acta de novedades{(' - ' + html.escape(company)) if company else ''}</p>
<div class="meta"><b>Evento:</b> {html.escape(event.name)} &nbsp; <b>Código:</b> {html.escape(str(event.event_code or ''))}<br><b>Fecha del acta:</b> {html.escape(_fmt(act.created_at))} &nbsp; <b>Estado:</b> {html.escape(status)}</div>
<div class="body">{_body_html(act)}</div>
<div class="sigs">{_sig_box('Coordinador', act.coordinator_name, act.coordinator_signed_at, coordinator_png)}{_sig_box('Cliente', act.client_name, act.client_signed_at, client_png)}</div>
<p class="foot">{('Huella del texto firmado: ' + html.escape(act.content_hash)) if act.content_hash else ''}</p>
</div></body></html>"""


def pdf_key(tenant_id: str, event_id: int, act_id: int) -> str:
    from app.storage import key_of
    return key_of(tenant_id, "event_acts", event_id, f"{act_id}_acta.pdf")


def render_pdf(event, act, coordinator_png: Optional[bytes], client_png: Optional[bytes], company: str = "") -> bytes:
    """El acta completa en PDF (título, evento, fecha, texto, las dos firmas con nombre y fecha, huella). reportlab se importa aquí (perezoso): sin la librería lanza ImportError y quien llama
    deja el acta guardada igual (se puede regenerar)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    esc = html.escape
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=11, leading=15, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=12, textColor=colors.HexColor("#555555"))
    title = ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18, alignment=TA_LEFT)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=act.title, author=company or "Orum")
    flow = [Paragraph(esc(act.title), title), Paragraph("Acta de novedades" + (" - " + esc(company) if company else ""), small), Spacer(1, 4 * mm),
            Paragraph(f"<b>Evento:</b> {esc(event.name)} &nbsp; <b>Código:</b> {esc(str(event.event_code or ''))}<br/><b>Fecha del acta:</b> {esc(_fmt(act.created_at))} &nbsp; <b>Estado:</b> {esc(STATUS_LABEL[status_of(act)])}", body),
            Spacer(1, 6 * mm)]
    if act.format == "list":
        flow.append(ListFlowable([ListItem(Paragraph(esc(line), body)) for line in act.body.split("\n") if line.strip()], bulletType="bullet", leftIndent=14))
    else:
        for par in act.body.split("\n\n"):
            if par.strip():
                flow += [Paragraph(esc(par).replace("\n", "<br/>"), body), Spacer(1, 2 * mm)]
    flow.append(Spacer(1, 14 * mm))

    def cell(label, name, at, png):
        parts = []
        if png:
            parts.append(RLImage(io.BytesIO(png), width=60 * mm, height=24 * mm, kind="proportional"))
        else:
            parts.append(Paragraph("<i>Pendiente de firma</i>", small))
        parts += [Paragraph(f"<b>{label}</b>", body)]
        if png:
            parts += [Paragraph(esc(name or ""), small), Paragraph(esc(_fmt(at)), small)]
        return parts
    sigs = Table([[cell("Coordinador", act.coordinator_name, act.coordinator_signed_at, coordinator_png), cell("Cliente", act.client_name, act.client_signed_at, client_png)]], colWidths=[85 * mm, 85 * mm])
    sigs.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEABOVE", (0, 0), (-1, 0), 0, colors.white)]))
    flow.append(KeepTogether([sigs]))
    if act.content_hash:
        flow += [Spacer(1, 8 * mm), Paragraph("Huella del texto firmado (SHA-256): " + esc(act.content_hash), small)]
    doc.build(flow)
    return out.getvalue()
