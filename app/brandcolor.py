"""Color de marca por evento (como el logo propio): `events.brand_color` = '#rrggbb' o NULL (= el dorado general de Golden).
Las páginas públicas del evento lo reciben como variables CSS en un <style> del servidor (nunca hay colores sueltos en las hojas):
`--gw-gold-grad`/`--gw-gold-1`/`--gw-on-gold` (tokens del sistema de diseño) y `--gold`/`--on-gold` (páginas públicas sueltas).
El color del texto de los botones se elige solo (blanco o azul marino de Golden) y el color se RECHAZA si ninguno da contraste AA (4,5:1)."""
import re
from typing import Optional

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
LIGHT_TEXT = "#ffffff"
DARK_TEXT = "#141c4d"          # = --gw-on-gold / --gw-navy-deep
MIN_CONTRAST = 4.5
DEFAULT_PICK = "#1e2a6e"      # color que ofrece el selector al elegir «Color propio» (el azul de Golden); la plantilla lo recibe, no lo escribe


def normalize(value) -> str:
    """'#RGB' / 'rrggbb' / '#RRGGBB' → '#rrggbb' en minúscula. ValueError con mensaje en español si no es un color."""
    m = _HEX.match(str(value or "").strip())
    if not m:
        raise ValueError("El color debe ser un hexadecimal como #1E2A6E")
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _luminance(hex_color: str) -> float:
    def ch(i):
        c = int(hex_color[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(normalize(a)), _luminance(normalize(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(color: str) -> str:
    """El texto (blanco o azul marino) con más contraste sobre `color`."""
    return LIGHT_TEXT if contrast(color, LIGHT_TEXT) >= contrast(color, DARK_TEXT) else DARK_TEXT


def validate(value) -> str:
    """Normaliza y exige contraste mínimo con el texto de los botones; ValueError (español) si no lo da."""
    color = normalize(value)
    if contrast(color, text_on(color)) < MIN_CONTRAST:
        raise ValueError("Ese color no deja leer el texto de los botones; elige uno más claro u oscuro")
    return color


def css(color: Optional[str]) -> str:
    """Contenido del <style> con el color de marca; '' si el evento usa el general de Golden (o el valor guardado ya no es válido)."""
    if not color:
        return ""
    try:
        c = validate(color)
    except ValueError:
        return ""
    on = text_on(c)
    return (f":root{{--gw-gold-grad:{c};--gw-gold-1:{c};--gw-gold-2:{c};--gw-on-gold:{on};--gold:{c};--on-gold:{on};}}")
