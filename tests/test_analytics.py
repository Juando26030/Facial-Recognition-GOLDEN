"""Módulo de analítica compartido: helpers y tablero del Registro del evento (Sprint 5)."""
from datetime import datetime, timedelta

from tests.conftest import login


# ------------------------------- helpers (app/analytics.py) -------------------------------
def test_time_series_picks_a_bucket_width_from_the_span_and_accumulates():
    from app import analytics as an

    base = datetime(2026, 10, 1, 13, 0, 0)          # 08:00 en Bogotá
    stamps = [base + timedelta(minutes=m) for m in (0, 3, 4, 20, 21, 59)]
    c = an.time_series("t", "T", stamps)
    assert c["type"] == "line" and c["labels"][0] == "08:00"
    assert sum(c["datasets"][0]["data"]) == 6 and c["datasets"][1]["data"][-1] == 6           # acumulado termina en el total
    assert c["datasets"][1]["data"] == sorted(c["datasets"][1]["data"])
    assert len(c["labels"]) <= 60


def test_time_series_widens_buckets_for_long_spans_and_handles_empty():
    from app import analytics as an

    stamps = [datetime(2026, 10, 1, 13) + timedelta(hours=h) for h in range(0, 200, 5)]
    c = an.time_series("t", "T", stamps)
    assert len(c["labels"]) <= 60 and "/" in c["labels"][0]                 # más de un día: la etiqueta trae la fecha
    assert an.time_series("t", "T", []) is None and an.hour_histogram("h", "H", []) is None and an.peak_hour([]) is None


def test_counter_chart_groups_the_tail_into_others():
    from app import analytics as an

    values = [f"E{i}" for i in range(15) for _ in range(15 - i)] + ["", None]
    c = an.counter_chart("c", "C", values, top=5)
    assert len(c["labels"]) == 6 and c["labels"][-1] == "Otros" and c["labels"][0] == "E0"
    assert sum(c["datasets"][0]["data"]) == sum(15 - i for i in range(15))       # vacíos no cuentan, nada se pierde
    assert an.counter_chart("c", "C", ["", None]) is None


def test_formatters():
    from app import analytics as an

    assert an.pct(1, 3) == "33%" and an.pct(0, 0) == "0%"
    assert an.fmt_duration(45) == "45 s" and an.fmt_duration(125) == "2 min 05 s" and an.fmt_duration(3900) == "1 h 05 min"


# ------------------------------- tablero del Registro -------------------------------
def _event_with_registrations(factory, db):
    from app.models import AccessLog, EventAttendee

    staff = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=staff)
    ev.categories = '["VIP","General"]'
    people = []
    for i in range(1, 7):
        u = factory.person(ev, f"{2000 + i}", f"N{i}", f"A{i}")
        u.entity = "ACME" if i <= 4 else "OTRA"
        people.append(u)
        db.query(EventAttendee).filter_by(event_id=ev.id, user_id=u.id).update({"categories": '["VIP"]' if i <= 2 else '["General"]'})
    base = datetime(2026, 10, 1, 13, 0, 0)         # 08:00 Bogotá
    for uid, minutes, method in (("2001", 0, "tradicional"), ("2002", 5, "qr"), ("2003", 65, "qr"), ("2005", 70, "biometrico")):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method=method,
                         timestamp=base + timedelta(minutes=minutes), registered_by_staff_id=staff.id))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="2004", event_id=ev.id, record_type="Actualizado", timestamp=base))   # una edición NO es un registro
    db.commit()
    return ev


def test_registro_dashboard_numbers(client, factory, db):
    ev = _event_with_registrations(factory, db)
    login(client, "coord1")
    d = client.get(f"/api/events/{ev.id}/analytics/registro").json()
    k = {x["label"]: x for x in d["kpis"]}
    assert k["Base del evento"]["value"] == 6 and k["Registrados"]["value"] == 4 and k["Pendientes"]["value"] == 2
    assert k["Registrados"]["hint"].startswith("67%")
    assert k["Primer registro"]["value"].endswith("08:00") and k["Último registro"]["value"].endswith("09:10")
    assert k["Hora pico"]["value"].startswith("08:00") and "(2)" in k["Hora pico"]["value"]
    charts = {c["id"]: c for c in d["charts"]}
    assert {"timeline", "by_hour", "by_method", "by_category", "by_entity", "by_operator"} <= set(charts)
    methods = dict(zip(charts["by_method"]["labels"], charts["by_method"]["datasets"][0]["data"]))
    assert methods == {"Tradicional": 1, "QR": 2, "Biométrico": 1}
    cat = charts["by_category"]
    assert cat["stacked"] and dict(zip(cat["labels"], cat["datasets"][0]["data"])) == {"VIP": 2, "General": 2}        # registrados
    assert dict(zip(cat["labels"], cat["datasets"][1]["data"])) == {"VIP": 0, "General": 2}                          # pendientes
    ent = dict(zip(charts["by_entity"]["labels"], zip(*[ds["data"] for ds in charts["by_entity"]["datasets"]])))
    assert ent == {"ACME": (3, 1), "OTRA": (1, 1)}
    assert charts["by_operator"]["datasets"][0]["data"] == [4]


def test_registro_dashboard_for_an_empty_event_does_not_break(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    r = client.get(f"/api/events/{ev.id}/analytics/registro")
    assert r.status_code == 200 and r.json()["charts"] == [] and r.json()["kpis"][0]["value"] == 0


def test_registro_dashboard_permissions(client, factory, db):
    ev = _event_with_registrations(factory, db)
    cli = factory.staff("cliente", "cli")
    dig = factory.staff("digitador", "9990001")
    factory.authorize(ev, cli)
    factory.authorize(ev, dig)
    url = f"/api/events/{ev.id}/analytics/registro"
    assert client.get(url).status_code == 401                                   # sin sesión
    login(client, "9990001")
    assert client.get(url).status_code == 403                                   # digitador no
    client.post("/logout")
    login(client, "cli")
    assert client.get(url).status_code == 200                                   # el cliente del evento sí (reemplaza el placeholder)


def test_stats_page_mounts_the_shared_dashboard(client, factory, db):
    ev = _event_with_registrations(factory, db)
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}/estadisticas").text
    assert "analytics-dashboard.js" in page and "/analytics/registro" in page
