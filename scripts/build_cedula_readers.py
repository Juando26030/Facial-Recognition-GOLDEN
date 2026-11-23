"""Genera static/js/cedula-readers.js (lectores de cédula para el quiosco) a partir de app/pruebas/lector_cedula.html, que es la FUENTE: así el lector de la página de prueba
y el del quiosco son el mismo código. Uso:  python scripts/build_cedula_readers.py   (tests/js/mrz_parser_check.js falla si el archivo generado quedó desactualizado)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "app" / "pruebas" / "lector_cedula.html"
OUT = ROOT / "static" / "js" / "cedula-readers.js"
START = "/*\n * Parser del PDF417 de la cédula de ciudadanía colombiana."
END = "/* ============ Interfaz de la demo ============ */"
HEAD = """/* GENERADO por scripts/build_cedula_readers.py desde app/pruebas/lector_cedula.html — NO editar a mano (edita la página y vuelve a generar).
   Lectores de cédula por cámara para el quiosco (Registro → Escanear), cargados bajo demanda por qr.js:
     CedulaReaders.CedulaScanner  cédula vieja: código de barras PDF417 (zxing-wasm)
     CedulaReaders.MrzScanner     cédula nueva: las 3 líneas de abajo (OCR con tesseract.js + dígitos de control)
   Librerías: copia propia en /static/vendor/cedula/ si existe (window.CEDULA_VENDOR; ver scripts/vendor_cedula_readers.sh); si no, CDN. Todo se procesa en el navegador. */
(function () {
'use strict';
"""
TAIL = """
window.CedulaReaders = { CedulaScanner, MrzScanner, parseCedula, parseMrz, mrzStrong, formatBirth };
})();
"""


def build() -> str:
    src = PAGE.read_text(encoding="utf8")
    a, b = src.index(START), src.index(END)
    return HEAD + src[a:b].rstrip() + "\n" + TAIL


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf8")
    print(f"{OUT.relative_to(ROOT)} generado ({OUT.stat().st_size} bytes)")
