"""Oportunidades del CRM y su tablero Kanban (C2). Sin commit propio: quien llama (el router) confirma o revierte.

* Una oportunidad = un posible evento de una cuenta. Su `code` sale del contador `event` AL CREARLA (docs/crm/ETAPA_C1C_C4_DISENO.md §4); si se gana, el evento usará ese mismo número (pieza C4).
* Mover de etapa es UNA actualización corta (`move_stage`); ganar o perder la cierra. Al ganarla `on_won` crea el cliente y el evento (C4, app/crm/won.py).
* El tablero cuesta DOS consultas por carga, sin importar cuántas oportunidades haya: una de totales por etapa y moneda (suma y suma ponderada, agrupadas por moneda: COP y USD nunca se suman) y una de
  tarjetas con `row_number()` por etapa (50 por columna; «ver más» pide otra página de UNA columna). Nombres de cuenta y responsable salen en la misma consulta con JOIN: no hay N+1.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.crm import history, normalize, pipeline as pipe
from app.crm.accounts import MAX_ID, MAX_PAGE, NORM_MAX, PAGE_SIZE, _check_owner, _check_version, _like
from app.crm.codes import next_code
from app.crm.errors import CrmError
from app.crm.sqlfold import fold
from app.crm.pipeline_rules import BOARD_PAGE, board_paging, clean_opportunity, effective_probability, move_effects
from app.models import CrmAccount, CrmContact, CrmOpportunity, CrmStage, Event, StaffUser
from app.timeutil import utcnow

CLOSED_DAYS = 90          # en el tablero, ganadas y perdidas se muestran si cerraron en los últimos N días (la lista las trae todas)
TEXT_MAX = 200


def get_opportunity(db: Session, opportunity_id: int) -> CrmOpportunity:
    if not 0 < opportunity_id <= MAX_ID:
        raise CrmError("Oportunidad no encontrada.", 404)
    o = db.get(CrmOpportunity, opportunity_id)
    if o is None:
        raise CrmError("Oportunidad no encontrada.", 404)
    return o


def on_won(db: Session, opportunity: CrmOpportunity, staff: StaffUser) -> None:
    """Al pasar a una etapa ganada: crea el cliente (si falta) y el evento con el mismo número (app/crm/won.py). Todo en la misma transacción del movimiento."""
    from app.crm import won
    if opportunity.event_id is None:
        won.create_event_for(db, staff, opportunity)
    else:
        from app.crm import platform_link
        platform_link.rewin(db, staff, opportunity)          # su evento quedó archivado al salir de «ganada»: se restaura


def _check_contact(db: Session, account_id: int, contact_id: Optional[int]) -> None:
    if contact_id is None:
        return
    c = db.get(CrmContact, contact_id)
    if c is None or c.account_id != account_id or c.archived_at is not None:
        raise CrmError("El contacto indicado no pertenece a esa cuenta o está archivado.")


# ------------------------------------------------------------------ alta y edición
def create_opportunity(db: Session, staff: StaffUser, data: dict) -> CrmOpportunity:
    fields = clean_opportunity(data, creating=True)
    account_id = fields.pop("account_id", None)
    account = db.get(CrmAccount, account_id) if account_id else None
    if account is None:
        raise CrmError("Elige la cuenta de la oportunidad.")
    if account.archived_at is not None:
        raise CrmError("La cuenta está archivada: restáurala antes de crearle oportunidades.")
    pipeline_id = fields.pop("pipeline_id", None) or pipe.default_pipeline_id(db)
    stage_id = fields.pop("stage_id", None) or pipe.first_open_stage(db, pipeline_id)
    stage = pipe.stage_info(db, stage_id)
    if stage is None or stage["pipeline_id"] != pipeline_id or stage["archived"] or stage["pipeline_archived"]:
        raise CrmError("La etapa no pertenece al embudo elegido o está archivada.")
    if stage["kind"] != "open":
        raise CrmError("Una oportunidad nueva empieza en una etapa abierta.")
    _check_owner(db, fields.get("owner_staff_id"))
    _check_contact(db, account.id, fields.get("primary_contact_id"))
    if fields.get("owner_staff_id") is None:                      # el formulario manda null cuando se deja «Yo»: se guarda quien crea
        fields["owner_staff_id"] = staff.id
    o = CrmOpportunity(code=next_code(db, "event"), account_id=account.id, pipeline_id=pipeline_id, stage_id=stage_id, created_by_id=staff.id, stage_entered_at=utcnow(), **fields)
    db.add(o)
    db.flush()
    return o


def update_opportunity(db: Session, staff: StaffUser, o: CrmOpportunity, data: dict, expected_updated_at: Optional[str]) -> CrmOpportunity:
    """Edita datos. La etapa se cambia con `move_stage`; la cuenta y el embudo no cambian."""
    _check_version(o, expected_updated_at)
    fields = clean_opportunity(data, creating=False)
    for key in ("account_id", "pipeline_id", "stage_id"):
        fields.pop(key, None)
    _check_owner(db, fields.get("owner_staff_id"))
    if "primary_contact_id" in fields:
        _check_contact(db, o.account_id, fields["primary_contact_id"])
    before = history.snapshot(o, "opportunity")
    for key, value in fields.items():
        setattr(o, key, value)
    if history.record(db, o, "opportunity", before, staff_id=staff.id):
        o.updated_at = utcnow()
    db.flush()
    return o


def set_archived(db: Session, staff: StaffUser, o: CrmOpportunity, archived: bool) -> CrmOpportunity:
    if archived == (o.archived_at is not None):
        raise CrmError("La oportunidad ya está archivada." if archived else "La oportunidad no está archivada.")
    before = history.snapshot(o, "opportunity")
    o.archived_at = utcnow() if archived else None
    history.record(db, o, "opportunity", before, staff_id=staff.id)
    o.updated_at = utcnow()
    db.flush()
    return o


def move_stage(db: Session, staff: StaffUser, o: CrmOpportunity, stage_id: int, *, lost_reason: Optional[str] = None, expected_updated_at: Optional[str] = None) -> CrmOpportunity:
    """Pone la oportunidad en otra etapa de su mismo embudo con una sola actualización. Ganada/perdida la cierra; una etapa abierta la reabre (salvo que ya tenga evento)."""
    if expected_updated_at is not None:
        _check_version(o, expected_updated_at)
    if o.archived_at is not None:
        raise CrmError("La oportunidad está archivada: restáurala para moverla.")
    stage = pipe.stage_info(db, stage_id) if 0 < stage_id <= MAX_ID else None
    if stage is None or stage["archived"] or stage["pipeline_id"] != o.pipeline_id:
        raise CrmError("Esa etapa no existe en el embudo de la oportunidad.")
    if stage_id == o.stage_id:
        raise CrmError("La oportunidad ya está en esa etapa.", 409)
    if o.event_id is not None and stage["kind"] != "won":
        from app.crm import platform_link
        platform_link.leave_won(db, staff, o)          # el evento «creado» y sin uso se archiva; en proceso o finalizado, se niega (409)
    now = utcnow()
    effects = move_effects(stage["kind"], o.outcome, lost_reason, now)
    before = history.snapshot(o, "opportunity")
    o.stage_id = stage_id
    for key, value in effects.items():
        setattr(o, key, value)
    history.record(db, o, "opportunity", before, staff_id=staff.id)
    o.updated_at = now
    db.flush()
    if stage["kind"] == "won":
        on_won(db, o, staff)
    return o


# ------------------------------------------------------------------ lectura
def _owner_name(db: Session, owner_id: Optional[int]) -> Optional[str]:
    if owner_id is None:
        return None
    row = db.query(StaffUser.full_name).filter(StaffUser.id == owner_id).first()
    return row[0] if row else None


def card(o: CrmOpportunity, account_name: Optional[str], owner_name: Optional[str], stage_probability: int, stage_kind: str) -> dict:
    return {"id": o.id, "code": o.code, "name": o.name, "account_id": o.account_id, "account_name": account_name, "amount": str(o.amount), "currency": o.currency,
            "probability": effective_probability(o.probability, stage_probability), "expected_close": o.expected_close.isoformat() if o.expected_close else None,
            "owner_staff_id": o.owner_staff_id, "owner_name": owner_name, "outcome": o.outcome, "stage_id": o.stage_id,
            "next_activity_at": o.next_activity_at.isoformat() if o.next_activity_at else None, "no_next_activity": o.outcome == "open" and o.next_activity_at is None,
            "stage_entered_at": o.stage_entered_at.isoformat(), "archived": o.archived_at is not None, "updated_at": o.updated_at.isoformat()}


def detail(db: Session, o: CrmOpportunity) -> dict:
    """La ficha: los datos de la oportunidad con nombre de cuenta, responsable y contacto principal (3 lecturas por clave primaria como mucho)."""
    account = db.get(CrmAccount, o.account_id)
    stage = pipe.stage_info(db, o.stage_id) or {"name": "?", "kind": "open", "probability": 0, "pipeline_id": o.pipeline_id}
    contact = db.get(CrmContact, o.primary_contact_id) if o.primary_contact_id else None
    out = card(o, account.name if account else None, _owner_name(db, o.owner_staff_id), stage["probability"], stage["kind"])
    out.update({"pipeline_id": o.pipeline_id, "stage_name": stage["name"], "stage_kind": stage["kind"], "opp_type": o.opp_type, "source": o.source, "next_step": o.next_step,
                "description": o.description, "primary_contact_id": o.primary_contact_id,
                "primary_contact": " ".join(p for p in ((contact.first_name or "").strip(), (contact.last_name or "").strip()) if p) if contact else None,
                "event_start": o.event_start.isoformat() if o.event_start else None, "city": o.city, "closed_at": o.closed_at.isoformat() if o.closed_at else None,
                "lost_reason": o.lost_reason, "event_id": o.event_id, "own_probability": o.probability, "created_at": o.created_at.isoformat(),
                "account_is_client": bool(account and account.tenant_id)})
    ev = db.get(Event, o.event_id) if o.event_id else None          # el evento enlazado: su código real, su estado y si quedó archivado (decide si la oportunidad puede salir de «ganada»)
    out.update({"event_code": ev.event_code if ev else None, "event_status": ev.status if ev else None, "event_archived": bool(ev and ev.archived_at is not None)})
    return out


def _filtered(query, f: dict):
    """Aplica los filtros comunes (tablero y lista). `query` ya trae el JOIN con CrmAccount."""
    if f.get("archived"):
        query = query.filter(CrmOpportunity.archived_at.isnot(None))
    else:
        query = query.filter(CrmOpportunity.archived_at.is_(None))
    if f.get("owner_id"):
        query = query.filter(CrmOpportunity.owner_staff_id == f["owner_id"])
    if f.get("account_id"):
        query = query.filter(CrmOpportunity.account_id == f["account_id"])
    if f.get("currency"):
        query = query.filter(CrmOpportunity.currency == f["currency"])
    if f.get("close_from"):
        query = query.filter(CrmOpportunity.expected_close >= f["close_from"])
    if f.get("close_to"):
        query = query.filter(CrmOpportunity.expected_close <= f["close_to"])
    if f.get("no_activity"):
        query = query.filter(CrmOpportunity.outcome == "open", CrmOpportunity.next_activity_at.is_(None))
    q = (f.get("q") or "").strip()[:TEXT_MAX]
    if q:
        parts = [fold(CrmOpportunity.name).like(_like(normalize(q)), escape="\\")]
        norm = normalize(q)[:NORM_MAX["name_norm"]]
        if norm:
            parts.append(CrmAccount.name_norm.like(_like(norm), escape="\\"))
        if q.isdigit() and len(q) <= 12:
            parts.append(CrmOpportunity.code == int(q))
        query = query.filter(or_(*parts))
    return query


def parse_filters(*, owner_id=None, account_id=None, currency="", close_from=None, close_to=None, no_activity=False, archived=False, q="") -> dict:
    from app.crm.pipeline_rules import clean_currency, clean_date, clean_id
    return {"owner_id": clean_id(owner_id, "responsable"), "account_id": clean_id(account_id, "cuenta"), "currency": clean_currency(currency) if currency else "",
            "close_from": clean_date(close_from, "cierre desde"), "close_to": clean_date(close_to, "cierre hasta"), "no_activity": bool(no_activity), "archived": bool(archived), "q": q or ""}


def board(db: Session, pipeline_id: Optional[int], filters: dict, *, stage_id: Optional[int] = None, offset=0, size=BOARD_PAGE, closed_days: int = CLOSED_DAYS) -> dict:
    """Tablero de un embudo. Sin `stage_id`: todas las columnas (primeros `size` de cada una). Con `stage_id` y `offset`: solo esa columna (el «ver más»)."""
    pipeline_id = pipeline_id or pipe.default_pipeline_id(db)
    cat = next((p for p in pipe.live_catalog(db) if p["id"] == pipeline_id), None)
    if cat is None:
        raise CrmError("Embudo no encontrado.", 404)
    stages = [s for s in cat["stages"] if stage_id is None or s["id"] == stage_id]
    if stage_id is not None and not stages:
        raise CrmError("Etapa no encontrada en ese embudo.", 404)
    off, size = board_paging(offset, size)
    since = utcnow() - timedelta(days=max(1, int(closed_days)))
    visible = or_(CrmOpportunity.outcome == "open", CrmOpportunity.closed_at >= since)

    eff = func.coalesce(CrmOpportunity.probability, CrmStage.probability)
    base = db.query(CrmOpportunity).join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id).join(CrmStage, CrmStage.id == CrmOpportunity.stage_id)
    base = _filtered(base.filter(CrmOpportunity.pipeline_id == pipeline_id, visible), filters)
    if stage_id is not None:
        base = base.filter(CrmOpportunity.stage_id == stage_id)

    # 1) totales: UNA consulta agregada por etapa y moneda
    totals_q = base.with_entities(CrmOpportunity.stage_id, CrmOpportunity.currency, func.count(CrmOpportunity.id), func.coalesce(func.sum(CrmOpportunity.amount), 0),
                                  func.coalesce(func.sum(CrmOpportunity.amount * eff / 100), 0)).group_by(CrmOpportunity.stage_id, CrmOpportunity.currency)
    totals: dict = {}
    for sid, cur, n, amount, wtd in totals_q.all():
        totals.setdefault(sid, {"count": 0, "by_currency": []})
        totals[sid]["count"] += int(n)
        totals[sid]["by_currency"].append({"currency": cur, "amount": str(Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "weighted": str(Decimal(wtd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))})

    # 2) tarjetas: UNA consulta con row_number() por etapa (ver _cards)
    result_rows = _cards(db, base, off, size)
    by_stage: dict = {}
    for o, account_name, owner_name, stage_probability, stage_kind in result_rows:
        by_stage.setdefault(o.stage_id, []).append(card(o, account_name, owner_name, stage_probability, stage_kind))

    columns = []
    for s in stages:
        t = totals.get(s["id"], {"count": 0, "by_currency": []})
        cards = by_stage.get(s["id"], [])
        columns.append({**s, "count": t["count"], "totals": t["by_currency"], "cards": cards, "offset": off, "has_more": t["count"] > off + len(cards)})
    return {"pipeline": {"id": cat["id"], "name": cat["name"]}, "columns": columns, "closed_days": closed_days, "page_size": size}


def _cards(db: Session, base, off: int, size: int):
    """Tarjetas de la ventana pedida: la subconsulta numera cada etapa con row_number() y se queda con las filas off < rn <= off + size. Una sola consulta."""
    rn = func.row_number().over(partition_by=CrmOpportunity.stage_id, order_by=(CrmOpportunity.stage_entered_at.desc(), CrmOpportunity.id.desc())).label("rn")
    ids = base.with_entities(CrmOpportunity.id.label("oid"), rn).subquery()
    return (db.query(CrmOpportunity, CrmAccount.name, StaffUser.full_name, CrmStage.probability, CrmStage.kind)
            .join(ids, ids.c.oid == CrmOpportunity.id)
            .join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id)
            .join(CrmStage, CrmStage.id == CrmOpportunity.stage_id)
            .join(StaffUser, StaffUser.id == CrmOpportunity.owner_staff_id, isouter=True)
            .filter(ids.c.rn > off, ids.c.rn <= off + size)
            .order_by(CrmOpportunity.stage_id, ids.c.rn).all())


def list_opportunities(db: Session, filters: dict, *, pipeline_id: Optional[int] = None, stage_id: Optional[int] = None, outcome: str = "", page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmOpportunity).join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id)
    query = _filtered(query, filters)
    if pipeline_id:
        query = query.filter(CrmOpportunity.pipeline_id == pipeline_id)
    if stage_id:
        query = query.filter(CrmOpportunity.stage_id == stage_id)
    if outcome in ("open", "won", "lost"):
        query = query.filter(CrmOpportunity.outcome == outcome)
    total = query.count()
    size = max(1, min(int(size or PAGE_SIZE), 200))
    page = max(1, min(int(page or 1), MAX_PAGE))
    rows = (query.with_entities(CrmOpportunity, CrmAccount.name, StaffUser.full_name, CrmStage.probability, CrmStage.kind)
            .join(CrmStage, CrmStage.id == CrmOpportunity.stage_id).join(StaffUser, StaffUser.id == CrmOpportunity.owner_staff_id, isouter=True)
            .order_by(CrmOpportunity.updated_at.desc(), CrmOpportunity.id.desc()).offset((page - 1) * size).limit(size).all())
    items = [{**card(o, account_name, owner_name, sp, sk), "stage_name": (pipe.stage_info(db, o.stage_id) or {}).get("name")} for o, account_name, owner_name, sp, sk in rows]
    return {"items": items, "total": total, "page": page, "size": size}


def pipeline_summary_case():
    """Expresión reutilizable (C4 la usa en los tableros): monto abierto ponderado de la oportunidad."""
    return case((CrmOpportunity.outcome == "open", CrmOpportunity.amount * func.coalesce(CrmOpportunity.probability, CrmStage.probability) / 100), else_=0)

