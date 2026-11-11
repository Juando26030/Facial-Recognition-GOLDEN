"""Archivos de los formularios en bloque (12-nov-2026, pedido de Juan David): bajar de una vez todos los archivos de una columna de «Respuestas» en un ZIP, y mostrar el archivo
de cada persona en «Editar persona». Lógica pura (sin base): nombres seguros, qué campos son de archivo y a qué campo del registro (`opcional_N`) corresponden."""
import os
import re
import unicodedata
from typing import Optional

MAX_FILES = 1000                     # tope de archivos por ZIP
MAX_BYTES = 300 * 1024 * 1024        # tope de tamaño total por ZIP (Cloud Run tiene 60 s por petición)


def file_fields(design: dict) -> list:
    """[(id, etiqueta)] de los campos de tipo archivo del formulario, en el orden en que aparecen."""
    out = []
    for row in design.get("rows", []):
        for fid in row.get("items", []):
            f = design.get("fields", {}).get(fid)
            if f and f.get("type") == "file":
                out.append((fid, f.get("label") or fid))
    return out


def file_info(value) -> Optional[dict]:
    """El valor guardado de un campo de archivo ({"filename","stored",…}) o None si la persona no subió nada."""
    return value if isinstance(value, dict) and value.get("stored") else None


def safe_part(text: str, limit: int = 60) -> str:
    """Un pedazo de nombre de archivo sin tildes, espacios ni caracteres raros."""
    norm = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^A-Za-z0-9._-]+", "_", norm).strip("._-")
    return norm[:limit] or "archivo"


def zip_entry_name(person_id, label: str, submission_id: int, filename: str, used: set) -> str:
    """`cedula_Columna_id.ext`, único dentro del ZIP."""
    ext = os.path.splitext(filename or "")[1].lower()
    ext = ext if re.fullmatch(r"\.[a-z0-9]{1,6}", ext) else ""
    base = f"{safe_part(person_id or 'sin-cedula', 30)}_{safe_part(label, 40)}"
    name = f"{base}{ext}"
    if name in used:
        name = f"{base}_{submission_id}{ext}"
    n = 2
    while name in used:
        name = f"{base}_{submission_id}_{n}{ext}"
        n += 1
    used.add(name)
    return name


def extras_key_for(design: dict, field_id: str) -> Optional[str]:
    """Si el campo del formulario alimenta un campo adicional del registro (`opcional_N`), esa llave; si no, None."""
    f = (design.get("fields") or {}).get(field_id) or {}
    key = f.get("key") or ""
    return key if re.fullmatch(r"opcional_\d+", key) else None


def stored_text(value) -> str:
    """Lo que se guarda como texto en el registro de la persona para un valor de archivo: solo el nombre del archivo (nunca el diccionario)."""
    if isinstance(value, dict):
        return str(value.get("filename") or "")
    return str(value)
