"""Parseo y validación de la zona MRZ (Machine Readable Zone, estándar ICAO 9303, formato TD1)
del reverso de la cédula colombiana nueva — Sprint 2 Parte 2, Historia 2.3.

Separado de `app/mrz_ocr.py` (que sí necesita el binario de Tesseract instalado) a propósito:
esta función es pura — recibe texto, no imágenes — así que se puede probar con las 3 líneas
exactas que ya trae confirmadas el brief del sprint, sin necesitar OCR real ni una foto de
verdad. Usa la librería `mrz` (ya trae el parseo TD1 completo + la validación de dígitos
verificadores del estándar, en vez de reimplementar el checksum a mano) — decisión de Juan
David, 2026-09-15, ver brief.
"""
from itertools import islice, product

from mrz.checker.td1 import TD1CodeChecker

_LINE_LENGTH = 30

# Clase de carácter que el estándar TD1 exige en cada posición: «d» dígito, «a» letra (o «<»), «n» cualquiera. El OCR confunde las parejas parecidas (en OCR-B la «O» y el «0» casi no
# se distinguen: «COL» sale «C0L»), pero la POSICIÓN dice cuál de las dos debe ser: es la corrección estándar de lectores MRZ y no puede dar por buena una lectura mala, porque
# lo que sale se valida igual con los dígitos verificadores ICAO.
_CLASSES = (
    "a" * 5 + "n" * 9 + "d" + "n" * 15,                                  # línea 1: tipo (2), país (3), nº del documento (9), verificador (1), opcional (15)
    "d" * 6 + "d" + "a" + "d" * 6 + "d" + "a" * 3 + "n" * 11 + "d",       # línea 2: nacimiento (6+1), sexo, vencimiento (6+1), nacionalidad (3), opcional (11), verificador final
    "a" * 30,                                                              # línea 3: apellidos y nombres
)
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
_TO_LETTER = {"0": "ODQ", "1": "IL", "2": "Z", "5": "S", "8": "B", "6": "G"}       # un dígito en una posición de letra puede ser varias letras: se prueban en este orden
_MAX_CANDIDATES = 64


def _alternatives(ch: str, cls: str) -> str:
    if cls == "d" and ch.isalpha():
        return _TO_DIGIT.get(ch, ch)
    if cls == "a" and ch.isdigit():
        return _TO_LETTER.get(ch, ch)
    return ch


def _fix_by_position(line: str, classes: str) -> str:
    """Una corrección por posición (la primera alternativa): para las pruebas y para quien quiera una sola lectura."""
    return "".join(_alternatives(ch, cls)[0] for ch, cls in zip(line, classes))


def _candidates(raw: list):
    """Lecturas corregidas por posición, de la más probable a la menos (combinando las alternativas de las posiciones dudosas, con tope): cada una se valida con los dígitos verificadores."""
    options = [[_alternatives(ch, cls) for ch, cls in zip(line, classes)] for line, classes in zip(raw, _CLASSES)]
    flat = [alts for line in options for alts in line]
    for combo in islice(product(*flat), _MAX_CANDIDATES):
        joined = "".join(combo)
        yield [joined[i * _LINE_LENGTH:(i + 1) * _LINE_LENGTH] for i in range(3)]


def _normalize_line(line: str) -> str:
    """OCR real casi nunca entrega las 3 líneas perfectamente alineadas a 30 caracteres — el
    relleno `<` a veces se lee como espacio, o falta/sobra un carácter en el borde. Se normaliza
    a mayúsculas, los espacios se tratan como relleno (en el MRZ real nunca hay espacios, solo
    `<`), y se recorta/rellena a 30 — si el OCR se equivocó de verdad, el checksum de abajo lo
    va a detectar igual (por eso no hace falta validar la alineación acá)."""
    cleaned = (line or "").strip().upper().replace(" ", "<")
    return cleaned.ljust(_LINE_LENGTH, "<")[:_LINE_LENGTH]


def _parse(lines: list) -> dict:
    """Devuelve {"valid": bool, "id", "first_name", "last_name", "birth_date", "sex",
    "expiry_date"}. `valid=False` significa que algún dígito verificador ICAO no cuadra — el
    llamador debe pedir repetir la foto en vez de aceptar los datos a ciegas (ver brief, "Validación
    de la lectura OCR")."""
    code = "\n".join(lines)
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


def parse_mrz_td1(line1: str, line2: str, line3: str) -> dict:
    """Devuelve {"valid": bool, "id", "first_name", "last_name", ...}. Primero la lectura tal cual; si no valida, la misma lectura corregida por la clase de carácter de cada posición
    (ver `_CLASSES`). `valid=False` significa que algún dígito verificador ICAO no cuadra incluso así: el llamador debe pedir repetir la foto, nunca aceptar los datos a ciegas."""
    raw = [_normalize_line(line1), _normalize_line(line2), _normalize_line(line3)]
    result = _parse(raw)
    if result["valid"]:
        return result
    for candidate in _candidates(raw):
        if candidate != raw:
            corrected = _parse(candidate)
            if corrected["valid"]:
                return corrected
    return result
