"""Correo de la escarapela virtual, editable por evento (Parámetros del Evento, 2026-09-25).

El organizador escribe asunto y cuerpo en un editor visual (negritas, enlaces, imágenes, botón) con variables entre llaves.
Lo que se guarda pasa SIEMPRE por `sanitize`: una lista blanca de etiquetas/atributos/estilos, sin scripts ni nada que cargue código.
Las imágenes se sirven desde `/email-assets/...` (público, nombre no adivinable) porque un lector de correo no tiene la sesión del sistema.
"""
import html
import re
from html.parser import HTMLParser

VARIABLES = [
    ("nombre", "Nombres de la persona"), ("apellido", "Apellidos"), ("nombre_completo", "Nombres y apellidos"),
    ("evento", "Nombre del evento"), ("fecha", "Fecha de inicio del evento"), ("lugar", "Lugar del evento"),
    ("enlace", "Enlace a su escarapela (texto)"), ("boton", "Botón «Abrir mi escarapela»"),
]
DEFAULT_SUBJECT = "Tu escarapela digital — {evento}"
DEFAULT_BODY = ("<p>Hola {nombre},</p><p>Esta es tu escarapela digital para <b>{evento}</b>. Ábrela desde tu celular el día del evento:</p>"
                "<p style=\"text-align:center\">{boton}</p>"
                "<p style=\"font-size:13px;color:#666\">Es personal: no compartas el enlace ni capturas de pantalla "
                "(la escarapela muestra una animación y la hora en vivo).</p>")
MAX_BODY = 60_000

_TAGS = {"p", "br", "div", "span", "b", "strong", "i", "em", "u", "a", "img", "h1", "h2", "h3", "ul", "ol", "li", "hr", "font"}
_VOID = {"br", "img", "hr"}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "form", "head", "title", "svg", "math"}
_STYLE_PROPS = {"color", "background-color", "font-size", "font-weight", "font-style", "text-decoration", "text-align", "padding", "margin",
                "border-radius", "line-height", "max-width", "width", "height", "font-family", "display"}
_SAFE_VALUE = re.compile(r"^[#\w\s.,%()'\"-]{1,80}$")


def _clean_style(raw: str) -> str:
    out = []
    for decl in (raw or "").split(";"):
        prop, _, value = decl.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if prop in _STYLE_PROPS and _SAFE_VALUE.match(value) and not re.search(r"url|expression|javascript|@import", value, re.I):
            out.append(f"{prop}:{value}")
    return ";".join(out)


def _safe_url(value: str, allow_mailto: bool = False) -> str:
    value = (value or "").strip()
    if value in ("{enlace}",) or re.match(r"^https?://[^\s\"'<>]+$", value, re.I) or (allow_mailto and re.match(r"^mailto:[^\s\"'<>]+$", value, re.I)):
        return value
    return ""


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.stack = [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _TAGS:
            return
        attrs = dict(attrs)
        keep = []
        style = _clean_style(attrs.get("style", ""))
        if style:
            keep.append(f'style="{html.escape(style, quote=True)}"')
        if tag == "a":
            href = _safe_url(attrs.get("href", ""), allow_mailto=True)
            if href:
                keep.append(f'href="{html.escape(href, quote=True)}"')
            keep.append('target="_blank" rel="noopener noreferrer"')
        elif tag == "img":
            src = _safe_url(attrs.get("src", ""))
            if not src:
                return
            keep.append(f'src="{html.escape(src, quote=True)}"')
            keep.append(f'alt="{html.escape((attrs.get("alt") or "")[:120], quote=True)}"')
            if str(attrs.get("width", "")).isdigit() and int(attrs["width"]) <= 1000:
                keep.append(f'width="{int(attrs["width"])}"')
            if "max-width" not in style:
                keep.append('style="max-width:100%;height:auto"' if not style else "")
        elif tag == "font" and re.fullmatch(r"#[0-9a-fA-F]{3,8}", attrs.get("color") or ""):
            keep.append(f'color="{attrs["color"]}"')
        self.out.append(f"<{tag}{' ' + ' '.join(k for k in keep if k) if any(keep) else ''}>")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in self.stack:
            while self.stack:
                top = self.stack.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def close_all(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def sanitize(raw: str) -> str:
    parser = _Sanitizer()
    parser.feed((raw or "")[:MAX_BODY])
    parser.close()
    parser.close_all()
    return "".join(parser.out).strip()


def to_text(body_html: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-3]>", "\n", body_html)
    text = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (\1)", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def values_for(event, first: str, last: str, link: str) -> dict:
    when = getattr(event, "start_date", None)
    place = ", ".join(x for x in (getattr(event, "location", None), getattr(event, "city", None)) if x)
    button = (f'<a href="{html.escape(link, quote=True)}" style="display:inline-block;background:#1a237e;color:#ffffff;padding:12px 24px;'
              f'border-radius:8px;text-decoration:none;font-weight:bold;">Abrir mi escarapela</a>')
    return {"nombre": first, "apellido": last, "nombre_completo": f"{first} {last}".strip(), "evento": event.name,
            "fecha": when.strftime("%d/%m/%Y") if when else "", "lugar": place, "enlace": link, "boton": button}


def render(event, first: str, last: str, link: str):
    """(asunto, cuerpo HTML, texto plano) con las variables ya reemplazadas. Si el evento no tiene plantilla propia, usa la de siempre."""
    subject_t = getattr(event, "digital_email_subject", None) or DEFAULT_SUBJECT
    body_t = getattr(event, "digital_email_body", None) or DEFAULT_BODY
    vals = values_for(event, first, last, link)

    def fill(text, escape):
        return re.sub(r"\{(\w+)\}", lambda m: (html.escape(vals[m.group(1)], quote=True) if escape and m.group(1) not in ("boton",) else vals[m.group(1)]) if m.group(1) in vals else m.group(0), text)

    body = fill(body_t, True)
    wrapped = f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#222;line-height:1.5;max-width:600px;margin:0 auto;">{body}</div>'
    return fill(subject_t, False).replace("\n", " ")[:200], wrapped, to_text(body)
