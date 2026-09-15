"""Parseo y validación de la zona MRZ (Machine Readable Zone, estándar ICAO 9303, formato TD1)
del reverso de la cédula colombiana nueva — Sprint 2 Parte 2, Historia 2.3.

Separado de `app/mrz_ocr.py` (que sí necesita el binario de Tesseract instalado) a propósito:
esta función es pura — recibe texto, no imágenes — así que se puede probar con las 3 líneas
exactas que ya trae confirmadas el brief del sprint, sin necesitar OCR real ni una foto de
verdad. Usa la librería `mrz` (ya trae el parseo TD1 completo + la validación de dígitos
verificadores del estándar, en vez de reimplementar el checksum a mano) — decisión de Juan
David, 2026-09-15, ver brief.
"""
from mrz.checker.td1 import TD1CodeChecker

_LINE_LENGTH = 30


def _normalize_line(line: str) -> str:
    """OCR real casi nunca entrega las 3 líneas perfectamente alineadas a 30 caracteres — el
    relleno `<` a veces se lee como espacio, o falta/sobra un carácter en el borde. Se normaliza
    a mayúsculas, los espacios se tratan como relleno (en el MRZ real nunca hay espacios, solo
    `<`), y se recorta/rellena a 30 — si el OCR se equivocó de verdad, el checksum de abajo lo
    va a detectar igual (por eso no hace falta validar la alineación acá)."""
    cleaned = (line or "").strip().upper().replace(" ", "<")
    return cleaned.ljust(_LINE_LENGTH, "<")[:_LINE_LENGTH]


def parse_mrz_td1(line1: str, line2: str, line3: str) -> dict:
    """Devuelve {"valid": bool, "id", "first_name", "last_name", "birth_date", "sex",
    "expiry_date"}. `valid=False` significa que algún dígito verificador ICAO no cuadra — el
    llamador debe pedir repetir la foto en vez de aceptar los datos a ciegas (ver brief, "Validación
    de la lectura OCR")."""
    code = "\n".join([_normalize_line(line1), _normalize_line(line2), _normalize_line(line3)])
    try:
        checker = TD1CodeChecker(code, check_expiry=False)
    except Exception:
        return {"valid": False, "id": None, "first_name": None, "last_name": None}

    fields = checker.fields()
    # optional_data_2 (línea 2, después de la nacionalidad) es donde el estándar TD1 deja el
    # número de cédula/NUIP real en el documento colombiano — confirmado carácter por carácter
    # contra una cédula real en el brief (línea 1 trae un número de documento físico distinto,
    # no el de cédula). Puede traer relleno `<` al final si el número es más corto que el campo.
    cedula = (fields.optional_data_2 or "").rstrip("<").strip()

    return {
        "valid": bool(checker) and bool(cedula),
        "id": cedula or None,
        "first_name": fields.name or None,
        "last_name": fields.surname or None,
        "birth_date": fields.birth_date,
        "sex": fields.sex,
        "expiry_date": fields.expiry_date,
    }
