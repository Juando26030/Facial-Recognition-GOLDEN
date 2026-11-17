"""Gastos de infraestructura (Fase 9C): lo que cuesta mantener viva la plataforma, por mes y POR EVENTO. Solo admin y super_admin (app/routers/gastos.py).

Lógica pura (validaciones, conversión de moneda, reparto por evento, mapeo de la exportación de Google) más lo poco que toca la base. Nada de datos personales: son montos de proveedores.

Reparto por evento (fórmula que también se muestra en pantalla):
  · costos VARIABLES (dependen del uso: Cloud Run, Storage, Neon cómputo…): el costo del mes se reparte según la parte de ACTIVIDAD de cada evento en ese mes
    (ingresos registrados del evento ÷ ingresos de todos los eventos del mes; la persona de prueba nunca cuenta).
  · costos FIJOS (no dependen del uso: dominio, Microsoft 365, GitHub, Cloudflare…): se reparten según los DÍAS ACTIVOS del evento en el mes
    (días del evento dentro del mes ÷ suma de días de todos los eventos del mes).
  · Parámetro `infra_alloc_basis` (editable): «auto» (lo anterior), «activity» (todo por actividad) o «days» (todo por días activos).
  · Si en un mes no hay base para repartir (sin ingresos, o sin eventos con fechas) el costo queda «sin asignar» y se ve así; nunca se inventa."""
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AccessLog, AppSetting, Event, InfraCost
from app.testperson import TEST_ID
from app.timeutil import utcnow

log = logging.getLogger("golden.infra")

# proveedor -> (nombre en pantalla, grupo del gráfico). Los grupos son los que tienen color propio; el resto va a «Otros».
PROVIDERS = {
    "google": ("Google Cloud", "google"), "neon": ("Neon (base de datos)", "neon"), "microsoft": ("Microsoft (OneDrive / 365)", "microsoft"),
    "cloudflare": ("Cloudflare", "cloudflare"), "domain": ("Dominio", "otros"), "github": ("GitHub", "otros"), "other": ("Otro", "otros"),
}
GROUPS = ("google", "neon", "microsoft", "cloudflare", "otros")
GROUP_LABELS = {"google": "Google Cloud", "neon": "Neon", "microsoft": "Microsoft", "cloudflare": "Cloudflare", "otros": "Otros"}
KINDS = ("fixed", "variable")
CURRENCIES = ("COP", "USD")
BASES = ("auto", "activity", "days")
SETTING_BASIS = "infra_alloc_basis"
SETTING_TRM = "infra_trm_default"
MAX_AMOUNT = Decimal("99999999999.99")
MAX_ATTACH = 5 * 1024 * 1024
ATTACH_TYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}
LOCAL_UTC_OFFSET_H = 5          # Colombia (UTC-5, sin horario de verano): el mes de un ingreso se mide en hora local

FORMULA = ("Costos variables (Cloud Run, Storage, Neon…): se reparten según la parte de ingresos registrados de cada evento en el mes. "
           "Costos fijos (dominio, Microsoft 365, GitHub, Cloudflare…): se reparten según los días activos de cada evento en el mes. "
           "La persona de prueba nunca cuenta. Si un mes no tiene base para repartir, el costo queda «sin asignar».")
BASIS_LABELS = {"auto": "Variables por ingresos y fijos por días activos (recomendado)", "activity": "Todo por ingresos registrados", "days": "Todo por días activos"}

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_CENT = Decimal("0.01")


class InfraError(ValueError):
    """Dato inválido: el mensaje (en español) se muestra tal cual al usuario."""


# ------------------------------------------------------------------------------------------------ validación y moneda
def valid_month(m) -> str:
    m = str(m or "").strip()
    if not _MONTH_RE.match(m):
        raise InfraError("El mes debe tener el formato AAAA-MM (por ejemplo 2026-11)")
    return m


