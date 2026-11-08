"""Texto con formato (negrilla, listas, color…) de los formularios web (P3). Lógica pura, sin base ni HTTP.

Se guarda HTML RESTRINGIDO: solo etiquetas y estilos de una lista blanca, sin atributos (salvo `style` filtrado), sin enlaces, sin
imágenes, sin scripts. `sanitize` se aplica al GUARDAR (formlib) y el navegador vuelve a limpiar al PINTAR (static/js/rich-text.js,
mismas reglas; los casos comunes están en tests/rich_vectors.json y los corren pytest y Node).

«Con formato» es SOLO lo que contiene una etiqueta de la lista blanca: un texto viejo como «menores de <18 años» o «a < b» no la
tiene, así que sigue siendo texto plano (se guarda igual y se pinta escapado, con sus saltos de línea)."""
import functools
import re
from html.parser import HTMLParser
from pathlib import Path

MAX_LEN = 8000                 # tope del HTML ya limpio
MAX_DEPTH = 6                  # anidado máximo de etiquetas abiertas (lo más hondo se aplana a su contenido)

TAGS_FULL = ("b", "strong", "i", "em", "u", "p", "div", "br", "ul", "ol", "li", "span")
TAGS_BASIC = ("b", "strong", "i", "em", "u", "br", "span")          # ayudas de los campos: formato básico
BLOCK = ("p", "div", "ul", "ol", "li")
SKIP = ("script", "style", "iframe", "object", "embed", "template", "svg", "math", "noscript", "textarea", "title", "head", "frame", "frameset", "applet", "xmp", "plaintext", "noembed", "noframes", "select", "option")
VOID = ("br",)

# una etiqueta de verdad: nombre + atributos con forma de atributo («<b && c>» o «a < b» de un texto viejo no lo son)
_FORMAT_RE = re.compile(r"<\/?(?:b|strong|i|em|u|p|div|br|ul|ol|li|span)(?:\s+[a-z-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>\"']+))*\s*\/?>", re.I)      # valor sin comillas: «+», no «*» (con «*» el valor vacío hacía la expresión ambigua y exponencial: ReDoS, R3-01)
_HEX = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*(0|1|0?\.\d{1,3}|1\.0)\s*)?\)")
_SIZE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)(px|pt|em|rem|%)")
_SIZE_RANGE = {"px": (8, 64), "pt": (6, 48), "em": (0.5, 4), "rem": (0.5, 4), "%": (50, 300)}


@functools.lru_cache(maxsize=1)
def hosted_fonts() -> frozenset:
    """Tipografías alojadas por nosotros (las mismas que ofrece el diseñador: static/js/fonts-propias.js, generado por scripts/gen_fonts_css.py)."""
    src = (Path(__file__).resolve().parent.parent / "static" / "js" / "fonts-propias.js").read_text(encoding="utf-8")
    m = re.search(r"choices:\s*\[(.*?)\]", src, re.S)
    return frozenset(re.findall(r'"([^"]+)"', m.group(1))) if m else frozenset()


def has_format(text) -> bool:
    s = str(text or "")
    if len(s) > 20000:       # defensa extra: ningún texto legítimo con formato llega a tanto; que sanitize() lo recorte o rechace en vez de evaluar la expresión
        return True
    return bool(_FORMAT_RE.search(s))


def _color(v: str):
    v = v.strip().lower()
    if _HEX.fullmatch(v):
        return v
    m = _RGB.fullmatch(v)
    if m and all(int(x) <= 255 for x in m.groups()[:3]):
        r, g, b, a = m.groups()
        return f"rgba({int(r)},{int(g)},{int(b)},{a})" if a is not None else f"rgb({int(r)},{int(g)},{int(b)})"
    return None


