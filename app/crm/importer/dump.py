"""Lector del VOLCADO completo de SuiteCRM 7 (una exportación de la base: todas las tablas pegadas una tras otra en un solo CSV, cada una con su encabezado y sin nombre).
Núcleo PURO (solo biblioteca estándar): reconoce cada tabla por sus columnas y entrega filas como diccionarios. No guarda nada ni escribe datos personales en ningún lado."""
import csv
import io
import re
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

csv.field_size_limit(2 ** 30)

# Nombre interno → columnas que la tabla TIENE y columnas que NO puede tener (para separar tablas parecidas: contactos / leads / usuarios).
SIGNATURES: List[Tuple[str, set, set]] = [
    ("accounts", {"name", "account_type", "billing_address_city", "sic_code"}, set()),
    ("accounts_cstm", {"id_c", "codigo_c", "estado_c"}, set()),
    ("contacts", {"first_name", "last_name", "phone_mobile", "reports_to_id", "lead_source"}, {"converted"}),
    ("leads", {"first_name", "last_name", "converted", "status", "account_name"}, set()),
    ("opportunities", {"sales_stage", "amount", "date_closed"}, set()),
    ("opportunities_cstm", {"id_c", "codbase_c", "codigo_c"}, set()),
    ("quotes", {"billing_account_id", "opportunity_id", "stage", "approval_status", "invoice_status"}, set()),
    ("quotes_cstm", {"id_c", "evento_nombre_c"}, set()),
    ("invoices", {"billing_account_id", "quote_number", "invoice_date", "due_date"}, set()),
    ("quote_lines", {"product_qty", "group_id", "parent_id", "product_unit_price"}, set()),
    ("line_groups", {"total_amt", "parent_id", "parent_type", "number"}, {"billing_account_id", "product_qty"}),
    ("products", {"maincode", "part_number", "price", "cost"}, set()),
    ("calls", {"direction", "date_start", "parent_type", "parent_id"}, set()),
    ("meetings", {"location", "date_start", "parent_type", "parent_id", "join_url"}, set()),
    ("tasks", {"date_due", "priority", "parent_type", "parent_id"}, set()),
    ("users", {"user_name", "user_hash", "is_admin"}, set()),
    ("rel_account_contact", {"contact_id", "account_id"}, set()),
    ("rel_account_opportunity", {"opportunity_id", "account_id"}, set()),
    ("rel_opportunity_contact", {"contact_id", "opportunity_id", "contact_role"}, set()),
    ("email_addresses", {"email_address", "email_address_caps", "invalid_email", "opt_out"}, set()),
    ("email_rel", {"email_address_id", "bean_id", "bean_module", "primary_address"}, set()),
    ("audit", {"parent_id", "field_name", "before_value_string", "after_value_string"}, set()),          # todas las tablas *_audit se parecen: se separan por el id al que apuntan
]
_IDENT = re.compile(r"^[a-z0-9_]+$")


def is_header(row: list) -> bool:
    """Fila de encabezado: la primera celda es `id` (o `id_c`, las tablas de campos propios) y todas son nombres de columna en minúscula."""
    return bool(row) and row[0] in ("id", "id_c") and len(row) >= 2 and all(_IDENT.match(c) for c in row if c)


def identify(header: list) -> Optional[str]:
    cols = set(header)
    for name, need, forbid in SIGNATURES:
        if need <= cols and not (forbid & cols):
            return name
    return None


def iter_tables(stream: Iterable[str]) -> Iterator[Tuple[Optional[str], list, Iterator[dict]]]:
    """Recorre el volcado en una sola pasada: rinde (nombre|None, encabezado, filas) por cada tabla, EN ORDEN. Hay que consumir las filas antes de pedir la siguiente tabla.
    Las filas con otra cantidad de celdas que el encabezado (basura entre tablas) se descartan; las tablas no reconocidas se rinden con nombre None."""
    reader = csv.reader(stream)
    pending: List[list] = []

    def rows_of(header: list, first_data: Optional[list]) -> Iterator[dict]:
        width = len(header)
        if first_data is not None and len(first_data) == width:
            yield dict(zip(header, first_data))
        for row in reader:
            if is_header(row):
                pending.append(row)
                return
            if len(row) == width:
                yield dict(zip(header, row))

    for row in reader:
        if is_header(row):
            pending.append(row)
            break
    while pending:
        header = pending.pop()
        yield identify(header), header, rows_of(header, None)


def load(stream: Iterable[str], wanted: Iterable[str]) -> Dict[str, List[dict]]:
    """Carga en memoria SOLO las tablas pedidas (por nombre interno). Si una tabla aparece dos veces se queda la primera; `audit` junta todas las tablas de historial."""
    want = set(wanted)
    out: Dict[str, List[dict]] = {}
    for name, _header, rows in iter_tables(stream):
        if name in want and (name == "audit" or name not in out):
            out.setdefault(name, []).extend(rows)
        else:
            for _ in rows:
                pass
    return out


def load_path(path: str, wanted: Iterable[str]) -> Dict[str, List[dict]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return load(fh, wanted)


def load_bytes(raw: bytes, wanted: Iterable[str]) -> Dict[str, List[dict]]:
    return load(io.StringIO(raw.decode("utf-8-sig")), wanted)


def blank(value) -> bool:
    return value is None or str(value).strip() in ("", "NULL")


def clean(value) -> str:
    """Valor de texto del volcado: 'NULL' y vacío son lo mismo (nada)."""
    return "" if blank(value) else str(value).strip()
