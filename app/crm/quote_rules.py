"""Reglas PURAS de productos, condiciones, plantillas, cotizaciones y proformas del CRM (etapa C3). Sin SQLAlchemy: se prueban sin base (tests/test_crm_c3_texto.py).

Cálculo de una línea (todo con Decimal, redondeo ROUND_HALF_UP a 2 decimales):
    bruto = cantidad × precio unitario · descuento = bruto × %desc / 100 · neto = bruto − descuento · impuesto = neto × %imp / 100
    `line_total` guarda el NETO (sin impuesto). Cotización: subtotal = suma de netos · descuento = suma de descuentos · impuestos = suma de impuestos · total = subtotal + impuestos.
Los topes de texto son EXACTAMENTE los de las columnas (hay una prueba que lo comprueba): más largo = 400 en español, nunca 500.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from app.crm.errors import CrmError
from app.crm.pipeline_rules import CURRENCIES, clean_currency, clean_date, text_field

PRODUCT_LIMITS = {"sku": 60, "name": 200, "description": 20000, "category": 80}
TERM_LIMITS = {"name": 80, "body": 20000}
TEMPLATE_LIMITS = {"name": 80, "header_text": 5000, "greeting_text": 5000, "footer_text": 5000}
QUOTE_LIMITS = {"title": 200, "terms_text": 20000, "meeting_notes": 20000}
LINE_LIMITS = {"name": 200, "description": 20000}
PROFORMA_LIMITS = {"event_name": 200, "city": 120}
FILTER_NAME_MAX = 80

QUOTE_STAGES = ("borrador", "enviada", "negociada", "aprobada", "rechazada", "vencida")
OPEN_QUOTE_STAGES = ("borrador", "enviada", "negociada")
APPROVALS = ("pendiente", "aprobada", "rechazada")
INVOICE_STATUSES = ("no_facturada", "facturada")
PROFORMA_STATUSES = ("no_pagado", "pagado", "anulado")
TEMPLATE_KINDS = ("quote", "proforma")
FILTER_SCOPES = ("cuentas", "oportunidades", "leads", "cotizaciones")
MAX_LINES = 200
MAX_MONEY = Decimal("99999999999999.99")          # Numeric(16, 2)
TWO = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def _dec(value, label: str, *, low=Decimal("0"), high=MAX_MONEY, default=None) -> Decimal:
    if value in (None, ""):
        if default is not None:
            return default
        raise CrmError(f"Falta «{label}».")
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise CrmError(f"«{label}» debe ser un número.") from exc
    if not d.is_finite() or d < low or d > high:
        raise CrmError(f"«{label}» está fuera del rango permitido.")
    return d


def clean_percent(value, label: str, default: Decimal) -> Decimal:
    return _dec(value, label, high=Decimal("100"), default=default).quantize(TWO, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ cálculo
def line_amounts(qty, unit_price, discount_percent, tax_percent) -> dict:
    qty, unit_price, disc, tax = Decimal(qty), Decimal(unit_price), Decimal(discount_percent), Decimal(tax_percent)
    gross = money(qty * unit_price)
    discount = money(gross * disc / 100)
    net = money(gross - discount)
    return {"gross": gross, "discount": discount, "net": net, "tax": money(net * tax / 100)}


def totals(lines: list) -> dict:
    """`lines`: [{qty, unit_price, discount_percent, tax_percent}]. Devuelve subtotal, discount_total, tax_total y total."""
    sub = disc = tax = Decimal("0.00")
    for ln in lines:
        a = line_amounts(ln["qty"], ln["unit_price"], ln["discount_percent"], ln["tax_percent"])
        sub, disc, tax = sub + a["net"], disc + a["discount"], tax + a["tax"]
    return {"subtotal": money(sub), "discount_total": money(disc), "tax_total": money(tax), "total": money(sub + tax)}


# ------------------------------------------------------------------ validación
def clean_product(data: dict, creating: bool = False) -> dict:
    out: dict = {}
    for key, limit in PRODUCT_LIMITS.items():
        text_field(data, key, limit, out)
    if (creating or "name" in out) and not out.get("name"):
        raise CrmError("El producto necesita un nombre.")
    for key, label in (("cost", "Costo"), ("price", "Precio")):
        if key in data or creating:
            out[key] = money(_dec(data.get(key), label, default=Decimal("0")))
    if "currency" in data or creating:
        out["currency"] = clean_currency(data.get("currency") or "COP")
    if "tax_percent" in data or creating:
        out["tax_percent"] = clean_percent(data.get("tax_percent"), "Impuesto (%)", Decimal("19"))
    if "active" in data:
        out["active"] = bool(data["active"])
    return out


def clean_term(data: dict, creating: bool = False) -> dict:
    out: dict = {}
    for key, limit in TERM_LIMITS.items():
        text_field(data, key, limit, out)
    for key in ("name", "body"):
        if (creating or key in out) and not out.get(key):
            raise CrmError("La condición necesita nombre y texto.")
    return out


def clean_template(data: dict, creating: bool = False) -> dict:
    out: dict = {}
    for key, limit in TEMPLATE_LIMITS.items():
        text_field(data, key, limit, out)
    if (creating or "name" in out) and not out.get("name"):
        raise CrmError("La plantilla necesita un nombre.")
    if creating or "kind" in data:
        kind = str(data.get("kind") or "").strip()
        if kind not in TEMPLATE_KINDS:
            raise CrmError("El tipo de plantilla debe ser «quote» o «proforma».")
        out["kind"] = kind
    return out


def clean_line(data: dict) -> dict:
    out: dict = {}
    for key, limit in LINE_LIMITS.items():
        text_field(data, key, limit, out)
    if not out.get("name"):
        raise CrmError("Cada línea necesita un nombre.")
    out["qty"] = _dec(data.get("qty"), "Cantidad", high=Decimal("9999999999.99"), default=Decimal("1")).quantize(TWO, rounding=ROUND_HALF_UP)
    out["unit_price"] = money(_dec(data.get("unit_price"), "Precio unitario", default=Decimal("0")))
    out["discount_percent"] = clean_percent(data.get("discount_percent"), "Descuento (%)", Decimal("0"))
    out["tax_percent"] = clean_percent(data.get("tax_percent"), "Impuesto (%)", Decimal("19"))
    pid = data.get("product_id")
    out["product_id"] = int(pid) if str(pid or "").isdigit() else None
    return out


def clean_lines(lines) -> list:
    if not isinstance(lines, list):
        raise CrmError("Las líneas deben venir como una lista.")
    if len(lines) > MAX_LINES:
        raise CrmError(f"Una cotización admite como máximo {MAX_LINES} líneas.")
    cleaned = [clean_line(ln if isinstance(ln, dict) else {}) for ln in lines]
    for i, c in enumerate(cleaned):
        c["position"] = i + 1
    return cleaned


def clean_quote(data: dict, creating: bool = False) -> dict:
    out: dict = {}
    for key, limit in QUOTE_LIMITS.items():
        text_field(data, key, limit, out)
    if (creating or "title" in out) and not out.get("title"):
        raise CrmError("La cotización necesita un título.")
    if "currency" in data:
        out["currency"] = clean_currency(data.get("currency"))
    for key, label in (("valid_until", "Válida hasta"), ("event_start", "Inicio del evento")):
        if key in data:
            out[key] = clean_date(data[key], label)
    for key, values, label in (("approval_status", APPROVALS, "aprobación"), ("invoice_status", INVOICE_STATUSES, "facturación")):
        if key in data:
            v = str(data[key] or "").strip()
            if v not in values:
                raise CrmError(f"El estado de {label} debe ser uno de: {', '.join(values)}.")
            out[key] = v
    for key in ("contact_id", "opportunity_id", "owner_staff_id", "terms_id", "template_id"):
        if key in data:
            v = data[key]
            out[key] = int(v) if str(v or "").isdigit() else None
    return out


def check_stage(current: str, new: str) -> None:
    if new not in QUOTE_STAGES:
        raise CrmError("Etapa de cotización no válida.")
    if new == current:
        raise CrmError("La cotización ya está en esa etapa.", 409)
    if new == "borrador" and current != "borrador":
        raise CrmError("Una cotización enviada no vuelve a borrador: crea una versión nueva.")


def is_expired(stage: str, valid_until: Optional[date], today: date) -> bool:
    """Vencida SIN temporizadores: se calcula al mostrar (una cotización abierta cuya fecha ya pasó)."""
    return stage in OPEN_QUOTE_STAGES and valid_until is not None and valid_until < today


def clean_proforma(data: dict) -> dict:
    out: dict = {}
    for key, limit in PROFORMA_LIMITS.items():
        text_field(data, key, limit, out)
    for key, label in (("issued_at", "Fecha de emisión"), ("due_at", "Vence")):
        if key in data:
            out[key] = clean_date(data[key], label)
    if "status" in data:
        v = str(data["status"] or "").strip()
        if v not in PROFORMA_STATUSES:
            raise CrmError(f"El estado de la proforma debe ser uno de: {', '.join(PROFORMA_STATUSES)}.")
        out["status"] = v
    return out


def clean_filter(data: dict) -> dict:
    """Filtro guardado: SOLO filtros estructurados (llave simple → valor corto). El texto libre `q` se descarta: podría ser el nombre de una persona (Ley 1581)."""
    scope = str(data.get("scope") or "").strip()
    if scope not in FILTER_SCOPES:
        raise CrmError("El filtro debe ser de cuentas, oportunidades, leads o cotizaciones.")
    name = (str(data.get("name") or "")).strip()
    if not name:
        raise CrmError("Ponle un nombre al filtro.")
    if len(name) > FILTER_NAME_MAX:
        raise CrmError(f"El nombre del filtro es demasiado largo (máximo {FILTER_NAME_MAX} caracteres).")
    raw = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    clean = {}
    for k, v in raw.items():
        if k in ("q", "search", "query") or not isinstance(k, str) or len(k) > 30:
            continue
        if isinstance(v, (str, int, bool)) and len(str(v)) <= 60 and v not in ("", None, False):
            clean[k] = v
    return {"scope": scope, "name": name, "filters": clean, "shared": bool(data.get("shared"))}


__all__ = ["CURRENCIES"]
