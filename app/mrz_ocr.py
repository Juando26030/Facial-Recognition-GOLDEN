"""OCR de la foto del reverso de la cédula nueva, para extraer las 3 líneas crudas de la zona
MRZ — Sprint 2 Parte 2, Historia 2.3. Aislado de `app/mrz_parser.py` (que es puro texto, sin
imágenes) a propósito: el parser se puede probar sin esto, pero ESTE módulo sí necesita el
binario de Tesseract instalado en el sistema (`apt install tesseract-ocr` en la VM de
producción; en Windows, el instalador de UB Mannheim — ver CLAUDE.md) y no se puede verificar de
punta a punta sin él ni sin una foto real de una cédula.

Se usa Pillow (ya es dependencia del proyecto, para las fotos biométricas) en vez de sumar
OpenCV — el único preprocesamiento que hace falta es convertir a escala de grises y binarizar
con un umbral fijo, suficiente para texto MRZ impreso (alto contraste, fuente monoespaciada
OCR-B) sin necesitar herramientas de visión más pesadas.
"""
import numpy as np
import pytesseract
from PIL import Image

# Alfabeto real de una línea MRZ: A-Z, 0-9 y "<" de relleno — restringir el reconocimiento a
# esto (en vez de dejar que Tesseract intente puntuación/acentos) mejora bastante la precisión.
_MRZ_CHAR_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
_TESSERACT_CONFIG = f"--psm 6 -c tessedit_char_whitelist={_MRZ_CHAR_WHITELIST}"


def _preprocess(image_array: np.ndarray) -> Image.Image:
    image = Image.fromarray(image_array).convert("L")  # escala de grises
    # Umbral fijo simple: el MRZ es texto negro impreso sobre fondo claro, no hace falta un
    # umbral adaptativo más sofisticado para este caso de uso.
    return image.point(lambda p: 255 if p > 140 else 0)


def extract_mrz_lines(image_array: np.ndarray) -> list:
    """Devuelve las líneas de texto no vacías que Tesseract detectó, en el orden en que
    aparecen. El reverso de la cédula trae más texto impreso además de la zona MRZ, así que se
    espera que las ÚLTIMAS 3 líneas no vacías sean la MRZ (siempre son las 3 líneas finales del
    documento, por definición del estándar) — el llamador se queda con esas 3."""
    processed = _preprocess(image_array)
    raw_text = pytesseract.image_to_string(processed, config=_TESSERACT_CONFIG)
    return [line.strip() for line in raw_text.splitlines() if line.strip()]