def month_add(m: str, n: int) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    t = y * 12 + (mo - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def months_between(first: str, last: str) -> list:
    """Meses AAAA-MM de `first` a `last` (incluidos); tope 36 para no pedir de más."""
    valid_month(first)
    valid_month(last)
    if first > last:
        raise InfraError("El mes inicial no puede ser posterior al final")
    out, cur = [], first
    while cur <= last and len(out) < 36:
        out.append(cur)
        cur = month_add(cur, 1)
    return out


def current_month(now: Optional[datetime] = None) -> str:
    n = (now or utcnow()) - timedelta(hours=LOCAL_UTC_OFFSET_H)
    return f"{n.year:04d}-{n.month:02d}"


def _dec(v, field: str, allow_none: bool = False) -> Optional[Decimal]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if allow_none:
            return None
        raise InfraError(f"Falta {field}")
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except Exception:  # noqa: BLE001
        raise InfraError(f"{field.capitalize()} no es un número válido") from None
    if not d.is_finite():
        raise InfraError(f"{field.capitalize()} no es un número válido")
    return d


def to_cop(amount: Decimal, currency: str, trm: Optional[Decimal]) -> Decimal:
    """Monto en pesos. Un monto en USD exige la TRM del día (pesos por dólar), que se guarda con el registro para que el histórico no cambie."""
    if currency == "COP":
        return amount.quantize(_CENT, ROUND_HALF_UP)
    if not trm or trm <= 0:
        raise InfraError("Un monto en USD necesita la TRM del día (pesos por dólar)")
    return (amount * trm).quantize(_CENT, ROUND_HALF_UP)


def clean_entry(data: dict) -> dict:
    """Valida y normaliza un gasto manual. Devuelve los campos del modelo (incluido `amount_cop`)."""
    d = data or {}
    month = valid_month(d.get("month"))
    provider = str(d.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise InfraError("Elige un proveedor de la lista")
    concept = " ".join(str(d.get("concept") or "").split())
    if not concept:
        raise InfraError("Escribe el concepto (por ejemplo «Cloud Run» o «Dominio golden-eventos.com»)")
    if len(concept) > 160:
        raise InfraError("El concepto es demasiado largo (máximo 160 caracteres)")
    kind = str(d.get("kind") or "variable").strip().lower()
    if kind not in KINDS:
        raise InfraError("El tipo debe ser «fijo» o «variable»")
    currency = str(d.get("currency") or "COP").strip().upper()
    if currency not in CURRENCIES:
        raise InfraError("La moneda debe ser COP o USD")
    amount = _dec(d.get("amount"), "el monto")
    if amount < 0 or amount > MAX_AMOUNT:
        raise InfraError("El monto debe ser positivo (un abono o crédito se registra restando en otro renglón con la nota)")
    trm = _dec(d.get("trm"), "la TRM", allow_none=True)
    if currency == "USD" and (trm is None or trm <= 0):
        raise InfraError("Un monto en USD necesita la TRM del día (pesos por dólar)")
    if currency == "COP":
        trm = None
    note = " ".join(str(d.get("note") or "").split())[:300] or None
    return {"month": month, "provider": provider, "concept": concept, "kind": kind, "currency": currency, "amount": amount.quantize(_CENT, ROUND_HALF_UP),
            "trm": trm.quantize(_CENT, ROUND_HALF_UP) if trm is not None else None, "amount_cop": to_cop(amount, currency, trm), "note": note}


def group_of(provider: str) -> str:
    return PROVIDERS.get(provider, PROVIDERS["other"])[1]


def row_dict(c: InfraCost) -> dict:
    return {"id": c.id, "month": c.month, "provider": c.provider, "provider_label": PROVIDERS.get(c.provider, PROVIDERS["other"])[0], "concept": c.concept, "kind": c.kind,
            "currency": c.currency, "amount": float(c.amount), "trm": float(c.trm) if c.trm is not None else None, "amount_cop": float(c.amount_cop),
            "source": c.source, "note": c.note, "has_attachment": bool(c.attachment_key), "attachment_name": c.attachment_name}


# ------------------------------------------------------------------------------------------------ parámetros
def get_basis(db: Session) -> str:
    row = db.get(AppSetting, SETTING_BASIS)
    return row.value if row and row.value in BASES else "auto"


def get_trm_default(db: Session) -> Optional[Decimal]:
    row = db.get(AppSetting, SETTING_TRM)
    try:
        v = Decimal(row.value) if row and row.value else None
    except Exception:  # noqa: BLE001
        return None
    return v if v and v > 0 else None


def _set(db: Session, key: str, value: Optional[str]) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value, row.updated_at = value, utcnow()
    db.flush()          # la sesión no autoflushea: sin esto la lectura de justo después (la respuesta del PUT) veía el valor viejo


def save_settings(db: Session, data: dict) -> dict:
    d = data or {}
    if "basis" in d:
        b = str(d.get("basis") or "").strip().lower()
        if b not in BASES:
            raise InfraError("El criterio de reparto no es válido")
        _set(db, SETTING_BASIS, b)
    if "trm_default" in d:
        t = _dec(d.get("trm_default"), "la TRM", allow_none=True)
        if t is not None and (t <= 0 or t > Decimal("100000")):
            raise InfraError("La TRM debe ser un valor positivo en pesos por dólar")
        _set(db, SETTING_TRM, str(t.quantize(_CENT)) if t is not None else None)
    return {"basis": get_basis(db), "trm_default": float(get_trm_default(db)) if get_trm_default(db) else None}


# ------------------------------------------------------------------------------------------------ actividad y días por evento
def event_days_in_month(start: Optional[date], end: Optional[date], month: str) -> int:
    """Días del evento (inclusive) que caen dentro del mes. Sin fecha de inicio no hay días; sin fecha de fin dura un día."""
    if not start:
        return 0
    end = end or start
    if end < start:
        end = start
    y, mo = int(month[:4]), int(month[5:7])
    first, last = date(y, mo, 1), date(y, mo, monthrange(y, mo)[1])
    lo, hi = max(start, first), min(end, last)
    return max(0, (hi - lo).days + 1)


def activity_by_event_month(db: Session, first: str, last: str) -> dict:
    """{(event_id, 'AAAA-MM'): ingresos} en el rango (hora local), SIN la persona de prueba."""
    y, mo = int(first[:4]), int(first[5:7])
    lo = datetime(y, mo, 1) + timedelta(hours=LOCAL_UTC_OFFSET_H)
    ny = month_add(last, 1)
    hi = datetime(int(ny[:4]), int(ny[5:7]), 1) + timedelta(hours=LOCAL_UTC_OFFSET_H)
    local = func.to_char(AccessLog.timestamp - timedelta(hours=LOCAL_UTC_OFFSET_H), "YYYY-MM")
    rows = (db.query(AccessLog.event_id, local, func.count(AccessLog.id))
            .filter(AccessLog.event_id.isnot(None), AccessLog.timestamp >= lo, AccessLog.timestamp < hi, func.upper(func.trim(AccessLog.user_id)) != TEST_ID)
            .group_by(AccessLog.event_id, local).all())
    return {(eid, m): int(n) for eid, m, n in rows}


def events_info(db: Session, ids) -> dict:
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    return {e.id: e for e in db.query(Event).filter(Event.id.in_(ids)).all()}


def allocate(costs: list, activity: dict, days: dict, basis: str = "auto") -> dict:
    """Reparte el costo de cada mes entre los eventos.

    costs:    [{'month', 'kind', 'amount_cop'}]
    activity: {(event_id, month): ingresos}
    days:     {(event_id, month): días activos}
    Devuelve {'events': {event_id: {'total', 'fixed', 'variable', 'activity', 'days'}}, 'unassigned': {month: monto}, 'by_month': {month: {event_id: monto}}}.
    """
    if basis not in BASES:
        basis = "auto"
    months = sorted({c["month"] for c in costs})
    fixed_m, var_m = defaultdict(Decimal), defaultdict(Decimal)
    for c in costs:
        (fixed_m if c["kind"] == "fixed" else var_m)[c["month"]] += Decimal(str(c["amount_cop"]))
    events: dict = {}
    by_month: dict = {}
    unassigned: dict = defaultdict(Decimal)

    def ev(eid):
        return events.setdefault(eid, {"total": Decimal(0), "fixed": Decimal(0), "variable": Decimal(0), "activity": 0, "days": 0})

    for m in months:
        act = {e: n for (e, mm), n in activity.items() if mm == m and n > 0}
        dys = {e: n for (e, mm), n in days.items() if mm == m and n > 0}
        for e, n in act.items():
            ev(e)["activity"] += n
        for e, n in dys.items():
            ev(e)["days"] += n
        by_month[m] = defaultdict(Decimal)
        for kind, total in (("fixed", fixed_m[m]), ("variable", var_m[m])):
            if total <= 0:
                continue
            use = "days" if basis == "days" else "activity" if basis == "activity" else ("days" if kind == "fixed" else "activity")
            weights = dys if use == "days" else act
            if not weights:                                     # el criterio elegido no tiene datos ese mes: se prueba el otro antes de dejarlo sin asignar
                weights = act if use == "days" else dys
            s = sum(weights.values())
            if not s:
                unassigned[m] += total
                continue
            given = Decimal(0)
            items = sorted(weights.items())
            for i, (e, w) in enumerate(items):
                part = (total - given) if i == len(items) - 1 else (total * Decimal(w) / Decimal(s)).quantize(_CENT, ROUND_HALF_UP)
                given += part
                ev(e)[kind] += part
                ev(e)["total"] += part
                by_month[m][e] += part
    return {"events": events, "unassigned": dict(unassigned), "by_month": {m: dict(v) for m, v in by_month.items()}}


# ------------------------------------------------------------------------------------------------ resumen para la pantalla
def summary(db: Session, first: str, last: str) -> dict:
    months = months_between(first, last)
    rows = db.query(InfraCost).filter(InfraCost.month >= months[0], InfraCost.month <= months[-1]).all()
    series = {g: {m: Decimal(0) for m in months} for g in GROUPS}
    totals = {m: Decimal(0) for m in months}
    by_provider: dict = defaultdict(Decimal)
    by_concept: dict = defaultdict(Decimal)
    costs = []
    for c in rows:
        series[group_of(c.provider)][c.month] += c.amount_cop
        totals[c.month] += c.amount_cop
        by_provider[c.provider] += c.amount_cop
        by_concept[(c.provider, c.concept)] += c.amount_cop
        costs.append({"month": c.month, "kind": c.kind, "amount_cop": c.amount_cop})
    activity = activity_by_event_month(db, months[0], months[-1])
    candidates = db.query(Event).filter(Event.start_date.isnot(None), Event.status != "creado").all()
    y, mo = int(months[0][:4]), int(months[0][5:7])
    lo_d = date(y, mo, 1)
    ly, lm = int(months[-1][:4]), int(months[-1][5:7])
    hi_d = date(ly, lm, monthrange(ly, lm)[1])
    days = {}
    for e in candidates:
        if (e.end_date or e.start_date) < lo_d or e.start_date > hi_d:
            continue
        for m in months:
            n = event_days_in_month(e.start_date, e.end_date, m)
            if n:
                days[(e.id, m)] = n
    basis = get_basis(db)
    alloc = allocate(costs, activity, days, basis)
    info = events_info(db, alloc["events"].keys())
    ev_rows = []
    for eid, v in alloc["events"].items():
        e = info.get(eid)
        if not e or v["total"] <= 0:
            continue
        ev_rows.append({"event_id": eid, "code": e.event_code, "name": e.name, "total": float(v["total"]), "fixed": float(v["fixed"]), "variable": float(v["variable"]),
                        "activity": v["activity"], "days": v["days"]})
    ev_rows.sort(key=lambda r: -r["total"])
    grand = sum(totals.values(), Decimal(0))
    n_active = sum(1 for m in months if totals[m] > 0)
    n_events = len(ev_rows)
    unassigned = sum(alloc["unassigned"].values(), Decimal(0))
    return {
        "months": months,
        "series": {g: [float(series[g][m]) for m in months] for g in GROUPS},
        "group_labels": GROUP_LABELS,
        "totals": [float(totals[m]) for m in months],
        "grand_total": float(grand),
        "monthly_avg": float(grand / n_active) if n_active else 0.0,
        "by_provider": [{"provider": p, "label": PROVIDERS[p][0], "total": float(t)} for p, t in sorted(by_provider.items(), key=lambda kv: -kv[1])],
        "by_concept": [{"provider": p, "concept": c, "label": PROVIDERS[p][0], "total": float(t)} for (p, c), t in sorted(by_concept.items(), key=lambda kv: -kv[1])[:12]],
        "events": ev_rows,
        "events_total": float(grand - unassigned),
        "avg_per_event": float((grand - unassigned) / n_events) if n_events else 0.0,
        "unassigned": float(unassigned),
        "unassigned_months": sorted(alloc["unassigned"].keys()),
        "basis": basis, "basis_labels": BASIS_LABELS, "formula": FORMULA,
        "trm_default": float(get_trm_default(db)) if get_trm_default(db) else None,
        "gcp_export_configured": bool(os.getenv("GCP_BILLING_EXPORT_TABLE", "").strip()),
        "neon_configured": neon_configured(),
    }


# ------------------------------------------------------------------------------------------------ Excel
def export_rows(db: Session, first: str, last: str) -> list:
    valid_month(first)
    valid_month(last)
    rows = db.query(InfraCost).filter(InfraCost.month >= first, InfraCost.month <= last).order_by(InfraCost.month, InfraCost.provider, InfraCost.concept, InfraCost.id).all()
    return [row_dict(c) for c in rows]


def build_workbook(db: Session, first: str, last: str) -> bytes:
    """Libro con la tabla de gastos y el reparto por evento. Pasa por `xlsafe` (un texto que empiece por «=» no se ejecuta en Excel)."""
    import io

    from openpyxl import Workbook

    from app.xlsafe import safe_workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Gastos"
    ws.append(["Mes", "Proveedor", "Concepto", "Tipo", "Moneda", "Monto", "TRM", "Monto en COP", "Origen", "Nota"])
    for r in export_rows(db, first, last):
        ws.append([r["month"], r["provider_label"], r["concept"], "Fijo" if r["kind"] == "fixed" else "Variable", r["currency"], r["amount"], r["trm"], r["amount_cop"],
                   "Importado de Google" if r["source"] == "gcp_export" else "Manual", r["note"]])
    s = summary(db, first, last)
    ws2 = wb.create_sheet("Por evento")
    ws2.append(["Evento", "Código", "Costo total COP", "Parte fija", "Parte variable", "Ingresos del periodo", "Días activos"])
    for e in s["events"]:
        ws2.append([e["name"], e["code"], e["total"], e["fixed"], e["variable"], e["activity"], e["days"]])
    ws2.append([])
    ws2.append(["Sin asignar", None, s["unassigned"]])
    ws2.append(["Criterio", BASIS_LABELS.get(s["basis"], s["basis"])])
    ws2.append(["Fórmula", FORMULA])
    ws3 = wb.create_sheet("Por mes")
    ws3.append(["Mes"] + [GROUP_LABELS[g] for g in GROUPS] + ["Total COP"])
    for i, m in enumerate(s["months"]):
        ws3.append([m] + [s["series"][g][i] for g in GROUPS] + [s["totals"][i]])
    safe_workbook(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ importación automática de Google (OPCIONAL)
# proyecto (6-30: minúscula inicial, minúsculas/dígitos/guiones, sin guion final) . conjunto (letras/dígitos/_) . tabla (letras/dígitos/_).
_GCP_TABLE_RE = re.compile(r"([a-z][a-z0-9-]{4,28}[a-z0-9])\.([A-Za-z_][A-Za-z0-9_]{0,1023})\.([A-Za-z_][A-Za-z0-9_]{0,1023})")
BQ_API = "https://bigquery.googleapis.com/bigquery/v2"
BQ_SCOPE = "https://www.googleapis.com/auth/bigquery.readonly"
BQ_TIMEOUT_S = 50                # tope total de la consulta (cabe en una petición de 60 s si se dispara desde el botón)
BQ_MAX_PAGES = 50


def gcp_table() -> str:
    """`proyecto.conjunto.tabla` de la exportación de facturación a BigQuery, de GCP_BILLING_EXPORT_TABLE. Se valida con una expresión ESTRICTA porque se interpola
    en la consulta (entre comillas invertidas): sin comillas, espacios, puntos de más ni el prefijo «dominio:» de proyectos antiguos."""
    t = os.getenv("GCP_BILLING_EXPORT_TABLE", "").strip()
    if not t:
        return ""
    if not _GCP_TABLE_RE.fullmatch(t):
        raise InfraError("GCP_BILLING_EXPORT_TABLE debe tener la forma proyecto.conjunto.tabla")
    return t


def map_gcp_rows(rows, trm_default: Optional[Decimal]) -> tuple:
    """Filas de la exportación (`invoice_month` AAAAMM, `service`, `currency`, `net_cost`) -> (gastos por insertar, avisos). Función pura: la prueba no necesita BigQuery.
    En COP el monto va tal cual; en USD se usa la TRM por defecto del parámetro (sin ella la fila se omite con aviso). Un neto <= 0 (crédito mayor al uso) no se registra."""
    out, warns = [], []
    for r in rows:
        im = str(r.get("invoice_month") or "")
        if not re.fullmatch(r"\d{6}", im):
            continue
        month = f"{im[:4]}-{im[4:]}"
        service = " ".join(str(r.get("service") or "Sin servicio").split())[:100]
        cur = str(r.get("currency") or "").upper()
        try:
            net = Decimal(str(r.get("net_cost")))
        except Exception:  # noqa: BLE001
            continue
        if net <= 0:
            continue
        if cur not in CURRENCIES:
            warns.append(f"{month} {service}: moneda {cur or '?'} no soportada")
            continue
        if cur == "USD" and not trm_default:
            warns.append(f"{month} {service}: falta la TRM por defecto para convertir USD (configúrala en Parámetros del panel)")
            continue
        out.append({"month": month, "provider": "google", "concept": service, "kind": "variable", "currency": cur, "amount": net.quantize(_CENT, ROUND_HALF_UP),
                    "trm": trm_default if cur == "USD" else None, "amount_cop": to_cop(net, cur, trm_default), "source_key": f"gcp:{month}:{service}"})
    return out, warns


class _BigQueryError(RuntimeError):
    """Falla de la API de BigQuery. El mensaje lleva solo el código HTTP y el motivo de Google (nunca la consulta, tokens ni encabezados)."""


def _bq_session():
    import google.auth                                   # viene con google-cloud-storage (no hace falta google-cloud-bigquery)
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=[BQ_SCOPE])
    return AuthorizedSession(creds)


def _bq_json(resp) -> dict:
    if resp.status_code != 200:
        try:
            reason = (resp.json().get("error") or {}).get("status") or ""
        except Exception:  # noqa: BLE001
            reason = ""
        raise _BigQueryError(f"BigQuery respondió HTTP {resp.status_code} {str(reason)[:60]}".strip())
    return resp.json()


def _bq_rows(js: dict) -> list:
    names = [f["name"] for f in ((js.get("schema") or {}).get("fields") or [])]
    return [{n: (c or {}).get("v") for n, c in zip(names, r.get("f") or [])} for r in (js.get("rows") or [])]


def _query_gcp(table: str, month: str, session=None, clock=None) -> list:
    """Consulta la exportación de facturación por la API REST de BigQuery (jobs.query + getQueryResults con paginación). `session` = algo con
    `.post/.get(url, json=, params=, timeout=)` que devuelve respuestas tipo requests (en las pruebas se simula). El proyecto de la consulta = primera parte de la tabla."""
    import time
    m = _GCP_TABLE_RE.fullmatch(table or "")
    if not m:
        raise InfraError("GCP_BILLING_EXPORT_TABLE debe tener la forma proyecto.conjunto.tabla")
    project = m.group(1)
    ym = valid_month(month).replace("-", "")
    sql = (f"SELECT invoice.month AS invoice_month, service.description AS service, currency, "
           f"SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost "
           f"FROM `{table}` WHERE invoice.month = @ym GROUP BY 1, 2, 3")
    clock = clock or time.monotonic
    deadline = clock() + BQ_TIMEOUT_S
    s = session or _bq_session()
    base = f"{BQ_API}/projects/{urllib.parse.quote(project, safe='')}/queries"
    body = {"query": sql, "useLegacySql": False, "parameterMode": "NAMED", "timeoutMs": 20000, "maxResults": 1000,
            "queryParameters": [{"name": "ym", "parameterType": {"type": "STRING"}, "parameterValue": {"value": ym}}]}
    js = _bq_json(s.post(base, json=body, timeout=30))
    ref = js.get("jobReference") or {}
    job_id, location = ref.get("jobId"), ref.get("location")
    rows: list = []
    pages = 0
    while True:
        if js.get("jobComplete") is False:
            if clock() > deadline:
                raise _BigQueryError("BigQuery no terminó la consulta a tiempo")
        else:
            rows += _bq_rows(js)
            if not js.get("pageToken"):
                return rows
            pages += 1
            if pages >= BQ_MAX_PAGES or clock() > deadline:
                raise _BigQueryError("La respuesta de BigQuery tiene demasiadas páginas o tardó demasiado")
        if not job_id:
            raise _BigQueryError("BigQuery no devolvió el identificador de la consulta")
        params = {"timeoutMs": 10000, "maxResults": 1000}
        if location:
            params["location"] = location
        if js.get("jobComplete") is not False and js.get("pageToken"):
            params["pageToken"] = js["pageToken"]
        js = _bq_json(s.get(f"{base}/{urllib.parse.quote(job_id, safe='')}", params=params, timeout=30))


def import_google(db: Session, month: Optional[str] = None, query=_query_gcp) -> dict:
    """Trae de la exportación de facturación de Google el costo NETO (con créditos) del mes por servicio y lo guarda como gastos `source='gcp_export'`. Idempotente:
    cada (mes, servicio) se actualiza, nunca se duplica; lo registrado a mano no se toca. Sin GCP_BILLING_EXPORT_TABLE no hace nada."""
    table = gcp_table()
    if not table:
        return {"configured": False, "imported": 0, "updated": 0, "warnings": []}
    months = [valid_month(month)] if month else [current_month(), month_add(current_month(), -1)]      # mes en curso y anterior: Google cierra la factura de un mes durante el siguiente
    imported = updated = 0
    warns: list = []
    for m in months:
        items, w = map_gcp_rows(query(table, m), get_trm_default(db))
        warns += w
        for it in items:
            row = db.query(InfraCost).filter(InfraCost.source_key == it["source_key"]).first()
            if row is None:
                db.add(InfraCost(source="gcp_export", **it))
                imported += 1
            elif row.source == "gcp_export":
                row.amount, row.currency, row.trm, row.amount_cop, row.updated_at = it["amount"], it["currency"], it["trm"], it["amount_cop"], utcnow()
                updated += 1
    db.commit()
    return {"configured": True, "imported": imported, "updated": updated, "warnings": warns[:20]}


# ------------------------------------------------------------------------------------------------ Neon (SOLO uso; el costo se registra a mano)
def neon_configured() -> bool:
    return bool(os.getenv("NEON_API_KEY", "").strip() and os.getenv("NEON_ORG_ID", "").strip())


def neon_usage(month: str, fetch=None) -> dict:
    """Uso de Neon del mes según su API (`GET /consumption_history/v2/projects`, granularidad mensual, requiere plan Launch o superior). Verificado en la documentación oficial
    de Neon: esa API devuelve CONSUMO (segundos de cómputo, bytes de almacenamiento…), NO dinero; por eso el costo de Neon se sigue registrando a mano y esto sirve para ver
    si el uso subió. Variables: NEON_API_KEY y NEON_ORG_ID. Sin ellas, o si la API falla, devuelve `available: False` (nunca rompe la pantalla)."""
    month = valid_month(month)
    if not neon_configured():
        return {"available": False, "reason": "Falta NEON_API_KEY y NEON_ORG_ID en el entorno"}
    y, mo = int(month[:4]), int(month[5:7])
    q = urllib.parse.urlencode({"from": f"{month}-01T00:00:00Z", "to": f"{month}-{monthrange(y, mo)[1]:02d}T23:59:59Z", "granularity": "monthly",
                                "org_id": os.environ["NEON_ORG_ID"].strip(), "metrics": "compute_unit_seconds,root_branch_bytes_month,child_branch_bytes_month", "limit": "100"})
    url = f"https://console.neon.tech/api/v2/consumption_history/v2/projects?{q}"

    def default_fetch(u):
        req = urllib.request.Request(u, headers={"Authorization": "Bearer " + os.environ["NEON_API_KEY"].strip(), "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:             # noqa: S310 — URL fija de Neon
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = (fetch or default_fetch)(url)
    except Exception as e:  # noqa: BLE001
        log.warning("Neon consumo: %s", type(e).__name__)
        return {"available": False, "reason": "No se pudo consultar la API de Neon (revisa la llave y el plan)"}
    compute = 0.0
    for p in data.get("projects", []) or []:
        for per in p.get("periods", []) or []:
            for c in per.get("consumption", []) or []:
                compute += float(c.get("compute_time_seconds") or 0)
    return {"available": True, "month": month, "compute_hours": round(compute / 3600, 1), "projects": len(data.get("projects", []) or [])}


# ------------------------------------------------------------------------------------------------ Fase 10 B: estado de las conexiones y carga por archivo
TABLE_MISSING = ("Falta aplicar una actualización de la base de datos de este entorno (la migración 0121_infra_costs). "
                 "Hasta entonces los gastos no se pueden guardar ni mostrar. Avísale al administrador técnico.")


def table_ready(db: Session) -> bool:
    """¿Existe la tabla `infra_costs` en esta base? (si la migración 0121 no se aplicó, el panel lo dice en vez de fallar con un error técnico)."""
    from sqlalchemy import inspect
    try:
        return bool(inspect(db.get_bind()).has_table("infra_costs"))
    except Exception:  # noqa: BLE001
        log.warning("no se pudo comprobar la tabla infra_costs", exc_info=True)
        return False


def connections(db: Optional[Session] = None) -> list:
    """Estado de cada fuente de datos de la pantalla de gastos, en lenguaje simple: `state` = ok | missing | error. Nunca revela valores (solo NOMBRES de variables).
    Lo manual siempre está disponible: ninguna conexión es obligatoria para usar el panel."""
    out = []
    # --- Google Cloud (exportación de facturación a BigQuery)
    raw = os.getenv("GCP_BILLING_EXPORT_TABLE", "").strip()
    google = {"key": "google", "title": "Google Cloud (facturación automática)", "env": ["GCP_BILLING_EXPORT_TABLE"],
              "iam": ["BigQuery Job User (roles/bigquery.jobUser) en el proyecto de la tabla", "BigQuery Data Viewer (roles/bigquery.dataViewer) en el conjunto de datos de la exportación",
                      "A la cuenta de servicio del servicio «web» y a la del Job de operaciones"]}
    if not raw:
        google.update(state="missing", summary="No conectado: falta la variable GCP_BILLING_EXPORT_TABLE.",
                      steps=["En Google Cloud → Facturación → «Exportación de facturación», activa la exportación estándar a BigQuery.",
                             "Copia el nombre de la tabla (proyecto.conjunto.tabla).",
                             "Guárdalo como variable GCP_BILLING_EXPORT_TABLE del entorno y vuelve a desplegar.",
                             "Dale a las cuentas de servicio los permisos de BigQuery indicados abajo.",
                             "Mientras tanto puedes registrar el gasto de Google a mano o subir un archivo."])
    elif not _GCP_TABLE_RE.fullmatch(raw):
        google.update(state="error", summary="La variable GCP_BILLING_EXPORT_TABLE está mal escrita: debe verse como proyecto.conjunto.tabla.",
                      steps=["Corrige el valor (tres partes separadas por puntos, sin comillas ni espacios) y vuelve a desplegar."])
    else:
        google.update(state="ok", summary="Conectado: la facturación de Google se importa sola cada domingo a las 12 m. (hora de Colombia) y también con el botón «Importar Google ahora».", steps=[])
        if db is not None:
            try:
                last = db.query(func.max(InfraCost.updated_at)).filter(InfraCost.source == "gcp_export").scalar()
                google["last_import"] = last.isoformat() if last else None
            except Exception:  # noqa: BLE001
                google["last_import"] = None
    out.append(google)
    # --- Neon (solo uso)
    neon = {"key": "neon", "title": "Neon (uso de la base de datos)", "env": ["NEON_API_KEY", "NEON_ORG_ID"], "iam": []}
    if neon_configured():
        neon.update(state="ok", summary="Conectado: se ve el uso de cómputo. El dinero de Neon se registra a mano.", steps=[])
    else:
        missing = [k for k in ("NEON_API_KEY", "NEON_ORG_ID") if not os.getenv(k, "").strip()]
        neon.update(state="missing", summary="No conectado: falta " + " y ".join(missing) + ". Es opcional: solo muestra el uso, no el dinero.",
                    steps=["En Neon crea una llave de API y copia el id de la organización.", "Guárdalos como NEON_API_KEY (secreto) y NEON_ORG_ID del servicio «web»."])
    out.append(neon)
    # --- Manual / archivo
    out.append({"key": "manual", "title": "Gastos a mano o por archivo", "state": "ok", "env": [], "iam": [],
                "summary": "Siempre disponible: «Registrar gasto» o «Subir archivo» (CSV de Excel). Sirve para Microsoft, Neon, dominio, GitHub, Cloudflare y para Google si aún no está conectado.", "steps": []})
    return out


_COL = {"month": ("mes", "month", "invoice_month", "periodo"), "provider": ("proveedor", "provider"), "concept": ("concepto", "concept", "service", "servicio", "descripcion"),
        "kind": ("tipo", "kind"), "currency": ("moneda", "currency"), "amount": ("monto", "amount", "net_cost", "costo", "valor", "total"), "trm": ("trm",), "note": ("nota", "note", "notas")}
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 1000


def _norm(s) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _csv_number(v, decimal_comma: bool = False) -> str:
    """Número como lo escribe Excel: con `;` de separador (Excel en español) el punto es de miles y la coma decimal («$ 1.234.567,89»); con `,` de separador el punto es decimal
    y una coma es de miles («1,234.50»; «19,5» se lee 19.5). Devuelve texto con punto decimal y sin separadores de miles."""
    t = re.sub(r"[^\d.,-]", "", str(v or ""))
    if decimal_comma:
        return t.replace(".", "").replace(",", ".")
    if "," in t and "." in t:
        return t.replace(",", "")
    if "," in t:
        parts = t.split(",")
        return parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) != 3 else t.replace(",", "")
    return t


def _csv_month(v) -> str:
    t = str(v or "").strip()
    m = re.fullmatch(r"(\d{4})[-/]?(\d{2})", t)
    if not m:
        raise InfraError("el mes debe verse como 2026-11")
    return valid_month(f"{m.group(1)}-{m.group(2)}")


def parse_csv(text: str, trm_default: Optional[Decimal] = None) -> tuple:
    """Archivo CSV (coma o punto y coma; el que guarda Excel) -> (gastos listos, avisos). Función pura. Columnas aceptadas (en español o inglés): mes, proveedor, concepto, tipo,
    moneda, monto, trm, nota. Sirve también la exportación de Google (invoice_month, service, currency, net_cost): sin columna de proveedor se asume Google. Cada fila inválida
    se omite con un aviso que dice cuál es; las demás se cargan."""
    import csv
    import hashlib
    import io
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise InfraError("El archivo está vacío")
    head = text.splitlines()[0]
    delim = ";" if head.count(";") > head.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = [_norm(h) for h in next(reader, [])]
    idx = {}
    for field, names in _COL.items():
        for n in names:
            if n in header and field not in idx:
                idx[field] = header.index(n)
    if "month" not in idx or "amount" not in idx or "concept" not in idx:
        raise InfraError("El archivo necesita al menos las columnas: mes, concepto y monto (la primera fila debe ser el encabezado)")
    labels = {_norm(v[0]): k for k, v in PROVIDERS.items()}
    labels.update({k: k for k in PROVIDERS})
    items, warns, seen = [], [], {}
    for n, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        if n - 1 > MAX_CSV_ROWS:
            warns.append(f"Solo se leen las primeras {MAX_CSV_ROWS} filas")
            break

        def cell(field):
            i = idx.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        try:
            prov_raw = _norm(cell("provider"))
            if prov_raw:
                if prov_raw not in labels:
                    raise InfraError("el proveedor no está en la lista (google, neon, microsoft, cloudflare, domain, github, other)")
                provider = labels[prov_raw]
            elif "provider" not in idx:
                provider = "google"
            else:
                raise InfraError("falta el proveedor")
            kind_raw = _norm(cell("kind"))
            kind = {"fijo": "fixed", "fija": "fixed", "fixed": "fixed", "variable": "variable", "": "variable"}.get(kind_raw)
            if kind is None:
                raise InfraError("el tipo debe ser fijo o variable")
            cur = cell("currency").upper() or "COP"
            trm = _csv_number(cell("trm"), delim == ";") if cell("trm") else (str(trm_default) if cur == "USD" and trm_default else "")
            entry = clean_entry({"month": _csv_month(cell("month")), "provider": provider, "concept": cell("concept"), "kind": kind, "currency": cur,
                                 "amount": _csv_number(cell("amount"), delim == ";"), "trm": trm, "note": cell("note")})
        except InfraError as e:
            warns.append(f"Fila {n}: {e}")
            continue
        key = "archivo:%s:%s:%s" % (entry["month"], entry["provider"], hashlib.sha1(entry["concept"].lower().encode()).hexdigest()[:20])
        if key in seen:
            warns.append(f"Fila {n}: {entry['month']} {entry['concept']} está repetida; se usó la última")
            items[seen[key]] = {**entry, "source_key": key}
            continue
        seen[key] = len(items)
        items.append({**entry, "source_key": key})
    return items, warns


def import_csv(db: Session, text: str) -> dict:
    """Carga los gastos de un CSV como `source='archivo'`. Idempotente: volver a subir el mismo archivo (o uno corregido) actualiza esos renglones, no los duplica; lo
    registrado a mano o importado de Google no se toca."""
    items, warns = parse_csv(text, get_trm_default(db))
    imported = updated = 0
    for it in items:
        row = db.query(InfraCost).filter(InfraCost.source_key == it["source_key"]).first()
        if row is None:
            db.add(InfraCost(source="archivo", **it))
            imported += 1
        else:
            for k, v in it.items():
                if k != "source_key":
                    setattr(row, k, v)
            row.updated_at = utcnow()
            updated += 1
    db.commit()
    return {"imported": imported, "updated": updated, "skipped": len([w for w in warns if w.startswith("Fila")]), "warnings": warns[:20]}
