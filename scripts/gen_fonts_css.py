"""Mapa ÚNICO de tipografías alojadas por nosotros. Genera static/css/fonts-propias.css y static/js/fonts-propias.js.

Las 6 familias de SIX son las OPCIONES de los selectores (Configuración > Apariencia, escarapelas, certificados, formulario, ruleta). Agrandir (la fuente por
defecto de la app) va aparte: es la opción «Original» y no pasa por aquí. Cada familia de Google que algún diseño guardado pueda traer (MAP) se declara como
un alias que sirve el archivo de la más parecida de las 6: los diseños viejos se siguen viendo sin pedirle nada a Google ni tocar la base de datos.

Uso: python scripts/gen_fonts_css.py   (la prueba tests/test_fuentes_propias.py falla si los archivos generados no coinciden con este)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# familia -> archivo de cada peso. Solo latín (cubre español), solo 400 y 700, woff2.
SIX = {
    "Roboto": {"400": "roboto-latin-400-normal.woff2", "700": "roboto-latin-700-normal.woff2"},
    "Open Sans": {"400": "open-sans-latin-400-normal.woff2", "700": "open-sans-latin-700-normal.woff2"},
    "Montserrat": {"400": "montserrat-latin-400-normal.woff2", "700": "montserrat-latin-700-normal.woff2"},
    "Playfair Display": {"400": "playfair-display-latin-400-normal.woff2", "700": "playfair-display-latin-700-normal.woff2"},
    "Merriweather": {"400": "merriweather-latin-400-normal.woff2", "700": "merriweather-latin-700-normal.woff2"},
    "Bebas Neue": {"400": "bebas-neue-latin-400-normal.woff2", "700": "bebas-neue-latin-400-normal.woff2"},        # solo existe el 400
}

# familia que ya no se ofrece -> la más parecida de las 6
MAP = {
    # sans humanistas
    "Lato": "Open Sans", "Noto Sans": "Open Sans", "Source Sans Pro": "Open Sans", "PT Sans": "Open Sans", "Fira Sans": "Open Sans", "Karla": "Open Sans",
    "Nunito": "Open Sans", "Mulish": "Open Sans", "Ubuntu": "Open Sans",
    # sans neutras
    "Inter": "Roboto", "Work Sans": "Roboto", "Barlow": "Roboto", "DM Sans": "Roboto", "Manrope": "Roboto", "Rubik": "Roboto", "Space Grotesk": "Roboto",
    # sans geométricas y redondeadas (anchas)
    "Poppins": "Montserrat", "Raleway": "Montserrat", "Quicksand": "Montserrat", "Comfortaa": "Montserrat", "Josefin Sans": "Montserrat", "Archivo Black": "Montserrat",
    # condensadas de titular
    "Oswald": "Bebas Neue", "Anton": "Bebas Neue",
    # serif de título y manuscritas
    "Abril Fatface": "Playfair Display", "Cormorant Garamond": "Playfair Display", "Dancing Script": "Playfair Display", "Pacifico": "Playfair Display",
    "Lobster": "Playfair Display", "Caveat": "Playfair Display",
    # serif de texto
    "Crimson Text": "Merriweather", "Libre Baskerville": "Merriweather", "EB Garamond": "Merriweather", "Zilla Slab": "Merriweather",
}

HEAD = ("/* GENERADO por scripts/gen_fonts_css.py: no se edita a mano. Tipografías alojadas en static/fonts (licencias en static/fonts/licencias): 6 familias, solo latín y pesos 400/700.\n"
        "   Las demás familias de Google que un diseño viejo pueda traer son alias de la más parecida, para no pedirle nada a un tercero. */\n")


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
    return ("/* GENERADO por scripts/gen_fonts_css.py: no se edita a mano. Las 6 opciones de tipografía y la equivalencia de las familias que ya no se ofrecen. */\n"
            "window.GoldenFonts = {\n"
            f"  choices: {json.dumps(list(SIX), ensure_ascii=False)},\n"
            f"  map: {json.dumps(MAP, ensure_ascii=False)},\n"
            "  resolve: function (name) { return this.choices.indexOf(name) >= 0 ? name : (this.map[name] || this.choices[0]); },\n"
            "};\n")


if __name__ == "__main__":
    (ROOT / "static/css/fonts-propias.css").write_text(css(), encoding="utf-8", newline="\n")
    (ROOT / "static/js/fonts-propias.js").write_text(js(), encoding="utf-8", newline="\n")
    print("ok", len(SIX), "familias +", len(MAP), "alias")
