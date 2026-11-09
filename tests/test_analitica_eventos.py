"""Fase 9 D: análisis de eventos (satisfacción y tiempos). Lógica pura (app/event_analytics.py) + API /api/gastos/eventos/* (solo admin)."""
from datetime import date, datetime, timedelta

import pytest

from app import event_analytics as ea
from app.models import EventDeliveryLink, SurveyAnswer, SurveyResponse
from app.timeutil import utcnow
from tests.conftest import login

D = datetime


# ------------------------------------------------------------------ lógica pura
def test_nps_formula():
    r = ea.nps([10, 9, 9, 8, 7, 6, 0, 3])          # 3 promotores, 2 pasivos, 3 detractores
    assert (r["promoters"], r["passives"], r["detractors"], r["total"]) == (3, 2, 3, 8)
    assert r["value"] == 0
    assert ea.nps([10, 10, 9])["value"] == 100
    assert ea.nps([0, 5, 6])["value"] == -100
    assert ea.nps([])["value"] is None


def test_percentiles_and_stats():
    assert ea.median([1, 2, 3, 4]) == 2.5
    assert ea.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == pytest.approx(9.1)
    assert ea.stats([]) == {"n": 0, "mean": None, "median": None, "p90": None}
    assert ea.stats([2, 4, None])["mean"] == 3


def test_days_between_never_negative():
    assert ea.days_between(D(2026, 1, 1), D(2026, 1, 11)) == 10
    assert ea.days_between(D(2026, 1, 11), D(2026, 1, 1)) is None
    assert ea.days_between(None, D(2026, 1, 1)) is None


def test_event_times_and_summary():
    e = {"end_at": D(2026, 3, 1), "finalized_at": D(2026, 3, 6), "final_db_at": D(2026, 3, 4), "billed_at": D(2026, 3, 16)}
    t = ea.event_times(e)
    assert t == {"close_days": 5, "base_days": 3, "bill_after_final_days": 10, "bill_after_end_days": 15}
    s = ea.time_summary([e, {"end_at": D(2026, 3, 1), "finalized_at": D(2026, 3, 11)}])
    assert s["close_days"]["n"] == 2 and s["close_days"]["mean"] == 7.5
    assert s["bill_after_end_days"]["n"] == 1


def test_question_averages_and_interest():
    answers = [{"question_id": "q1_experience", "score": 3}, {"question_id": "q1_experience", "score": 1}, {"question_id": "q6_badges", "score": None},
               {"question_id": "q7_nps", "score": 9}, {"question_id": "q8_next_event", "choice_text": "Sí"}, {"question_id": "q8_next_event", "choice_text": "No"},
               {"question_id": "q8_next_event", "choice_text": "si"}]
    q = ea.question_averages(answers)
    assert len(q) == 1 and q[0]["avg"] == 2 and q[0]["bad"] == 1 and q[0]["excellent"] == 1
    i = ea.next_event_interest(answers)
    assert (i["yes"], i["no"], i["pct_yes"]) == (2, 1, 66.7)


def _ev(i, avg, nps_score, end, billed=None, fin=None, tenant="t1", sub=None):
    return {"id": i, "name": f"E{i}", "tenant_id": tenant, "tenant_name": tenant.upper(), "commercial_id": 1, "commercial_name": "Com", "city": "Bogotá", "end_at": end, "finalized_at": fin,
            "billed_at": billed, "final_db_at": None, "delivery_opened": False,
            "survey": ({"avg_score": avg, "nps_score": nps_score, "submitted_at": sub or end} if avg is not None else None)}


def test_alerts_overdue_pending_low_declining():
    now = D(2026, 6, 1)
    events = [_ev(1, 2.9, 10, D(2026, 1, 10), billed=D(2026, 1, 20), fin=D(2026, 1, 12)),
              _ev(2, 1.5, 4, D(2026, 2, 10), billed=D(2026, 2, 20), fin=D(2026, 2, 12), tenant="t2"),
              _ev(3, None, None, D(2026, 3, 10), billed=D(2026, 3, 20), fin=D(2026, 3, 12), tenant="t2"),
              _ev(4, None, None, D(2026, 4, 1), fin=D(2026, 4, 5), tenant="t3"),
              _ev(5, 2.0, 8, D(2026, 5, 1), billed=D(2026, 5, 3), fin=D(2026, 5, 2), tenant="t1"),
              _ev(6, 2.9, 9, D(2026, 4, 1), billed=D(2026, 4, 3), fin=D(2026, 4, 2), tenant="t2", sub=D(2026, 4, 10))]
    assert [o["event_id"] for o in ea.overdue_events(events, now, 30)] == [4]
    assert [o["event_id"] for o in ea.overdue_events(events, now, 90)] == []
    assert [p["event_id"] for p in ea.pending_surveys(events, now, 7)] == [3]
    assert [l["event_id"] for l in ea.low_satisfaction(events, 1.8)] == [2]
    dec = ea.declining_clients(events, 0.3)
    assert [d["client"] for d in dec] == ["T1"] and dec[0]["drop"] == 0.9      # t1: 2.9 -> 2.0; t2 (1.5 antes de 2.9) sube, no cae


