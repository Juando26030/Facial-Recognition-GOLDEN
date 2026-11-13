"""Del VOLCADO de SuiteCRM a los archivos por tipo que entiende el importador (accounts, contacts, opportunities…).
Núcleo PURO (solo biblioteca estándar, sin base de datos): une cada tabla con sus enlaces (cuenta↔contacto, cuenta↔oportunidad, correos, campos propios `*_cstm`)
y escribe CSV con los encabezados de `formats.py`. Las filas borradas (`deleted=1`) no pasan. Nada se guarda ni se imprime con datos personales: el informe son solo conteos."""
import csv
import io
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Tuple

from app.crm.importer import dump

NEEDED = ("calls", "meetings", "tasks", "quotes", "quote_lines", "products", "accounts", "accounts_cstm", "contacts", "opportunities", "opportunities_cstm", "rel_account_contact", "rel_account_opportunity", "email_addresses", "email_rel")

ACCOUNT_HEADER = ["id", "numero de cuenta", "nombre", "nit", "telefono", "correo electronico", "sitio web", "ciudad", "direccion", "descripcion",
                  "estado", "categoria", "tipo", "industria", "legacy_json"]
CONTACT_HEADER = ["id", "nombre", "apellidos", "cargo", "correo electronico", "telefono", "telefono movil", "nombre de la cuenta", "id cuenta", "notas", "legacy_json"]
OPPORTUNITY_HEADER = ["id", "codigo", "nombre", "nombre de la cuenta", "id cuenta", "etapa", "importe", "moneda", "fecha de cierre esperada", "tipo", "fuente", "siguiente paso",
                      "descripcion", "legacy_json"]

ACCOUNT_LEGACY = ("account_type", "industry", "phone_alternate", "phone_fax", "ownership", "employees", "rating", "billing_address_postalcode", "billing_address_state",
                  "billing_address_country", "shipping_address_street", "shipping_address_city", "shipping_address_state", "shipping_address_country", "assigned_user_id",
                  "date_entered")
CONTACT_LEGACY = ("salutation", "department", "do_not_call", "phone_home", "phone_other", "phone_fax", "lead_source", "birthdate", "assistant", "assistant_phone", "assigned_user_id",
                  "primary_address_street", "primary_address_city", "primary_address_state", "primary_address_country", "date_entered")
OPPORTUNITY_LEGACY = ("currency_id", "probability", "date_closed", "assigned_user_id", "campaign_id", "date_entered")
ACCOUNT_CSTM_LEGACY = ("plazo_pago_c", "dias_para_pago_c", "cierre_facturacion_c", "porcentaje_agencia_c", "contacto_cobro_c", "contacto_cobro_tel_c")
ACTIVITY_HEADER = ["id", "tipo", "asunto", "estado", "fecha", "descripcion", "id oportunidad", "nombre de la cuenta", "legacy_json"]
QUOTE_HEADER = ["id", "numero", "titulo", "nombre de la cuenta", "id oportunidad", "etapa", "valida hasta", "terminos", "moneda", "total", "legacy_json"]
LINE_HEADER = ["id cotizacion", "nombre", "descripcion", "cantidad", "precio unitario", "descuento", "impuesto"]
PRODUCT_HEADER = ["id", "codigo", "nombre", "descripcion", "categoria", "costo", "precio", "moneda"]
ACTIVITY_LEGACY = ("duration_hours", "duration_minutes", "direction", "location", "priority", "parent_type", "assigned_user_id", "date_entered")
QUOTE_LEGACY = ("approval_status", "invoice_status", "stage", "billing_contact_id", "subtotal_amount", "discount_amount", "tax_amount", "assigned_user_id", "date_entered")
OPP_CSTM_LEGACY = ("codbase_c", "dateproject_c", "facturahistorico_c", "gestorini_c", "gestorfin_c")


def _alive(row: dict) -> bool:
    return dump.clean(row.get("deleted")) != "1"


def _legacy(row: dict, keys: Iterable[str], extra: Optional[dict] = None) -> str:
    """JSON con lo que no tiene columna propia, con su nombre original de SuiteCRM (solo las llaves con valor)."""
    out = {k: dump.clean(row.get(k)) for k in keys if dump.clean(row.get(k))}
    if extra:
        out.update({k: v for k, v in extra.items() if v})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""


STATUS_MAP = {"activo": "activo", "inactivo": "inactivo", "masivo": "masivo", "nogestionar": "no_gestionar", "liquidado": "liquidado", "moroso": "moroso", "conrestriccion": "restringido"}


