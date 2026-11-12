"""Lectura de valores de SuiteCRM (fechas, dinero, monedas, etapas, estados). Funciones puras, sin base de datos."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.crm import normalize, quote_rules as qr
from app.crm.errors import CrmError


def parse_date(value) -> Optional[date]:
    v = (value or "").strip()
    if not v:
        return None
    v = re.split(r"[ T]", v, maxsplit=1)[0]
    for pattern, order in ((r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", (0, 1, 2)), (r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", (2, 1, 0))):
        m = re.match(pattern, v)
        if m:
            g = [int(x) for x in m.groups()]
            try:
                return date(g[order[0]], g[order[1]], g[order[2]])
            except ValueError:
                break
    raise CrmError("Fecha no válida (usa año-mes-día o día/mes/año).")


def parse_datetime(value) -> Optional[datetime]:
    d = parse_date(value)
    if d is None:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", value or "")
    h, mi = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    if h > 23 or mi > 59:
        raise CrmError("Hora no válida.")
    return datetime(d.year, d.month, d.day, h, mi)


def parse_money(value, label: str = "Importe") -> Decimal:
    """«1.500.000,50», «1,500,000.50», «1500000.5», «$ 1.500.000» → Decimal. Dos decimales como máximo se toman como decimales."""
    v = re.sub(r"[^\d,.\-]", "", (value or "").strip())
    if not v:
        return Decimal("0")
    if "," in v and "." in v:
        dec_sep = "," if v.rfind(",") > v.rfind(".") else "."
        thou = "." if dec_sep == "," else ","
        v = v.replace(thou, "").replace(dec_sep, ".")
    elif "," in v or "." in v:
        sep = "," if "," in v else "."
        parts = v.split(sep)
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            v = parts[0] + "." + parts[1]
        else:
            v = v.replace(sep, "")
    try:
        d = Decimal(v)
    except InvalidOperation as exc:
        raise CrmError(f"«{label}» no es un número válido.") from exc
    if d < 0 or d > qr.MAX_MONEY:
        raise CrmError(f"«{label}» está fuera de rango.")
    return d


def map_currency(value, allowed) -> tuple:
    v = normalize(value)
    if not v:
        return "COP", False
    if v.upper() in allowed:
        return v.upper(), False
    if "usd" in v or "dolar" in v or v in ("us$", "us"):
        return "USD", False
    if "cop" in v or "peso" in v or v == "$":
        return "COP", False
    return "COP", True


STAGE_ALIASES = {
    "prospecto": "Prospecto", "prospecting": "Prospecto", "prospeccion": "Prospecto",
    "calificado": "Calificado", "qualification": "Calificado", "calificacion": "Calificado",
    "needs analysis": "Propuesta de valor", "analisis de necesidades": "Propuesta de valor", "value proposition": "Propuesta de valor", "propuesta de valor": "Propuesta de valor",
    "id. decision makers": "Propuesta de valor", "id decision makers": "Propuesta de valor", "perception analysis": "Propuesta de valor", "analisis de percepcion": "Propuesta de valor",
    "proposal/price quote": "Cotización enviada", "propuesta/cotizacion": "Cotización enviada", "propuesta": "Cotización enviada", "cotizacion enviada": "Cotización enviada",
    "negotiation/review": "Negociación", "negociacion/revision": "Negociación", "negociacion": "Negociación",
    "closed won": "Ganada", "cerrado ganado": "Ganada", "cerrada ganada": "Ganada", "ganada": "Ganada",
    "closed lost": "Perdida", "cerrado perdido": "Perdida", "cerrada perdida": "Perdida", "perdida": "Perdida",
}


def stage_for(stages: list, label: str) -> tuple:
    """(id, tipo, reconocida). Por nombre de fábrica; si el admin cambió el nombre, por tipo; si no se reconoce, la primera abierta."""
    wanted = STAGE_ALIASES.get(normalize(label))
    by_name = {s["name"]: s for s in stages}
    if wanted and wanted in by_name:
        s = by_name[wanted]
        return s["id"], s["kind"], True
    if wanted in ("Ganada", "Perdida"):
        kind = "won" if wanted == "Ganada" else "lost"
        s = next((x for x in stages if x["kind"] == kind), None)
        if s:
            return s["id"], kind, True
    s = next((x for x in stages if x["kind"] == "open"), None)
    if s is None:
        raise CrmError("El embudo no tiene una etapa abierta.")
    return s["id"], "open", False


KIND_ALIASES = {"llamada": "call", "call": "call", "calls": "call", "tarea": "task", "task": "task", "reunion": "meeting", "meeting": "meeting", "nota": "note", "note": "note"}
STATUS_ALIASES = {"planned": "planned", "planificada": "planned", "planificado": "planned", "pendiente": "planned", "not started": "planned", "no iniciada": "planned", "in progress": "planned", "en progreso": "planned",
                  "held": "done", "realizada": "done", "completed": "done", "completada": "done", "completado": "done", "hecha": "done", "not held": "cancelled", "no realizada": "cancelled",
                  "cancelled": "cancelled", "canceled": "cancelled", "cancelada": "cancelled", "deferred": "cancelled", "aplazada": "cancelled"}


QUOTE_STAGE_ALIASES = {"draft": "borrador", "borrador": "borrador", "delivered": "enviada", "enviada": "enviada", "entregada": "enviada", "negotiation": "negociada", "negociacion": "negociada",
                       "negociada": "negociada", "on hold": "negociada", "en espera": "negociada", "confirmed": "aprobada", "confirmada": "aprobada", "closed accepted": "aprobada",
                       "cerrada aceptada": "aprobada", "aprobada": "aprobada", "closed lost": "rechazada", "cerrada perdida": "rechazada", "closed dead": "rechazada", "cerrada muerta": "rechazada",
                       "rechazada": "rechazada"}


def line_data(r: dict) -> dict:
    return {"name": r.get("name"), "description": r.get("description") or None, "qty": str(parse_money(r.get("qty") or "1", "Cantidad")) if r.get("qty") else "1",
            "unit_price": str(parse_money(r.get("unit_price"), "Precio unitario")), "discount_percent": str(min(parse_money(r.get("discount_percent"), "Descuento"), Decimal("100"))),
            "tax_percent": str(parse_money(r.get("tax_percent"), "Impuesto")) if r.get("tax_percent") else "19"}


PROFORMA_STATUS_ALIASES = {"paid": "pagado", "pagado": "pagado", "pagada": "pagado", "unpaid": "no_pagado", "no pagado": "no_pagado", "no pagada": "no_pagado", "pendiente": "no_pagado",
                           "cancelled": "anulado", "anulado": "anulado", "anulada": "anulado"}
