"""Mayúsculas / minúsculas al subir la base (Plan 5, paso 4): selector «Texto: como viene / MAYÚSCULAS / minúsculas» de la pantalla de carga.

Se aplica en el servidor, UNA vez, sobre las filas ya con sus columnas reconocidas (antes de partirlas en pasos o lotes), a los textos de la persona: nombres, apellidos, cargo, entidad, tipo de asistente
y los campos opcionales. NUNCA a la cédula, al teléfono, a la fecha de nacimiento ni a las columnas de control (categoría, certificado, registrado en formulario). El correo SIEMPRE se normaliza a
minúsculas, también con «como viene»."""
from typing import Optional

AS_IS, UPPER, LOWER = "", "upper", "lower"
MODES = {"": AS_IS, "asis": AS_IS, "como_viene": AS_IS, "upper": UPPER, "mayusculas": UPPER, "lower": LOWER, "minusculas": LOWER}
TEXT_KEYS = ("nombres", "apellidos", "cargo", "entidad", "tipo de asistente")
LABELS = {UPPER: "MAYÚSCULAS", LOWER: "minúsculas"}


def parse_mode(value: Optional[str]) -> Optional[str]:
    """Valor del formulario → modo (AS_IS/UPPER/LOWER); None si no es uno válido (la ruta responde 400)."""
    return MODES.get(str(value or "").strip().lower().replace(" ", "_"))


def convert(value: str, mode: Optional[str]) -> str:
    """Un solo texto según el modo (el formulario de persona, app/personform.py, lo usa al guardar). Solo cambia mayúsculas/minúsculas; sin modo devuelve el texto tal cual."""
    if not isinstance(value, str) or not value:
        return value
    return value.upper() if mode == UPPER else (value.lower() if mode == LOWER else value)


def _is_optional(key: str) -> bool:
    return key.startswith("opcional_")


def apply(rows: list, mode: Optional[str]) -> list:
    """Devuelve las mismas filas (se modifican en el lugar) con el texto convertido y el correo en minúsculas."""
    convert = str.upper if mode == UPPER else (str.lower if mode == LOWER else None)
    for row in rows:
        if "correo" in row and row["correo"]:
            row["correo"] = str(row["correo"]).strip().lower()
        if convert is None:
            continue
        for key, value in row.items():
            if (key in TEXT_KEYS or _is_optional(key)) and isinstance(value, str) and value:
                row[key] = convert(value)
    return rows
