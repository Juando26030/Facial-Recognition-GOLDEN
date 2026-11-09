"""Panel de gastos — pestaña «Eventos» (Fase 9, pieza D): satisfacción de los clientes y tiempos de cierre/facturación. SOLO administradores (admin y super_admin).

Lee lo que ya existe (encuestas `survey_responses`/`survey_answers`, fechas del evento, enlaces de entrega) y lo agrega por demanda; el cálculo está en app/event_analytics.py (puro).
Nada de datos personales de asistentes: solo eventos, clientes y cuentas del personal. Los comentarios (texto libre del cliente) los ve solo el administrador.
Se excluyen los eventos de prueba (código `LOAD-…` de las pruebas de carga) y los archivados no cuentan como excluidos (siguen siendo historia). La persona `PRUEBA` no interviene: aquí no se cuentan asistentes.
Respuestas con caché corta en memoria (60 s) por combinación de filtros: no se consulta la base cada vez que el administrador cambia de pestaña. Endpoints `def`."""
import io
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app import event_analytics as ea, xlsafe
from app.auth import require_platform_role
from app.database import get_db
from app.models import Event, EventDeliveryLink, StaffUser, SurveyAnswer, SurveyResponse, Tenant
from app.timeutil import to_local, utcnow
from app.ttlcache import TTLCache

router = APIRouter()
_cache = TTLCache(60, 256)
TEST_EVENT_PREFIXES = ("LOAD-",)          # eventos de las pruebas de carga: nunca cuentan
DEFAULT_MONTHS = 12
MAX_COMMENTS = 20
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
admin_only = require_platform_role("admin")      # admin y super_admin GLOBALES: ven comentarios de todos los clientes (F5-9 E)


def _staff_name(s: Optional[StaffUser]) -> Optional[str]:
    return (s.full_name or s.username) if s else None


def _parse_day(value: Optional[str], default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida (use AAAA-MM-DD)") from None


def _range(desde: Optional[str], hasta: Optional[str]) -> tuple:
    today = to_local(utcnow()).date()
    end = _parse_day(hasta, today)
    start = _parse_day(desde, end - timedelta(days=DEFAULT_MONTHS * 30))
    if start > end:
        raise HTTPException(status_code=422, detail="La fecha inicial es posterior a la final")
    return start, end


def _end_of_day(d: Optional[date]) -> Optional[datetime]:
    return datetime.combine(d, time(23, 59)) if d else None


def load_events(db: Session, start: date, end: date, tenant_id: Optional[str] = None, commercial_id: Optional[int] = None) -> list:
    """Filas de evento ya planas (diccionarios) con su encuesta si la hay. Eventos cuyo FIN cae entre `start` y `end`."""
    q = db.query(Event).filter(Event.end_date >= start, Event.end_date <= end)
    if tenant_id:
        q = q.filter(Event.tenant_id == tenant_id)
    if commercial_id:
        q = q.filter(Event.commercial_staff_id == commercial_id)
    events = [e for e in q.order_by(Event.end_date).all() if not (e.event_code or "").upper().startswith(TEST_EVENT_PREFIXES)]
    if not events:
        return []
    ids = [e.id for e in events]
    tenants = {t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_({e.tenant_id for e in events}))}
    staff_ids = {e.commercial_staff_id for e in events} | {e.coordinator_staff_id for e in events}
    staff = {s.id: s for s in db.query(StaffUser).filter(StaffUser.id.in_([i for i in staff_ids if i]))} if staff_ids else {}
    surveys = {s.event_id: s for s in db.query(SurveyResponse).filter(SurveyResponse.event_id.in_(ids))}
    links = {l.event_id: l for l in db.query(EventDeliveryLink).filter(EventDeliveryLink.event_id.in_(ids))}
    rows = []
    for e in events:
        s = surveys.get(e.id)
        link = links.get(e.id)
        rows.append({
            "id": e.id, "name": e.name, "city": e.city or "(sin ciudad)",
            "tenant_id": e.tenant_id, "tenant_name": tenants.get(e.tenant_id),
            "commercial_id": e.commercial_staff_id, "commercial_name": _staff_name(staff.get(e.commercial_staff_id)),
            "coordinator_id": e.coordinator_staff_id, "coordinator_name": _staff_name(staff.get(e.coordinator_staff_id)),
            "end_at": _end_of_day(e.end_date), "created_at": e.created_at, "finalized_at": e.finalized_at, "final_db_at": e.final_db_uploaded_at, "billed_at": e.billed_at,
            "has_link": link is not None, "delivery_opened": bool(link and link.last_opened_at),
            "survey": ({"avg_score": s.avg_score, "nps_score": s.nps_score, "submitted_at": s.submitted_at, "comment_count": s.comment_count} if s else None),
        })
    return rows


