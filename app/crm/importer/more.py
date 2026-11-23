"""Importador de SuiteCRM, parte 2 (C1c-2): productos, oportunidades, actividades, cotizaciones (con sus líneas) y proformas.
Mismas garantías que la parte 1: modos sample/dry_run/apply, un SAVEPOINT por fila, rechazos con número de fila y motivo SIN valores de datos, idempotente por `legacy_sugar_id`.
Lo importado NO dispara efectos: una oportunidad ganada que llega de SuiteCRM no crea evento ni cliente (se ve «Crear el evento» en su ficha); no se escribe historial de cambios; los totales de las cotizaciones se calculan aquí con las mismas reglas del servidor.
En `dry_run` y `sample` nada se guarda, pero las referencias entre archivos se validan contra lo que traen los propios archivos (`Ctx`): así la prueba en seco se parece a la carga real."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.crm import activities as act_svc, normalize, pipeline as pipe, quote_rules as qr
from app.crm.codes import bump_floor, next_code
from app.crm.errors import CrmError
from app.crm.importer import formats, parsing
from app.crm.pipeline_rules import CURRENCIES, clean_activity, clean_opportunity
from app.models import CrmAccount, CrmActivity, CrmOpportunity, CrmProduct, CrmProforma, CrmQuote, CrmQuoteLine
from app.timeutil import utcnow

SAMPLE_ROWS = 20
COMMIT_EVERY = 200
MAX_REJECTED = 500


# ------------------------------------------------------------------ lectura de valores
def _reject(rejected: list, lineno: int, reason: str) -> None:
    if len(rejected) < MAX_REJECTED:
        rejected.append({"row": lineno, "reason": reason})


def _generic(e: Exception) -> str:
    return f"No se pudo guardar la fila (dato repetido o fuera de rango) [{parsing.describe_error(e)}]."


# ------------------------------------------------------------------ referencias entre archivos
class Ctx:
    """Lo que ya existe (base) o lo que traen los archivos de esta corrida (virtual). Presencia en el diccionario = conocido; el valor es el id real si ya está guardado, None si es virtual."""

    def __init__(self, db: Session, save: bool):
        self.db, self.save = db, save
        self.acc: dict = {}                 # name_norm → id | None
        self.opp_legacy: dict = {}          # legacy → (id|None, account_norm)
        self.opp_name: dict = {}            # name_norm → id|None
        self.quote_legacy: dict = {}        # legacy → id|None
        self.quote_number: dict = {}        # número → id|None
        self.product_sku: dict = {}         # sku → id|None
        self.product_legacy: dict = {}
        self.touched_opps: set = set()
        self.max_code = {"event": 0, "quote": 0, "proforma": 0}
        self.load()

    def load(self) -> None:
        db = self.db
        for i, n in db.query(CrmAccount.id, CrmAccount.name_norm).order_by(CrmAccount.id.desc()).all():
            self.acc[n] = i
        for i, lg, nm in db.query(CrmOpportunity.id, CrmOpportunity.legacy_sugar_id, CrmOpportunity.name).all():
            if lg:
                self.opp_legacy[lg] = (i, None)
            self.opp_name.setdefault(normalize(nm)[:200], i)
        for i, lg, num in db.query(CrmQuote.id, CrmQuote.legacy_sugar_id, CrmQuote.number).filter(CrmQuote.version == 1).all():
            if lg:
                self.quote_legacy[lg] = i
            self.quote_number[int(num)] = i
        for i, lg, sku in db.query(CrmProduct.id, CrmProduct.legacy_sugar_id, CrmProduct.sku).all():
            if lg:
                self.product_legacy[lg] = i
            if sku:
                self.product_sku[sku.lower()] = i

    def add_accounts(self, names) -> None:
        for _legacy, name, _code in names:
            self.acc.setdefault(normalize(name)[:200], None)


# ------------------------------------------------------------------ productos
def import_products(ctx: Ctx, staff_id: int, raw: bytes, mode: str) -> dict:
    db, save = ctx.db, mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "currency_defaulted": 0}
    rejected, seen_sku = [], set()
    for lineno, row in formats.read_rows("products", raw, SAMPLE_ROWS if mode == "sample" else None):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and (legacy in ctx.product_legacy):
                counts["skipped_existing"] += 1
                continue
            cur, defaulted = parsing.map_currency(row.get("currency"), CURRENCIES)
            counts["currency_defaulted"] += 1 if defaulted else 0
            data = {"name": row.get("name"), "sku": row.get("sku") or None, "description": row.get("description") or None, "category": row.get("category") or None,
                    "price": str(parsing.parse_money(row.get("price"), "Precio")), "cost": str(parsing.parse_money(row.get("cost"), "Costo")), "currency": cur}
            fields = qr.clean_product(data, creating=True)
            sku = (fields.get("sku") or "").lower()
            if sku and (sku in ctx.product_sku or sku in seen_sku):
                raise CrmError("Código (SKU) repetido.")
            if save:
                with db.begin_nested():
                    p = CrmProduct(name_norm=normalize(fields["name"])[:200], legacy_sugar_id=legacy, **fields)
                    db.add(p)
                    db.flush()
                    ctx.product_legacy[legacy or f"p{p.id}"] = p.id
                    if sku:
                        ctx.product_sku[sku] = p.id
            else:
                if legacy:
                    ctx.product_legacy[legacy] = None
                if sku:
                    ctx.product_sku[sku] = None
            if sku:
                seen_sku.add(sku)
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, _generic(e))
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    return {"counts": counts, "rejected": rejected}


# ------------------------------------------------------------------ oportunidades
def import_opportunities(ctx: Ctx, staff_id: int, raw: bytes, mode: str) -> dict:
    db, save = ctx.db, mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "without_account": 0, "stage_unmapped": 0, "currency_defaulted": 0, "won": 0, "lost": 0}
    rejected, seen_codes, max_code = [], set(), 0
    pid = pipe.default_pipeline_id(db)
    stages = next(p["stages"] for p in pipe.live_catalog(db) if p["id"] == pid)
    for lineno, row in formats.read_rows("opportunities", raw, SAMPLE_ROWS if mode == "sample" else None):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and legacy in ctx.opp_legacy:
                counts["skipped_existing"] += 1
                continue
            account_norm = normalize(row.get("account_name"))[:200]
            if not account_norm or account_norm not in ctx.acc:
                counts["without_account"] += 1
                raise CrmError("La oportunidad no tiene una cuenta conocida.")
            cur, defaulted = parsing.map_currency(row.get("currency"), CURRENCIES)
            counts["currency_defaulted"] += 1 if defaulted else 0
            data = {"name": row.get("name"), "amount": str(parsing.parse_money(row.get("amount"))), "currency": cur, "opp_type": row.get("opp_type") or None, "source": row.get("source") or None,
                    "next_step": row.get("next_step") or None, "description": row.get("description") or None, "city": row.get("city") or None}
            expected, event_start = parsing.parse_date(row.get("expected_close")), parsing.parse_date(row.get("event_start"))
            data["expected_close"], data["event_start"] = expected, event_start
            fields = clean_opportunity(data, creating=True)
            stage_id, kind, known = parsing.stage_for(stages, row.get("stage"))
            counts["stage_unmapped"] += 0 if known else 1
            code = int(row["code"]) if (row.get("code") or "").isdigit() else None
            if code is not None and (code in seen_codes or code > 9_000_000_000):
                raise CrmError("Código de proyecto repetido en el archivo o fuera de rango.")
            closed_at = None
            if kind != "open":
                real = parsing.parse_datetime(row.get("closed_at"))
                closed_at = real or (datetime(expected.year, expected.month, expected.day) if expected else utcnow())
                counts["won" if kind == "won" else "lost"] += 1
            lost_reason = ((row.get("lost_reason") or "").strip()[:200] or None) if kind == "lost" else None
            if save:
                with db.begin_nested():
                    o = CrmOpportunity(code=code if code is not None else next_code(db, "event"), account_id=ctx.acc[account_norm], pipeline_id=pid, stage_id=stage_id, outcome=kind,
                                       closed_at=closed_at, lost_reason=lost_reason, stage_entered_at=closed_at or utcnow(), owner_staff_id=staff_id, created_by_id=staff_id,
                                       legacy_sugar_id=legacy, legacy_json=(row.get("legacy_json") or None), **fields)
                    db.add(o)
                    db.flush()
                    if legacy:
                        ctx.opp_legacy[legacy] = (o.id, account_norm)
                    ctx.opp_name.setdefault(normalize(fields["name"])[:200], o.id)
            else:
                if legacy:
                    ctx.opp_legacy[legacy] = (None, account_norm)
                ctx.opp_name.setdefault(normalize(fields["name"])[:200], None)
            if code is not None:
                seen_codes.add(code)
                max_code = max(max_code, code)
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, _generic(e))
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    if save and max_code:
        bump_floor(db, "event", max_code)
    return {"counts": counts, "rejected": rejected}


# ------------------------------------------------------------------ actividades
def import_activities(ctx: Ctx, staff_id: int, raw: bytes, mode: str) -> dict:
    db, save = ctx.db, mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "unlinked": 0}
    rejected = []
    for lineno, row in formats.read_rows("activities", raw, SAMPLE_ROWS if mode == "sample" else None):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and db.query(CrmActivity.id).filter(CrmActivity.legacy_sugar_id == legacy).first():
                counts["skipped_existing"] += 1
                continue
            kind = parsing.KIND_ALIASES.get(normalize(row.get("kind")), "task")
            status = parsing.STATUS_ALIASES.get(normalize(row.get("status")), "planned")
            if kind == "note":
                status = "done"
            due = parsing.parse_datetime(row.get("due"))
            opp_id, account_id, linked = None, None, False
            lg = (row.get("opportunity_legacy_id") or "").strip()
            on = normalize(row.get("opportunity_name"))[:200]
            if lg and lg in ctx.opp_legacy:
                opp_id, linked = ctx.opp_legacy[lg][0], True
            elif on and on in ctx.opp_name:
                opp_id, linked = ctx.opp_name[on], True
            an = normalize(row.get("account_name"))[:200]
            if an and an in ctx.acc:
                account_id, linked = ctx.acc[an], True
            if not linked:
                counts["unlinked"] += 1
                raise CrmError("La actividad no se pudo ligar a una oportunidad ni a una cuenta conocidas.")
            data = {"kind": kind, "subject": row.get("subject") or None, "description": row.get("description") or None, "due_at": due}
            fields = clean_activity(data, creating=True)
            if save:
                with db.begin_nested():
                    if opp_id:
                        opp = db.get(CrmOpportunity, opp_id)
                        account_id = opp.account_id                                # la oportunidad manda sobre el nombre de cuenta
                    a = CrmActivity(status=status, done_at=(due or utcnow()) if status == "done" else None, account_id=account_id, opportunity_id=opp_id, owner_staff_id=staff_id,
                                    created_by_id=staff_id, legacy_sugar_id=legacy, legacy_json=(row.get("legacy_json") or None), **fields)
                    db.add(a)
                    db.flush()
                    if opp_id and status == "planned":
                        ctx.touched_opps.add(opp_id)
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, _generic(e))
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    if save:
        for oid in ctx.touched_opps:                               # la copia `next_activity_at` se recalcula UNA vez por oportunidad, no por fila
            act_svc.refresh_next(db, oid)
        ctx.touched_opps.clear()
    return {"counts": counts, "rejected": rejected}


# ------------------------------------------------------------------ cotizaciones y sus líneas
def import_quotes(ctx: Ctx, staff_id: int, raw: bytes, mode: str, lines_by_quote: dict) -> dict:
    """`lines_by_quote`: {clave de la cotización (id de SuiteCRM o «n:<número>»): [filas de línea]} ya leídas del archivo de líneas. Sin líneas pero con total: una sola línea «Total importado» sin impuesto."""
    db, save = ctx.db, mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "without_account": 0, "total_only": 0, "stage_unmapped": 0, "currency_defaulted": 0, "lines": 0}
    rejected, seen_numbers, max_num = [], set(), 0
    for lineno, row in formats.read_rows("quotes", raw, SAMPLE_ROWS if mode == "sample" else None):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and legacy in ctx.quote_legacy:
                counts["skipped_existing"] += 1
                continue
            an = normalize(row.get("account_name"))[:200]
            if not an or an not in ctx.acc:
                counts["without_account"] += 1
                raise CrmError("La cotización no tiene una cuenta conocida.")
            number = int(row["number"]) if (row.get("number") or "").isdigit() else None
            if number is not None and (number in seen_numbers or number in ctx.quote_number or number > 9_000_000_000):
                raise CrmError("Número de cotización repetido o fuera de rango.")
            stage = parsing.QUOTE_STAGE_ALIASES.get(normalize(row.get("stage")))
            if stage is None:
                counts["stage_unmapped"] += 1
                stage = "borrador"
            cur, defaulted = parsing.map_currency(row.get("currency"), CURRENCIES)
            counts["currency_defaulted"] += 1 if defaulted else 0
            data = {"title": row.get("title") or row.get("number") or "Cotización importada", "currency": cur, "valid_until": parsing.parse_date(row.get("valid_until")), "terms_text": row.get("terms") or None}
            fields = qr.clean_quote(data, creating=True)
            raw_lines = lines_by_quote.get(legacy or "", []) or (lines_by_quote.get(f"n:{number}", []) if number is not None else [])
            lines = [parsing.line_data(r) for r in raw_lines]
            if not lines and parsing.parse_money(row.get("total")) > 0:
                lines = [{"name": "Total importado de SuiteCRM", "qty": "1", "unit_price": str(parsing.parse_money(row.get("total"), "Total")), "discount_percent": "0", "tax_percent": "0"}]
                counts["total_only"] += 1
            cleaned = qr.clean_lines(lines)
            opp_id = None
            og, on = (row.get("opportunity_legacy_id") or "").strip(), normalize(row.get("opportunity_name"))[:200]
            if og in ctx.opp_legacy:
                opp_id = ctx.opp_legacy[og][0]
            elif on in ctx.opp_name:
                opp_id = ctx.opp_name[on]
            if save:
                with db.begin_nested():
                    acc_id = ctx.acc[an]
                    if opp_id is not None and db.get(CrmOpportunity, opp_id).account_id != acc_id:
                        opp_id = None                                  # la oportunidad es de otra cuenta: no se liga
                    q = CrmQuote(number=number if number is not None else next_code(db, "quote"), version=1, account_id=acc_id, opportunity_id=opp_id, stage=stage,
                                 approval_status=stage if stage in ("aprobada", "rechazada") else "pendiente", owner_staff_id=staff_id, created_by_id=staff_id, legacy_sugar_id=legacy,
                                 legacy_json=(row.get("legacy_json") or None), sent_at=utcnow() if stage != "borrador" else None, **fields)
                    db.add(q)
                    db.flush()
                    for c in cleaned:
                        a = qr.line_amounts(c["qty"], c["unit_price"], c["discount_percent"], c["tax_percent"])
                        db.add(CrmQuoteLine(quote_id=q.id, line_total=a["net"], **c))
                    t = qr.totals(cleaned)
                    q.subtotal, q.discount_total, q.tax_total, q.total = t["subtotal"], t["discount_total"], t["tax_total"], t["total"]
                    db.flush()
                    if legacy:
                        ctx.quote_legacy[legacy] = q.id
                    ctx.quote_number[int(q.number)] = q.id
            else:
                if legacy:
                    ctx.quote_legacy[legacy] = None
                if number is not None:
                    ctx.quote_number[number] = None
            if number is not None:
                seen_numbers.add(number)
                max_num = max(max_num, number)
            counts["lines"] += len(cleaned)
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, _generic(e))
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    if save and max_num:
        bump_floor(db, "quote", max_num)
    return {"counts": counts, "rejected": rejected}


def group_lines(raw: Optional[bytes]) -> dict:
    """Agrupa las filas del archivo de líneas por cotización (id de SuiteCRM o número). Un archivo malo es un error para toda la corrida, no para una fila."""
    out: dict = {}
    if not raw:
        return out
    for _lineno, row in formats.read_rows("quote_lines", raw):
        key = (row.get("quote_legacy_id") or "").strip() or (f"n:{int(row['quote_number'])}" if (row.get("quote_number") or "").isdigit() else "")
        if key:
            out.setdefault(key, []).append(row)
    return out


# ------------------------------------------------------------------ proformas
def import_proformas(ctx: Ctx, staff_id: int, raw: bytes, mode: str) -> dict:
    db, save = ctx.db, mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "without_account": 0, "without_quote": 0, "currency_defaulted": 0}
    rejected, seen, max_num = [], set(), 0
    for lineno, row in formats.read_rows("proformas", raw, SAMPLE_ROWS if mode == "sample" else None):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and db.query(CrmProforma.id).filter(CrmProforma.legacy_sugar_id == legacy).first():
                counts["skipped_existing"] += 1
                continue
            an = normalize(row.get("account_name"))[:200]
            if not an or an not in ctx.acc:
                counts["without_account"] += 1
                raise CrmError("La proforma no tiene una cuenta conocida.")
            number = int(row["number"]) if (row.get("number") or "").isdigit() else None
            if number is not None and (number in seen or number > 9_000_000_000):
                raise CrmError("Número de proforma repetido o fuera de rango.")
            cur, defaulted = parsing.map_currency(row.get("currency"), CURRENCIES)
            counts["currency_defaulted"] += 1 if defaulted else 0
            data = {"event_name": row.get("event_name") or None, "city": row.get("city") or None, "status": parsing.PROFORMA_STATUS_ALIASES.get(normalize(row.get("status")), "no_pagado")}
            fields = qr.clean_proforma(data)
            issued = parsing.parse_date(row.get("issued_at")) or utcnow().date()
            due = parsing.parse_date(row.get("due_at"))
            total = parsing.parse_money(row.get("total"), "Total")
            qid = None
            qg = (row.get("quote_legacy_id") or "").strip()
            if qg in ctx.quote_legacy:
                qid = ctx.quote_legacy[qg]
            elif (row.get("quote_number") or "").isdigit() and int(row["quote_number"]) in ctx.quote_number:
                qid = ctx.quote_number[int(row["quote_number"])]
            else:
                counts["without_quote"] += 1                                 # se importa igual, sin cotización ligada
            if save:
                with db.begin_nested():
                    p = CrmProforma(number=number if number is not None else next_code(db, "proforma"), quote_id=qid, account_id=ctx.acc[an], issued_at=issued, due_at=due, currency=cur,
                                    total=total, created_by_id=staff_id, legacy_sugar_id=legacy, **fields)
                    db.add(p)
                    db.flush()
            if number is not None:
                seen.add(number)
                max_num = max(max_num, number)
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, _generic(e))
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    if save and max_num:
        bump_floor(db, "proforma", max_num)
    return {"counts": counts, "rejected": rejected}