def clean_style(style: str, full: bool = True) -> str:
    """Solo las declaraciones de la lista blanca, con valores estrictos (color hex/rgb, tamaño en rango, tipografías alojadas…)."""
    out = []
    for decl in str(style or "").split(";"):
        if ":" not in decl:
            continue
        prop, value = decl.split(":", 1)
        prop, value = prop.strip().lower(), value.strip()
        low = value.lower()
        if prop == "color":
            c = _color(value)
            if c:
                out.append(f"color:{c}")
        elif prop == "font-weight" and low in ("bold", "700", "normal", "400"):
            out.append("font-weight:" + ("bold" if low in ("bold", "700") else "normal"))
        elif prop == "font-style" and low in ("italic", "normal"):
            out.append(f"font-style:{low}")
        elif prop in ("text-decoration", "text-decoration-line") and low in ("underline", "none"):
            out.append(f"text-decoration:{low}")
        elif prop == "font-size" and full:
            m = _SIZE.fullmatch(low)
            if m and _SIZE_RANGE[m.group(2)][0] <= float(m.group(1)) <= _SIZE_RANGE[m.group(2)][1]:
                out.append(f"font-size:{m.group(1)}{m.group(2)}")
        elif prop == "font-family" and full:
            names = [n.strip().strip("'\"") for n in value.split(",")]
            names = [n for n in names if n in hosted_fonts()]
            if names:
                out.append("font-family:" + ",".join(f"'{n}'" for n in names[:3]))
        elif prop == "text-align" and full and low in ("left", "center", "right", "justify"):
            out.append(f"text-align:{low}")
    return ";".join(out)


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _Cleaner(HTMLParser):
    def __init__(self, basic: bool):
        super().__init__(convert_charrefs=True)
        self.allowed = TAGS_BASIC if basic else TAGS_FULL
        self.full = not basic
        self.out: list = []
        self.stack: list = []          # etiquetas permitidas abiertas (nombre)
        self.skip = 0                  # dentro de una etiqueta cuyo contenido se descarta (script, iframe…)

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in SKIP:
                self.skip += 1
            return
        if tag in SKIP:
            self.skip = 1
            return
        if tag not in self.allowed:
            return                                         # etiqueta desconocida: se descarta, su contenido queda
        if tag == "li" and not any(t in ("ul", "ol") for t in self.stack):
            return
        if tag in VOID:
            self.out.append("<br>")
            return
        if len(self.stack) >= MAX_DEPTH:
            return                                         # demasiado hondo: se aplana
        style = clean_style(dict(attrs).get("style") or "", self.full)
        self.out.append(f'<{tag} style="{style}">' if style else f"<{tag}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID:
            self.handle_starttag(tag, attrs)
        elif tag not in SKIP:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in SKIP:
                self.skip -= 1
            return
        if tag in self.stack:                              # cierra hasta la etiqueta (las de en medio quedan cerradas)
            while self.stack:
                t = self.stack.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(_esc(data))

    def close_all(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def sanitize(text, basic: bool = False) -> str:
    """HTML limpio (lista blanca). Lanza ValueError si el resultado pasa de MAX_LEN. Úsese solo si `has_format(text)`."""
    p = _Cleaner(basic)
    p.feed(str(text or ""))
    p.close()
    p.close_all()
    html = "".join(p.out).strip()
    if len(html) > MAX_LEN:
        raise ValueError(f"El texto con formato es demasiado largo (máximo {MAX_LEN} caracteres contando el formato)")
    return html


def clean_text(value, plain_limit: int, basic: bool = False) -> str:
    """Lo que se guarda: texto plano tal cual (recortado como siempre a `plain_limit`) o, si tiene etiquetas permitidas, su HTML limpio."""
    text = str(value if value is not None else "").strip()
    if not has_format(text):
        return text[:plain_limit]
    return sanitize(text, basic)


def to_plain(value) -> str:
    """Texto plano de un texto con formato, para destinos que no muestran HTML (correo de texto, PDF, reportes): sin etiquetas, con saltos de
    línea por bloque / <br> y «• » en las listas. El texto plano pasa sin tocarse."""
    text = str(value if value is not None else "")
    if not has_format(text):
        return text.strip()
    out: list = []

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.skip = 0
            self.lists: list = []

        def handle_starttag(self, tag, attrs):
            if tag in SKIP:
                self.skip += 1
            elif tag == "br":
                out.append("\n")
            elif tag in ("ul", "ol"):
                self.lists.append([tag, 0])
            elif tag == "li":
                if self.lists:
                    self.lists[-1][1] += 1
                out.append("\n" + (f"{self.lists[-1][1]}. " if self.lists and self.lists[-1][0] == "ol" else "• "))
            elif tag in ("p", "div"):
                out.append("\n")

        def handle_endtag(self, tag):
            if tag in SKIP:
                self.skip = max(0, self.skip - 1)
            elif tag in ("ul", "ol") and self.lists:
                self.lists.pop()
                out.append("\n")
            elif tag in ("p", "div"):
                out.append("\n")

        def handle_data(self, data):
            if not self.skip:
                out.append(data)

    p = _P()
    p.feed(text)
    p.close()
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
