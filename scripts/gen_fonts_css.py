"""Mapa ÚNICO de tipografías alojadas por nosotros. Genera static/css/fonts-propias.css y static/js/fonts-propias.js.

TODAS las familias de FAMILIES son opciones de los selectores (Configuración > Apariencia, escarapelas, certificados, formulario, ruleta) y se sirven desde static/fonts: nada se le pide a un tercero.
Agrandir (la fuente por defecto de la app) va aparte: es la opción «Original» y no pasa por aquí. Orden del 24-oct-2026: el diseñador de escarapelas ofrece todas las tipografías, no solo seis
(las 40 que ya tenía el producto antes de alojarlas: 6 de la primera ronda + 34). `MAP` queda para nombres viejos que ya no existan (hoy ninguno).

Uso: python scripts/gen_fonts_css.py   (la prueba tests/test_fuentes_propias.py falla si los archivos generados no coinciden con este)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# familia -> id del archivo (fontsource, solo latín = cubre español, pesos 400 y 700, woff2). Las que no tienen 700 sirven el 400 para todo el rango (sin negrita sintética).
FAMILIES = {
    "Abril Fatface": "abril-fatface", "Anton": "anton", "Archivo Black": "archivo-black", "Barlow": "barlow", "Bebas Neue": "bebas-neue", "Caveat": "caveat", "Comfortaa": "comfortaa",
    "Cormorant Garamond": "cormorant-garamond", "Crimson Text": "crimson-text", "DM Sans": "dm-sans", "Dancing Script": "dancing-script", "EB Garamond": "eb-garamond", "Fira Sans": "fira-sans",
    "Inter": "inter", "Josefin Sans": "josefin-sans", "Karla": "karla", "Lato": "lato", "Libre Baskerville": "libre-baskerville", "Lobster": "lobster", "Manrope": "manrope",
    "Merriweather": "merriweather", "Montserrat": "montserrat", "Mulish": "mulish", "Noto Sans": "noto-sans", "Nunito": "nunito", "Open Sans": "open-sans", "Oswald": "oswald",
    "PT Sans": "pt-sans", "Pacifico": "pacifico", "Playfair Display": "playfair-display", "Poppins": "poppins", "Quicksand": "quicksand", "Raleway": "raleway", "Roboto": "roboto",
    "Rubik": "rubik", "Source Sans Pro": "source-sans-pro", "Space Grotesk": "space-grotesk", "Ubuntu": "ubuntu", "Work Sans": "work-sans", "Zilla Slab": "zilla-slab",
}
FONT_DIR = ROOT / "static/fonts"


def _files(fid):
    w400 = f"{fid}-latin-400-normal.woff2"
    w700 = f"{fid}-latin-700-normal.woff2"
    return {"400": w400, "700": w700 if (FONT_DIR / w700).exists() else w400}


SIX = {fam: _files(fid) for fam, fid in FAMILIES.items()}        # nombre histórico: familia -> archivos
# nombre viejo que ya no se ofrece -> familia equivalente (hoy todas se ofrecen)
MAP = {}

HEAD = ("/* GENERADO por scripts/gen_fonts_css.py: no se edita a mano. Tipografías alojadas en static/fonts (licencias en static/fonts/licencias): 40 familias, solo latín y pesos 400/700.\n"
        "   Nada se le pide a un tercero (Google, Typekit...). */\n")


def face(family, files):
    out = []
    if files["400"] == files["700"]:
        out.append(f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: 400 700; font-display: swap; src: url('../fonts/{files['400']}') format('woff2'); }}")
    else:
        for w in ("400", "700"):
            out.append(f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {w}; font-display: swap; src: url('../fonts/{files[w]}') format('woff2'); }}")
    return out


def css():
    lines = [HEAD.rstrip("\n")]
    for fam, files in SIX.items():
        lines += face(fam, files)
    lines.append("/* alias */")
    for old, new in MAP.items():
        lines += face(old, SIX[new])
    return "\n".join(lines) + "\n"


def js():
    return ("/* GENERADO por scripts/gen_fonts_css.py: no se edita a mano. Las opciones de tipografía (todas alojadas) y la equivalencia de los nombres que ya no se ofrecen. */\n"
            "window.GoldenFonts = {\n"
            f"  choices: {json.dumps(list(SIX), ensure_ascii=False)},\n"
            f"  map: {json.dumps(MAP, ensure_ascii=False)},\n"
            "  resolve: function (name) { return this.choices.indexOf(name) >= 0 ? name : (this.map[name] || 'Roboto'); },\n"
            "};\n")


if __name__ == "__main__":
    (ROOT / "static/css/fonts-propias.css").write_text(css(), encoding="utf-8", newline="\n")
    (ROOT / "static/js/fonts-propias.js").write_text(js(), encoding="utf-8", newline="\n")
    print("ok", len(SIX), "familias +", len(MAP), "alias")
