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
PRODUCT_ALIASES = {
    "legacy_id": ("id",), "sku": ("codigo", "sku", "part number", "numero de parte", "referencia"), "name": ("nombre", "name", "producto", "nombre del producto"),
    "description": ("descripcion", "description"), "category": ("categoria", "category"), "cost": ("costo", "cost"), "price": ("precio", "price", "precio de lista", "list price"),
    "currency": ("moneda", "currency"),
}
OPPORTUNITY_ALIASES = {
    "legacy_id": ("id",), "code": ("codigo proyecto", "codigo del proyecto", "project code", "numero", "codigo"), "name": ("nombre", "name", "nombre de la oportunidad", "opportunity name"),
    "account_name": ("nombre de la cuenta", "account name", "cuenta"), "stage": ("etapa de ventas", "sales stage", "etapa"), "amount": ("importe", "amount", "monto", "valor"),
    "currency": ("moneda", "currency"), "expected_close": ("fecha de cierre esperada", "expected close date", "fecha de cierre", "cierre esperado"),
    "opp_type": ("tipo", "type"), "source": ("fuente de la oportunidad", "lead source", "fuente", "origen"), "next_step": ("siguiente paso", "next step"),
    "description": ("descripcion", "description"), "city": ("ciudad", "city"), "event_start": ("fecha del evento", "fecha de inicio del evento", "event date", "event start"),
    "lost_reason": ("motivo de perdida", "motivo", "lost reason"), "closed_at": ("fecha de cierre real", "closed date", "fecha cierre real"),
}
ACTIVITY_ALIASES = {
    "legacy_id": ("id",), "kind": ("tipo", "type", "tipo de actividad", "module"), "subject": ("asunto", "subject", "tema", "nombre", "name"), "status": ("estado", "status"),
    "due": ("fecha de vencimiento", "fecha de inicio", "date due", "date start", "fecha", "vence"), "description": ("descripcion", "description"),
    "opportunity_legacy_id": ("id oportunidad", "opportunity id", "id de la oportunidad"), "opportunity_name": ("oportunidad", "opportunity", "nombre de la oportunidad"),
    "account_name": ("nombre de la cuenta", "account name", "cuenta"),
}
QUOTE_ALIASES = {
    "legacy_id": ("id",), "number": ("numero", "number", "numero de cotizacion", "quote number"), "title": ("titulo", "title", "nombre", "name", "asunto"),
    "account_name": ("nombre de la cuenta", "account name", "cuenta"), "opportunity_legacy_id": ("id oportunidad", "opportunity id", "id de la oportunidad"),
    "opportunity_name": ("oportunidad", "opportunity", "nombre de la oportunidad"), "stage": ("etapa", "stage", "estado", "etapa de la cotizacion", "quote stage"),
    "valid_until": ("valida hasta", "valid until", "fecha de validez", "valido hasta"), "terms": ("terminos y condiciones", "terms", "terminos"),
    "currency": ("moneda", "currency"), "total": ("total", "total amount", "importe total"),
}
QUOTE_LINE_ALIASES = {
    "quote_legacy_id": ("id cotizacion", "quote id", "id de la cotizacion"), "quote_number": ("numero de cotizacion", "quote number", "cotizacion"),
    "name": ("nombre", "name", "producto", "concepto", "item"), "description": ("descripcion", "description"), "qty": ("cantidad", "quantity", "qty"),
    "unit_price": ("precio unitario", "unit price", "precio", "list price"), "discount_percent": ("descuento", "discount", "descuento %"),
    "tax_percent": ("impuesto", "tax", "iva", "impuesto %"),
}
PROFORMA_ALIASES = {
    "legacy_id": ("id",), "number": ("numero", "number", "numero de proforma", "proforma"), "quote_legacy_id": ("id cotizacion", "quote id", "id de la cotizacion"),
    "quote_number": ("numero de cotizacion", "quote number", "cotizacion"), "account_name": ("nombre de la cuenta", "account name", "cuenta"),
    "issued_at": ("fecha de emision", "fecha", "issue date", "issued"), "due_at": ("fecha de vencimiento", "vence", "due date"), "status": ("estado", "status", "estado de pago"),
    "event_name": ("evento", "nombre del evento", "event"), "city": ("ciudad", "city"), "total": ("total", "importe total", "total amount"), "currency": ("moneda", "currency"),
}
ALIASES = {"accounts": ACCOUNT_ALIASES, "contacts": CONTACT_ALIASES, "products": PRODUCT_ALIASES, "opportunities": OPPORTUNITY_ALIASES, "activities": ACTIVITY_ALIASES,
           "quotes": QUOTE_ALIASES, "quote_lines": QUOTE_LINE_ALIASES, "proformas": PROFORMA_ALIASES}
REQUIRED = {"accounts": ("name",), "contacts": ("first_name",), "products": ("name",), "opportunities": ("name", "account_name"), "activities": ("subject",),
            "quotes": ("account_name",), "quote_lines": ("name",), "proformas": ("account_name",)}


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


def check_headers(kind: str, raw: bytes) -> None:
    """Valida tamaño, codificación y columnas obligatorias al subir (falla rápido, antes de encolar nada)."""
    for _ in read_rows(kind, raw, 1):
        break
