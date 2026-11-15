"""«Mi día» y tableros del CRM (C4). Solo lectura. Cada pantalla se llena con POCAS consultas agrupadas al abrirla; nada corre solo ni despierta la base (sin temporizadores).

* «Mi día»: 5 consultas con LIMIT (actividades vencidas/de hoy/recordatorios, oportunidades sin próxima actividad, oportunidades por cerrar, cotizaciones por vencer). Usa el índice `ix_crm_act_owner_due`.
* Tableros: embudo abierto por etapa, cerradas (ganadas/perdidas), actividades y cotizaciones; el admin ve todo el equipo y por responsable; el comercial solo lo suyo.
* Dinero: siempre separado por moneda (COP y USD nunca se suman). Sin datos personales: solo nombres de cuenta/oportunidad, conteos y montos.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crm import opportunities as opp_svc, pipeline as pipe
from app.crm.pipeline_rules import ACTIVITY_KINDS
from app.models import CrmAccount, CrmActivity, CrmOpportunity, CrmQuote, CrmStage, StaffUser
from app.timeutil import local_to_utc, to_local, utcnow

LIST_LIMIT = 50
DAY_OPTIONS = (30, 90, 365)
CLOSE_SOON_DAYS = 14
QUOTE_SOON_DAYS = 7
OPEN_QUOTE_STAGES = ("borrador", "enviada", "negociada")


def day_bounds(now=None):
    """(inicio del día local en UTC, fin del día local en UTC, fecha local de hoy)."""
    local = to_local(now or utcnow())
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    start = local_to_utc(start_local)
    return start, start + timedelta(days=1), local.date()


def _money(v) -> str:
    return str(Decimal(v or 0).quantize(Decimal("0.01")))


def _act(a: CrmActivity, account_name, opp_name) -> dict:
    return {"id": a.id, "kind": a.kind, "kind_label": ACTIVITY_KINDS.get(a.kind, a.kind), "subject": a.subject, "due_at": a.due_at.isoformat() if a.due_at else None,
            "remind_at": a.remind_at.isoformat() if a.remind_at else None, "account_id": a.account_id, "account_name": account_name, "opportunity_id": a.opportunity_id, "opportunity_name": opp_name,
            "lead_id": a.lead_id, "contact_id": a.contact_id, "updated_at": a.updated_at.isoformat()}


def my_day(db: Session, staff_id: int, now=None) -> dict:
    now = now or utcnow()
    start, end, today = day_bounds(now)
    rows = (db.query(CrmActivity, CrmAccount.name, CrmOpportunity.name).join(CrmAccount, CrmAccount.id == CrmActivity.account_id, isouter=True)
            .join(CrmOpportunity, CrmOpportunity.id == CrmActivity.opportunity_id, isouter=True)
            .filter(CrmActivity.owner_staff_id == staff_id, CrmActivity.status == "planned", CrmActivity.due_at.isnot(None), CrmActivity.due_at < end)
            .order_by(CrmActivity.due_at).limit(2 * LIST_LIMIT + 1).all())
    overdue = [_act(a, an, on) for a, an, on in rows if a.due_at < start][:LIST_LIMIT]
    due_today = [_act(a, an, on) for a, an, on in rows if a.due_at >= start][:LIST_LIMIT]
    remind = (db.query(CrmActivity, CrmAccount.name, CrmOpportunity.name).join(CrmAccount, CrmAccount.id == CrmActivity.account_id, isouter=True)
              .join(CrmOpportunity, CrmOpportunity.id == CrmActivity.opportunity_id, isouter=True)
              .filter(CrmActivity.owner_staff_id == staff_id, CrmActivity.status == "planned", CrmActivity.remind_at.isnot(None), CrmActivity.remind_at <= now, CrmActivity.due_at >= end)
              .order_by(CrmActivity.due_at).limit(LIST_LIMIT).all())
    base = (db.query(CrmOpportunity.id, CrmOpportunity.code, CrmOpportunity.name, CrmOpportunity.amount, CrmOpportunity.currency, CrmOpportunity.expected_close, CrmAccount.name)
            .join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id)
            .filter(CrmOpportunity.owner_staff_id == staff_id, CrmOpportunity.outcome == "open", CrmOpportunity.archived_at.is_(None)))

    def opp(r):
        return {"id": r[0], "code": r[1], "name": r[2], "amount": _money(r[3]), "currency": r[4], "expected_close": r[5].isoformat() if r[5] else None, "account_name": r[6]}
    no_next = [opp(r) for r in base.filter(CrmOpportunity.next_activity_at.is_(None)).order_by(CrmOpportunity.updated_at.desc()).limit(LIST_LIMIT + 1).all()]
    closing = [opp(r) for r in base.filter(CrmOpportunity.expected_close.isnot(None), CrmOpportunity.expected_close <= today + timedelta(days=CLOSE_SOON_DAYS))
               .order_by(CrmOpportunity.expected_close).limit(LIST_LIMIT).all()]
    quotes = [{"id": q.id, "number": q.number, "version": q.version, "title": q.title, "stage": q.stage, "valid_until": q.valid_until.isoformat(), "total": _money(q.total), "currency": q.currency, "account_name": an}
              for q, an in (db.query(CrmQuote, CrmAccount.name).join(CrmAccount, CrmAccount.id == CrmQuote.account_id)
                            .filter(CrmQuote.owner_staff_id == staff_id, CrmQuote.stage.in_(OPEN_QUOTE_STAGES), CrmQuote.archived_at.is_(None), CrmQuote.valid_until.isnot(None),
                                    CrmQuote.valid_until <= today + timedelta(days=QUOTE_SOON_DAYS)).order_by(CrmQuote.valid_until).limit(LIST_LIMIT).all())]
    return {"today": today.isoformat(), "overdue": overdue, "due_today": due_today, "reminders": [_act(a, an, on) for a, an, on in remind],
            "no_next_activity": no_next[:LIST_LIMIT], "no_next_activity_more": len(no_next) > LIST_LIMIT, "closing_soon": closing, "quotes_expiring": quotes,
            "close_soon_days": CLOSE_SOON_DAYS, "quote_soon_days": QUOTE_SOON_DAYS}


def dashboards(db: Session, *, owner_id: Optional[int], days: int, pipeline_id: Optional[int] = None) -> dict:
    """`owner_id` None = todo el equipo (solo admin). `days` decide la ventana de cerradas, actividades hechas y cotizaciones creadas."""
    days = days if days in DAY_OPTIONS else 90
    now = utcnow()
    since = now - timedelta(days=days)
    pid = pipeline_id or pipe.default_pipeline_id(db)
    weighted = opp_svc.pipeline_summary_case()
    q = (db.query(CrmStage.id, CrmStage.name, CrmStage.position, CrmOpportunity.currency, func.count(CrmOpportunity.id), func.coalesce(func.sum(CrmOpportunity.amount), 0), func.coalesce(func.sum(weighted), 0))
         .select_from(CrmOpportunity).join(CrmStage, CrmStage.id == CrmOpportunity.stage_id)
         .filter(CrmOpportunity.pipeline_id == pid, CrmOpportunity.outcome == "open", CrmOpportunity.archived_at.is_(None)))
    if owner_id:
        q = q.filter(CrmOpportunity.owner_staff_id == owner_id)
    stages: dict = {}
    for sid, name, pos, cur, n, amt, wt in q.group_by(CrmStage.id, CrmStage.name, CrmStage.position, CrmOpportunity.currency).order_by(CrmStage.position).all():
        s = stages.setdefault(sid, {"stage_id": sid, "name": name, "count": 0, "totals": []})
        s["count"] += n
        s["totals"].append({"currency": cur, "amount": _money(amt), "weighted": _money(wt)})
    c = (db.query(CrmOpportunity.outcome, CrmOpportunity.currency, func.count(CrmOpportunity.id), func.coalesce(func.sum(CrmOpportunity.amount), 0))
         .filter(CrmOpportunity.pipeline_id == pid, CrmOpportunity.outcome.in_(("won", "lost")), CrmOpportunity.closed_at >= since, CrmOpportunity.archived_at.is_(None)))
    if owner_id:
        c = c.filter(CrmOpportunity.owner_staff_id == owner_id)
    closed = {"won": {"count": 0, "totals": []}, "lost": {"count": 0, "totals": []}}
    for outcome, cur, n, amt in c.group_by(CrmOpportunity.outcome, CrmOpportunity.currency).all():
        closed[outcome]["count"] += n
        closed[outcome]["totals"].append({"currency": cur, "amount": _money(amt)})
    decided = closed["won"]["count"] + closed["lost"]["count"]
    win_rate = round(100 * closed["won"]["count"] / decided) if decided else None
    a = db.query(CrmActivity.kind, CrmActivity.status, func.count(CrmActivity.id)).filter(
        (CrmActivity.status == "planned") | ((CrmActivity.status == "done") & (CrmActivity.done_at >= since)))
    if owner_id:
        a = a.filter(CrmActivity.owner_staff_id == owner_id)
    overdue_n = 0
    done: dict = {}
    pending = 0
    for kind, status, n in a.group_by(CrmActivity.kind, CrmActivity.status).all():
        if status == "done":
            done[kind] = n
        else:
            pending += n
    if pending:
        o = db.query(func.count(CrmActivity.id)).filter(CrmActivity.status == "planned", CrmActivity.due_at < now)
        if owner_id:
            o = o.filter(CrmActivity.owner_staff_id == owner_id)
        overdue_n = o.scalar() or 0
    qq = db.query(CrmQuote.stage, CrmQuote.currency, func.count(CrmQuote.id), func.coalesce(func.sum(CrmQuote.total), 0)).filter(CrmQuote.archived_at.is_(None), CrmQuote.created_at >= since)
    if owner_id:
        qq = qq.filter(CrmQuote.owner_staff_id == owner_id)
    quotes: dict = {}
    for stage, cur, n, tot in qq.group_by(CrmQuote.stage, CrmQuote.currency).all():
        e = quotes.setdefault(stage, {"stage": stage, "count": 0, "totals": []})
        e["count"] += n
        e["totals"].append({"currency": cur, "amount": _money(tot)})
    out = {"days": days, "day_options": list(DAY_OPTIONS), "scope": "me" if owner_id else "all", "pipeline_id": pid, "stages": list(stages.values()), "closed": closed, "win_rate": win_rate,
           "activities": {"pending": pending, "overdue": overdue_n, "done_by_kind": [{"kind": k, "label": ACTIVITY_KINDS.get(k, k), "count": n} for k, n in sorted(done.items())]},
           "quotes": list(quotes.values()), "by_owner": []}
    if not owner_id:
        rows = (db.query(StaffUser.id, StaffUser.full_name, CrmOpportunity.currency, func.count(CrmOpportunity.id), func.coalesce(func.sum(CrmOpportunity.amount), 0), func.coalesce(func.sum(weighted), 0))
                .select_from(CrmOpportunity).join(StaffUser, StaffUser.id == CrmOpportunity.owner_staff_id, isouter=True).join(CrmStage, CrmStage.id == CrmOpportunity.stage_id)
                .filter(CrmOpportunity.pipeline_id == pid, CrmOpportunity.outcome == "open", CrmOpportunity.archived_at.is_(None))
                .group_by(StaffUser.id, StaffUser.full_name, CrmOpportunity.currency).order_by(StaffUser.full_name).limit(300).all())
        owners: dict = {}
        for sid, name, cur, n, amt, wt in rows:
            e = owners.setdefault(sid, {"owner_id": sid, "name": name or "Sin responsable", "count": 0, "totals": []})
            e["count"] += n
            e["totals"].append({"currency": cur, "amount": _money(amt), "weighted": _money(wt)})
        out["by_owner"] = list(owners.values())
    return out


CAL_LIMIT = 500


def calendar_range(db: Session, *, owner_id: Optional[int], start: date, end: date) -> dict:
    """Lo del CRM para el Calendario, entre `start` y `end` (fechas locales, inclusive; máximo ~6 semanas). `owner_id` None = todo el equipo (solo admin).
    Tres consultas con LIMIT: actividades (llamadas, tareas, reuniones; con hora), cierres esperados de oportunidades abiertas y cotizaciones abiertas que vencen.
    Cada elemento: {type, id, date, time, title, sub, href, status}. Solo nombres de cuenta/oportunidad: sin datos personales."""
    if end < start:
        start, end = end, start
    end = min(end, start + timedelta(days=45))
    lo, hi = local_to_utc(datetime.combine(start, time.min)), local_to_utc(datetime.combine(end + timedelta(days=1), time.min))
    items = []
    act_q = (db.query(CrmActivity, CrmAccount.name, CrmOpportunity.name).join(CrmAccount, CrmAccount.id == CrmActivity.account_id, isouter=True)
             .join(CrmOpportunity, CrmOpportunity.id == CrmActivity.opportunity_id, isouter=True)
             .filter(CrmActivity.status.in_(("planned", "done")), CrmActivity.due_at >= lo, CrmActivity.due_at < hi))
    if owner_id:
        act_q = act_q.filter(CrmActivity.owner_staff_id == owner_id)
    for a, an, on in act_q.order_by(CrmActivity.due_at).limit(CAL_LIMIT).all():
        local = to_local(a.due_at)
        href = f"/crm/oportunidades/{a.opportunity_id}" if a.opportunity_id else (f"/crm/cuentas/{a.account_id}" if a.account_id else "/crm/leads")
        items.append({"type": "activity", "id": a.id, "date": local.date().isoformat(), "time": local.strftime("%H:%M"), "title": f"{ACTIVITY_KINDS.get(a.kind, a.kind)}: {a.subject}",
                      "sub": on or an or "", "href": href, "status": a.status})
    opp_q = (db.query(CrmOpportunity.id, CrmOpportunity.name, CrmOpportunity.expected_close, CrmAccount.name).join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id)
             .filter(CrmOpportunity.outcome == "open", CrmOpportunity.archived_at.is_(None), CrmOpportunity.expected_close >= start, CrmOpportunity.expected_close <= end))
    if owner_id:
        opp_q = opp_q.filter(CrmOpportunity.owner_staff_id == owner_id)
    for oid, name, close, an in opp_q.order_by(CrmOpportunity.expected_close).limit(CAL_LIMIT).all():
        items.append({"type": "close", "id": oid, "date": close.isoformat(), "time": None, "title": "Cierre esperado: " + name, "sub": an, "href": f"/crm/oportunidades/{oid}", "status": "open"})
    quote_q = (db.query(CrmQuote.id, CrmQuote.number, CrmQuote.title, CrmQuote.valid_until, CrmAccount.name).join(CrmAccount, CrmAccount.id == CrmQuote.account_id)
               .filter(CrmQuote.stage.in_(OPEN_QUOTE_STAGES), CrmQuote.archived_at.is_(None), CrmQuote.valid_until >= start, CrmQuote.valid_until <= end))
    if owner_id:
        quote_q = quote_q.filter(CrmQuote.owner_staff_id == owner_id)
    for qid, number, title, valid, an in quote_q.order_by(CrmQuote.valid_until).limit(CAL_LIMIT).all():
        items.append({"type": "quote", "id": qid, "date": valid.isoformat(), "time": None, "title": f"Vence la cotización N.º {number}: {title}", "sub": an, "href": f"/crm/cotizaciones/{qid}", "status": "open"})
    return {"items": items}