def _answers(db: Session, event_ids: list) -> list:
    if not event_ids:
        return []
    return [{"event_id": a.event_id, "question_id": a.question_id, "score": a.score, "choice_text": a.choice_text, "comment": a.comment, "tenant_id": a.tenant_id, "submitted_at": a.submitted_at}
            for a in db.query(SurveyAnswer).filter(SurveyAnswer.event_id.in_(event_ids))]


def _creations(db: Session, tenant_ids: set) -> dict:
    out: dict = {}
    if not tenant_ids:
        return out
    for tid, created in db.query(Event.tenant_id, Event.created_at).filter(Event.tenant_id.in_(tenant_ids)):
        if created:
            out.setdefault(tid, []).append(created)
    return out


def build_panel(db: Session, start: date, end: date, tenant_id: Optional[str], commercial_id: Optional[int], low: float, overdue_days: int, survey_days: int) -> dict:
    now = utcnow()
    events = load_events(db, start, end, tenant_id, commercial_id)
    by_id = {e["id"]: e for e in events}
    answers = _answers(db, list(by_id))
    surveyed = [e for e in events if e["survey"]]
    eligible = [e for e in events if e["billed_at"] or e["has_link"]]
    interest = ea.next_event_interest(answers)
    yes_rows = [{"tenant_id": a["tenant_id"], "submitted_at": a["submitted_at"]} for a in answers if a["question_id"] == "q8_next_event" and (a["choice_text"] or "").strip().lower() in ("sí", "si")]
    conv = ea.converted_next_event(yes_rows, _creations(db, {r["tenant_id"] for r in yes_rows}))
    nps_all = ea.nps(e["survey"]["nps_score"] for e in surveyed)
    comments = sorted(([{"event": by_id[a["event_id"]]["name"], "client": by_id[a["event_id"]]["tenant_name"], "date": a["submitted_at"].strftime("%Y-%m-%d"), "text": a["comment"].strip()[:600]}
                        for a in answers if (a["comment"] or "").strip() and a["event_id"] in by_id]), key=lambda r: r["date"], reverse=True)[:MAX_COMMENTS]
    this_month = to_local(now).strftime("%Y-%m")
    month_events = [e for e in events if ea.month_key(e["billed_at"]) == this_month]
    month_surveys = [e for e in surveyed if ea.month_key(e["survey"]["submitted_at"]) == this_month]
    month_bill = ea.stats(ea.event_times(e)["bill_after_end_days"] for e in month_events)["mean"]
    times = ea.time_summary(events)
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "events_total": len(events),
        "summary_text": ea.plain_summary(month_label="Este mes", nps_value=ea.nps(e["survey"]["nps_score"] for e in month_surveys)["value"], billed_count=len(month_events),
                                         bill_days_mean=month_bill, responses=len(month_surveys)),
        "kpis": {"nps": nps_all, "avg_quality": ea.rnd(ea.mean(e["survey"]["avg_score"] for e in surveyed), 2), "responses": len(surveyed), "eligible": len(eligible),
                 "response_rate_pct": ea.rnd(len(surveyed) * 100.0 / len(eligible)) if eligible else None, "next_event": interest, "converted": conv,
                 "bill_median_days": times["bill_after_end_days"]["median"], "close_median_days": times["close_days"]["median"]},
        "satisfaction": {
            "questions": ea.question_averages(answers), "nps_distribution": ea.nps_distribution(e["survey"]["nps_score"] for e in surveyed), "monthly": ea.monthly_satisfaction(events),
            "best": ea.ranking(events, True), "worst": ea.ranking(events, False),
            "by_commercial": ea.group_satisfaction(events, "commercial_id", "commercial_name"), "by_coordinator": ea.group_satisfaction(events, "coordinator_id", "coordinator_name"),
            "by_client": ea.group_satisfaction(events, "tenant_id", "tenant_name"), "by_city": ea.group_satisfaction(events, "city", "city"), "comments": comments},
        "times": {"summary": times, "monthly": ea.monthly_times(events), "by_commercial": ea.group_times(events, "commercial_id", "commercial_name"), "by_client": ea.group_times(events, "tenant_id", "tenant_name"),
                  "overdue": ea.overdue_events(events, now, overdue_days)},
        "alerts": {"low_satisfaction": ea.low_satisfaction(events, low), "pending_surveys": ea.pending_surveys(events, now, survey_days), "declining_clients": ea.declining_clients(events),
                   "params": {"low_threshold": low, "overdue_days": overdue_days, "survey_wait_days": survey_days}},
    }