def _status(value) -> str:
    """Estado de cuenta de SuiteCRM → clave nuestra; vacío si no se reconoce (queda «activo» y el original se anota en legacy_json)."""
    return STATUS_MAP.get(dump.clean(value).lower().replace(" ", "").replace("_", ""), "")


def _amount(value) -> str:
    """El importe de SuiteCRM trae 8 decimales («1500000.00000000»): se redondea a 2 para que el importador no lo lea como miles."""
    v = dump.clean(value)
    if not v:
        return ""
    try:
        return str(Decimal(v).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return v


def _fit(value, limit: int, extra: dict, key: str, report: Optional[Counter] = None) -> str:
    """Texto dentro del tope de la columna; si se pasa, queda recortado y el original completo en legacy_json."""
    v = dump.clean(value)
    if len(v) > limit:
        extra[key + "_original"] = v
        if report is not None:
            report["trimmed"] += 1
        return v[:limit]
    return v


def _digits(value) -> str:
    v = dump.clean(value)
    return v if v.isdigit() else ""


def load_tables(stream) -> Dict[str, List[dict]]:
    return dump.load(stream, NEEDED)


def _emails(tables: Dict[str, List[dict]]) -> Dict[Tuple[str, str], str]:
    """(módulo, id del registro) → correo principal (o el primero que tenga). Salta los inválidos, los de «no contactar» no se descartan: solo se anotan en el informe."""
    by_id = {r["id"]: r for r in tables.get("email_addresses", []) if _alive(r)}
    best: Dict[Tuple[str, str], Tuple[int, str]] = {}
    for rel in tables.get("email_rel", []):
        if not _alive(rel):
            continue
        addr = by_id.get(rel.get("email_address_id"))
        if not addr or dump.clean(addr.get("invalid_email")) == "1" or not dump.clean(addr.get("email_address")):
            continue
        key = (dump.clean(rel.get("bean_module")), dump.clean(rel.get("bean_id")))
        rank = 0 if dump.clean(rel.get("primary_address")) == "1" else 1
        if key not in best or rank < best[key][0]:
            best[key] = (rank, dump.clean(addr["email_address"]))
    return {k: v[1] for k, v in best.items()}


def convert(tables: Dict[str, List[dict]]) -> Tuple[Dict[str, Tuple[List[str], List[list]]], dict]:
    """Devuelve ({tipo: (encabezado, filas)}, informe de conteos). Una cuenta sin nombre o un contacto/oportunidad sin cuenta se cuentan y se dejan fuera."""
    emails = _emails(tables)
    cstm_a = {r["id_c"]: r for r in tables.get("accounts_cstm", [])}
    cstm_o = {r["id_c"]: r for r in tables.get("opportunities_cstm", [])}
    report: dict = {"accounts": Counter(), "contacts": Counter(), "opportunities": Counter()}

    # --- cuentas
    accounts, acc_name, name_count = [], {}, Counter()
    from app.crm import normalize
    for r in tables.get("accounts", []):
        if not _alive(r):
            report["accounts"]["deleted"] += 1
            continue
        name = dump.clean(r.get("name"))
        if not name:
            report["accounts"]["no_name"] += 1
            continue
        c = cstm_a.get(r["id"], {})
        code = _digits(c.get("codigo_c"))
        extra = {k: dump.clean(c.get(k)) for k in ACCOUNT_CSTM_LEGACY}
        accounts.append((r, c, name, code, extra))
        name_count[normalize(name)[:200]] += 1
    seen_codes: set = set()
    seen_names: set = set()
    rows_a = []
    for r, c, name, code, extra in accounts:
        key = normalize(name)[:200]
        if name_count[key] > 1:
            report["accounts"]["duplicate_name"] += 1
            if key in seen_names:                                                # el importador liga por nombre: la repetida lleva su número para poder distinguirla
                extra["nombre_original"] = name
                name = f"{name} (cuenta {code or r['id'][:8]})"[:200]
            seen_names.add(key)
        estado = dump.clean(c.get("estado_c"))
        status = _status(estado)
        if estado and not status:
            extra["estado_original"] = estado
            report["accounts"]["status_unknown"] += 1
        if code and code in seen_codes:
            extra["codigo_original_repetido"] = code
            code = ""
            report["accounts"]["code_repeated"] += 1
        if code:
            seen_codes.add(code)
        acc_name[r["id"]] = name
        rows_a.append([r["id"], code, name, dump.clean(r.get("sic_code")), _fit(r.get("phone_office"), 60, extra, "phone_office", report["accounts"]), emails.get(("Accounts", r["id"]), ""),
                       dump.clean(r.get("website")), dump.clean(r.get("billing_address_city")), dump.clean(r.get("billing_address_street")), dump.clean(r.get("description")),
                       status, dump.clean(c.get("categoria_c")), dump.clean(r.get("account_type")), dump.clean(r.get("industry")),
                       _legacy(r, ACCOUNT_LEGACY, extra)])
        report["accounts"]["out"] += 1

    # --- contactos (cuenta por la tabla de enlace; si tiene dos, la primera)
    link_c: Dict[str, str] = {}
    for rel in tables.get("rel_account_contact", []):
        if _alive(rel) and rel.get("account_id") in acc_name:
            link_c.setdefault(rel["contact_id"], rel["account_id"])
    rows_c = []
    for r in tables.get("contacts", []):
        if not _alive(r):
            report["contacts"]["deleted"] += 1
            continue
        aid = link_c.get(r["id"])
        if not aid:
            report["contacts"]["no_account"] += 1
            continue
        first = dump.clean(r.get("first_name")) or dump.clean(r.get("last_name"))
        if not first:
            report["contacts"]["no_name"] += 1
            continue
        last = dump.clean(r.get("last_name")) if dump.clean(r.get("first_name")) else ""
        extra: dict = {}
        rep = report["contacts"]
        rows_c.append([r["id"], _fit(first, 120, extra, "first_name", rep), _fit(last, 120, extra, "last_name", rep), _fit(r.get("title"), 120, extra, "title", rep),
                       _fit(emails.get(("Contacts", r["id"]), ""), 200, extra, "email", rep), _fit(r.get("phone_work"), 60, extra, "phone_work", rep),
                       _fit(r.get("phone_mobile"), 60, extra, "phone_mobile", rep), acc_name[aid], aid, dump.clean(r.get("description")), _legacy(r, CONTACT_LEGACY, extra)])
        report["contacts"]["out"] += 1

    # --- oportunidades
    link_o: Dict[str, str] = {}
    for rel in tables.get("rel_account_opportunity", []):
        if _alive(rel) and rel.get("account_id") in acc_name:
            link_o.setdefault(rel["opportunity_id"], rel["account_id"])
    rows_o, seen_o = [], set()
    for r in tables.get("opportunities", []):
        if not _alive(r):
            report["opportunities"]["deleted"] += 1
            continue
        aid = link_o.get(r["id"])
        if not aid:
            report["opportunities"]["no_account"] += 1
            continue
        c = cstm_o.get(r["id"], {})
        code = _digits(c.get("codigo_c"))
        extra = {k: dump.clean(c.get(k)) for k in OPP_CSTM_LEGACY}
        if code and (code in seen_o or int(code) > 9_000_000_000):
            extra["codigo_original"] = code
            code = ""
            report["opportunities"]["code_repeated"] += 1
        if code:
            seen_o.add(code)
        rows_o.append([r["id"], code, dump.clean(r.get("name")), acc_name[aid], aid, dump.clean(r.get("sales_stage")), _amount(r.get("amount")), dump.clean(r.get("currency_id")) if dump.clean(r.get("currency_id")).isalpha() and len(dump.clean(r.get("currency_id"))) == 3 else "",
                       dump.clean(r.get("date_closed")), dump.clean(r.get("opportunity_type")), dump.clean(r.get("lead_source")), dump.clean(r.get("next_step")),
                       dump.clean(r.get("description")), _legacy(r, OPPORTUNITY_LEGACY, extra)])
        report["opportunities"]["out"] += 1

    opp_ids = {row[0] for row in rows_o}
    report.update({"activities": Counter(), "quotes": Counter(), "quote_lines": Counter(), "products": Counter()})

    # --- actividades: llamadas, reuniones y tareas colgadas de una oportunidad o de una cuenta (también por un contacto de la cuenta); el resto no tiene dónde ir
    rows_t = []
    for table, kind in (("calls", "call"), ("meetings", "meeting"), ("tasks", "task")):
        for r in tables.get(table, []):
            if not _alive(r):
                report["activities"]["deleted"] += 1
                continue
            ptype, pid = dump.clean(r.get("parent_type")), dump.clean(r.get("parent_id"))
            opp_id, acc_id = "", ""
            if ptype == "Opportunities" and pid in opp_ids:
                opp_id = pid
            elif ptype == "Accounts" and pid in acc_name:
                acc_id = pid
            elif ptype == "Contacts" and pid in link_c:
                acc_id = link_c[pid]
            if not opp_id and not acc_id:
                report["activities"]["unlinked_" + (ptype or "none").lower()] += 1
                continue
            due = dump.clean(r.get("date_due")) or dump.clean(r.get("date_start"))
            extra: dict = {}
            rows_t.append([r["id"], kind, _fit(r.get("name") or "(sin asunto)", 200, extra, "name"), dump.clean(r.get("status")), due, dump.clean(r.get("description")), opp_id,
                           acc_name.get(acc_id, "") if acc_id else "", _legacy(r, ACTIVITY_LEGACY, extra)])
            report["activities"]["out_" + kind] += 1

    # --- cotizaciones y sus líneas
    quote_ids, rows_q, seen_n = set(), [], set()
    for r in tables.get("quotes", []):
        if not _alive(r):
            report["quotes"]["deleted"] += 1
            continue
        aid = dump.clean(r.get("billing_account_id"))
        if aid not in acc_name:
            report["quotes"]["no_account"] += 1
            continue
        number = _digits(r.get("number"))
        extra = {}
        if number and (number in seen_n or int(number) > 9_000_000_000):
            extra["numero_original"] = number
            number = ""
            report["quotes"]["number_repeated"] += 1
        if number:
            seen_n.add(number)
        oid = dump.clean(r.get("opportunity_id"))
        cur = dump.clean(r.get("currency_id"))
        quote_ids.add(r["id"])
        rows_q.append([r["id"], number, _fit(r.get("name"), 200, extra, "name"), acc_name[aid], oid if oid in opp_ids else "", dump.clean(r.get("stage")), dump.clean(r.get("expiration")),
                       dump.clean(r.get("term")), cur if cur.isalpha() and len(cur) == 3 else "", _amount(r.get("total_amount")), _legacy(r, QUOTE_LEGACY, extra)])
        report["quotes"]["out"] += 1
    rows_l = []
    for r in tables.get("quote_lines", []):
        if not _alive(r) or dump.clean(r.get("parent_id")) not in quote_ids:
            report["quote_lines"]["skipped"] += 1
            continue
        qty, price = _amount(r.get("product_qty")) or "1", _amount(r.get("product_list_price")) or _amount(r.get("product_unit_price")) or "0.00"
        disc = _amount(r.get("product_discount")) or "0.00"
        if dump.clean(r.get("discount")) == "Amount":                         # SuiteCRM permite descuento en pesos; el CRM solo en %: se convierte
            try:
                base = Decimal(price) * Decimal(qty)
                disc = str((Decimal(disc) / base * 100).quantize(Decimal("0.01"))) if base > 0 else "0.00"
            except (InvalidOperation, ValueError):
                disc = "0.00"
            report["quote_lines"]["discount_amount_to_percent"] += 1
        vat = dump.clean(r.get("vat")).replace(",", ".")
        try:
            tax = str(Decimal(vat).quantize(Decimal("0.01"))) if vat else "0.00"
        except (InvalidOperation, ValueError):
            tax = "0.00"
        rows_l.append([r["parent_id"], dump.clean(r.get("name")) or "(sin nombre)", dump.clean(r.get("item_description")), qty, price, disc, tax])
        report["quote_lines"]["out"] += 1

    # --- productos
    rows_p, seen_sku = [], set()
    for r in tables.get("products", []):
        if not _alive(r) or not dump.clean(r.get("name")):
            report["products"]["skipped"] += 1
            continue
        sku = dump.clean(r.get("part_number")) or dump.clean(r.get("maincode"))
        if sku and sku in seen_sku:
            sku = ""
            report["products"]["sku_repeated"] += 1
        if sku:
            seen_sku.add(sku)
        cur = dump.clean(r.get("currency_id"))
        rows_p.append([r["id"], sku, dump.clean(r.get("name")), dump.clean(r.get("description")), dump.clean(r.get("category")), _amount(r.get("cost")), _amount(r.get("price")),
                       cur if cur.isalpha() and len(cur) == 3 else ""])
        report["products"]["out"] += 1

    out = {"accounts": (ACCOUNT_HEADER, rows_a), "contacts": (CONTACT_HEADER, rows_c), "opportunities": (OPPORTUNITY_HEADER, rows_o), "activities": (ACTIVITY_HEADER, rows_t),
           "quotes": (QUOTE_HEADER, rows_q), "quote_lines": (LINE_HEADER, rows_l), "products": (PRODUCT_HEADER, rows_p)}
    return out, {k: dict(v) for k, v in report.items()}


def to_csv(header: List[str], rows: List[list]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")
