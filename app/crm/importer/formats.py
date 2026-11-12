"""Lectura de archivos exportados de SuiteCRM 7 (CSV): codificación, delimitador y encabezados en español o inglés."""
import csv
import io
from typing import Iterator, Optional

from app.crm import normalize
from app.crm.errors import CrmError

MAX_FILE_BYTES = 25 * 1024 * 1024
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
DELIMITERS = (",", ";", "\t", "|")

# Llave interna → nombres posibles de la columna (ya normalizados: minúsculas, sin tildes).
ACCOUNT_ALIASES = {
    "legacy_id": ("id",),
    "code": ("numero de cuenta", "account number", "numero", "codigo", "codigo cliente", "client code"),
    "name": ("nombre", "name", "nombre de la cuenta", "account name", "razon social"),
    "nit": ("nit", "tax id", "nit / cc"),
    "phone": ("telefono de la oficina", "office phone", "telefono", "phone"),
    "email": ("correo electronico", "email address", "email", "correo"),
    "website": ("sitio web", "website"),
    "city": ("ciudad", "billing city", "ciudad de facturacion"),
    "address": ("direccion", "billing street", "direccion de facturacion"),
    "description": ("descripcion", "description"),
}
CONTACT_ALIASES = {
    "legacy_id": ("id",), "first_name": ("nombre", "first name"), "last_name": ("apellidos", "apellido", "last name"),
    "job_title": ("cargo", "title", "job title"), "email": ("correo electronico", "email address", "email", "correo"),
    "phone": ("telefono de la oficina", "telefono movil", "mobile", "office phone", "telefono", "phone"),
    "account_name": ("nombre de la cuenta", "account name", "cuenta"),
}
ALIASES = {"accounts": ACCOUNT_ALIASES, "contacts": CONTACT_ALIASES}
REQUIRED = {"accounts": ("name",), "contacts": ("first_name",)}


def decode(raw: bytes) -> str:
    if len(raw) > MAX_FILE_BYTES:
        raise CrmError("El archivo supera 25 MB. Divídelo en partes.")
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CrmError("No se pudo leer la codificación del archivo.")


def detect_delimiter(text: str) -> str:
    head = "\n".join(text.splitlines()[:5])
    best = max(DELIMITERS, key=lambda d: head.count(d))
    return best if head.count(best) else ","


def map_headers(kind: str, headers: list) -> dict:
    """Índice de cada llave interna según el encabezado. Falta una obligatoria → error SIN valores de datos."""
    table = ALIASES[kind]
    seen = {normalize(h): i for i, h in enumerate(headers)}
    out = {}
    for key, names in table.items():
        for n in names:
            if n in seen:
                out[key] = seen[n]
                break
    missing = [k for k in REQUIRED[kind] if k not in out]
    if missing:
        raise CrmError("Al archivo le falta la columna obligatoria: " + ", ".join(table[k][0] for k in missing) + ".")
    return out


def read_rows(kind: str, raw: bytes, limit: Optional[int] = None) -> Iterator[tuple]:
    """Rinde (número_de_fila, dict_por_llave_interna). El número cuenta desde 2 (fila 1 = encabezado), como en la hoja de cálculo."""
    text = decode(raw)
    reader = csv.reader(io.StringIO(text), delimiter=detect_delimiter(text))
    try:
        headers = next(reader)
    except StopIteration:
        raise CrmError("El archivo está vacío.")
    idx = map_headers(kind, headers)
    n = 0
    for lineno, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        yield lineno, {k: (row[i].strip() if i < len(row) else "") for k, i in idx.items()}
        n += 1
        if limit is not None and n >= limit:
            return