def _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait) -> dict:
    start, end = _range(desde, hasta)
    key = (start, end, cliente or "", comercial or 0, low, overdue, wait)
    return _cache.get_or_set(key, lambda: build_panel(db, start, end, cliente or None, comercial or None, low, overdue, wait))


_FILTERS = dict(desde=Query(None), hasta=Query(None), cliente=Query(None), comercial=Query(None, ge=1),
                low=Query(ea.LOW_SCORE_DEFAULT, ge=1, le=3), overdue=Query(ea.OVERDUE_DAYS_DEFAULT, ge=1, le=365), wait=Query(ea.SURVEY_WAIT_DAYS_DEFAULT, ge=1, le=365))


@router.get("/gastos/eventos/filtros")
def filtros(db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    """Listas para los selectores: clientes y comerciales (nombres; sin contacto)."""
    tenants = db.query(Tenant.id, Tenant.name).filter(Tenant.archived_at.is_(None)).order_by(Tenant.name).all()
    coms = db.query(StaffUser).filter(StaffUser.is_active.is_(True), StaffUser.role.in_(("comercial", "admin", "super_admin", "coordinador"))).order_by(StaffUser.full_name).all()
    return {"clients": [{"id": i, "name": n} for i, n in tenants], "commercials": [{"id": s.id, "name": _staff_name(s)} for s in coms],
            "defaults": {"low_threshold": ea.LOW_SCORE_DEFAULT, "overdue_days": ea.OVERDUE_DAYS_DEFAULT, "survey_wait_days": ea.SURVEY_WAIT_DAYS_DEFAULT}}


@router.get("/gastos/eventos/panel")
def panel(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
          low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    return _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)


@router.get("/gastos/eventos/resumen")
def resumen(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
            low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    p = _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)
    return {"range": p["range"], "events_total": p["events_total"], "summary_text": p["summary_text"], "kpis": p["kpis"]}


@router.get("/gastos/eventos/satisfaccion")
def satisfaccion(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
                 low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    return _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)["satisfaction"]


@router.get("/gastos/eventos/tiempos")
def tiempos(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
            low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    return _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)["times"]


@router.get("/gastos/eventos/alertas")
def alertas(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
            low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    return _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)["alerts"]


def _sheet(ws, header: list, rows: list) -> None:
    ws.append(header)
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(48, max(12, max(len(str(c.value or "")) for c in col) + 2))


@router.get("/gastos/eventos/exportar")
def exportar(desde: Optional[str] = _FILTERS["desde"], hasta: Optional[str] = _FILTERS["hasta"], cliente: Optional[str] = _FILTERS["cliente"], comercial: Optional[int] = _FILTERS["comercial"],
             low: float = _FILTERS["low"], overdue: int = _FILTERS["overdue"], wait: int = _FILTERS["wait"], db: Session = Depends(get_db), staff: StaffUser = Depends(admin_only)):
    """Excel con una hoja por tema (resumen, eventos con sus tiempos y nota, por pregunta, por comercial, por cliente, atrasados, comentarios)."""
    p = _panel_cached(db, desde, hasta, cliente, comercial, low, overdue, wait)
    start, end = _range(desde, hasta)
    events = load_events(db, start, end, cliente or None, comercial or None)
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    k = p["kpis"]
    _sheet(ws, ["Indicador", "Valor"], [["Periodo", f"{p['range']['from']} a {p['range']['to']}"], ["Resumen", p["summary_text"]], ["Eventos", p["events_total"]], ["NPS", k["nps"]["value"]],
                                        ["Encuestas respondidas", k["responses"]], ["Tasa de respuesta (%)", k["response_rate_pct"]], ["Promedio de calidad (1-3)", k["avg_quality"]],
                                        ["Interesados en otro evento (%)", k["next_event"]["pct_yes"]], ["Mediana días fin → facturado", k["bill_median_days"]], ["Mediana días fin → finalizado", k["close_median_days"]]])
    _sheet(wb.create_sheet("Eventos"), ["Evento", "Cliente", "Comercial", "Coordinador", "Ciudad", "Fin del evento", "Días a finalizar", "Días a subir la base", "Días finalizado → facturado", "Días fin → facturado", "Calidad (1-3)", "Recomendación (0-10)"],
           [[e["name"], e["tenant_name"], e["commercial_name"], e["coordinator_name"], e["city"], e["end_at"].strftime("%Y-%m-%d") if e["end_at"] else None,
             *[ea.rnd(v) for v in ea.event_times(e).values()], ea.rnd(e["survey"]["avg_score"], 2) if e["survey"] else None, e["survey"]["nps_score"] if e["survey"] else None] for e in events])
    _sheet(wb.create_sheet("Por pregunta"), ["Pregunta", "Respuestas", "Promedio (1-3)", "Malo", "Bueno", "Excelente"], [[q["label"], q["n"], q["avg"], q["bad"], q["good"], q["excellent"]] for q in p["satisfaction"]["questions"]])
    _sheet(wb.create_sheet("Por comercial"), ["Comercial", "Eventos", "Calidad (1-3)", "NPS"], [[g["name"], g["events"], g["avg"], g["nps"]] for g in p["satisfaction"]["by_commercial"]])
    _sheet(wb.create_sheet("Por cliente"), ["Cliente", "Eventos", "Calidad (1-3)", "NPS"], [[g["name"], g["events"], g["avg"], g["nps"]] for g in p["satisfaction"]["by_client"]])
    _sheet(wb.create_sheet("Por mes"), ["Mes", "Encuestas", "Calidad (1-3)", "NPS"], [[m["month"], m["responses"], m["avg"], m["nps"]] for m in p["satisfaction"]["monthly"]])
    _sheet(wb.create_sheet("Sin facturar"), ["Evento", "Cliente", "Comercial", "Días esperando", "Base final subida"], [[o["name"], o["client"], o["commercial"], o["days_waiting"], "Sí" if o["final_db"] else "No"] for o in p["times"]["overdue"]])
    _sheet(wb.create_sheet("Comentarios"), ["Fecha", "Evento", "Cliente", "Comentario"], [[c["date"], c["event"], c["client"], c["text"]] for c in p["satisfaction"]["comments"]])
    xlsafe.safe_workbook(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="analisis_eventos_{p["range"]["from"]}_{p["range"]["to"]}.xlsx"', "Cache-Control": "no-store"})