def test_group_and_monthly_and_converted():
    events = [_ev(1, 3.0, 10, D(2026, 1, 10)), _ev(2, 2.0, 5, D(2026, 1, 20)), _ev(3, 1.0, 0, D(2026, 2, 5))]
    g = ea.group_satisfaction(events, "tenant_id", "tenant_name")
    assert g[0]["avg"] == 2.0 and g[0]["events"] == 3
    m = ea.monthly_satisfaction(events)
    assert [x["month"] for x in m] == ["2026-01", "2026-02"] and m[0]["avg"] == 2.5
    assert [r["event_id"] for r in ea.ranking(events, True, 2)] == [1, 2]
    assert [r["event_id"] for r in ea.ranking(events, False, 1)] == [3]
    c = ea.converted_next_event([{"tenant_id": "a", "submitted_at": D(2026, 1, 1)}, {"tenant_id": "b", "submitted_at": D(2026, 1, 1)}], {"a": [D(2026, 2, 1)], "b": [D(2025, 12, 1)]})
    assert c == {"interested": 2, "converted": 1, "pct": 50.0}


def test_plain_summary():
    s = ea.plain_summary(month_label="Este mes", nps_value=40, billed_count=1, bill_days_mean=12.5, responses=3)
    assert s == "Este mes: NPS +40, 3 encuestas respondidas, 1 evento facturado, tiempo promedio de facturación 12.5 días."
    assert "sin NPS" in ea.plain_summary(month_label="Este mes", nps_value=None, billed_count=0, bill_days_mean=None, responses=0)


# ------------------------------------------------------------------ API
def _survey(db, ev, avg, nps_score, comment=None, next_event="Sí", when=None):
    when = when or utcnow()
    r = SurveyResponse(event_id=ev.id, tenant_id=ev.tenant_id, survey_version=1, submitted_at=when, nps_score=nps_score, avg_score=avg, comment_count=1 if comment else 0)
    r.answers = [SurveyAnswer(event_id=ev.id, tenant_id=ev.tenant_id, submitted_at=when, survey_version=1, question_id="q1_experience", score=3),
                 SurveyAnswer(event_id=ev.id, tenant_id=ev.tenant_id, submitted_at=when, survey_version=1, question_id="q7_nps", score=nps_score),
                 SurveyAnswer(event_id=ev.id, tenant_id=ev.tenant_id, submitted_at=when, survey_version=1, question_id="q8_next_event", choice_text=next_event, comment=comment)]
    db.add(r)
    db.commit()


@pytest.fixture()
def datos(client, factory, db):
    admin = factory.staff("admin", "adm1")
    com = factory.staff("comercial", "com1")
    today = date.today()
    e1 = factory.event("finalizado", commercial=com, end_date=today - timedelta(days=20), finalized_at=utcnow() - timedelta(days=18), billed_at=utcnow() - timedelta(days=10))
    e2 = factory.event("finalizado", commercial=com, end_date=today - timedelta(days=60), finalized_at=utcnow() - timedelta(days=50))
    e3 = factory.event("finalizado", commercial=com, end_date=today - timedelta(days=5))
    e3.event_code = "LOAD-STG"
    db.add(EventDeliveryLink(event_id=e1.id))
    db.commit()
    _survey(db, e1, 2.8, 10, comment="Excelente servicio")
    return {"admin": admin, "com": com, "e1": e1, "e2": e2, "e3": e3}


def test_only_admin_can_read(client, factory, datos):
    assert client.get("/api/gastos/eventos/panel").status_code == 401
    login(client, "com1")
    for path in ("panel", "resumen", "satisfaccion", "tiempos", "alertas", "filtros", "exportar"):
        assert client.get(f"/api/gastos/eventos/{path}").status_code == 403


def test_panel_numbers_and_test_event_excluded(client, datos):
    login(client, "adm1")
    r = client.get("/api/gastos/eventos/panel")
    assert r.status_code == 200
    d = r.json()
    assert d["events_total"] == 2                                  # e3 (LOAD-) no cuenta
    k = d["kpis"]
    assert k["nps"]["value"] == 100 and k["responses"] == 1 and k["eligible"] == 1 and k["response_rate_pct"] == 100.0
    assert k["next_event"]["yes"] == 1
    assert d["times"]["summary"]["bill_after_end_days"]["n"] == 1
    assert [o["event_id"] for o in d["times"]["overdue"]] == [datos["e2"].id]
    assert d["satisfaction"]["comments"][0]["text"] == "Excelente servicio"
    assert "Este mes" in d["summary_text"]


def test_filters_and_validation(client, datos):
    login(client, "adm1")
    assert client.get("/api/gastos/eventos/resumen?cliente=no-existe").json()["events_total"] == 0
    assert client.get("/api/gastos/eventos/resumen?desde=2020-01-01&hasta=2019-01-01").status_code == 422
    assert client.get("/api/gastos/eventos/resumen?desde=hola").status_code == 422
    assert client.get("/api/gastos/eventos/alertas?low=9").status_code == 422
    f = client.get("/api/gastos/eventos/filtros").json()
    assert any(c["id"] == "acme" for c in f["clients"])


def test_export_excel(client, datos):
    import io
    from openpyxl import load_workbook
    login(client, "adm1")
    r = client.get("/api/gastos/eventos/exportar")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    assert {"Resumen", "Eventos", "Por pregunta", "Sin facturar", "Comentarios"} <= set(wb.sheetnames)
    assert wb["Comentarios"]["D2"].value == "Excelente servicio"
