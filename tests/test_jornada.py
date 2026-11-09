"""Jornada (Fase 5): campo informativo calculado de las horas del evento. Función pura app/workday.py + su lugar en el motor de plantilla (diseñador, creación, edición, calendario)."""
import copy

import pytest

from app import event_template as et
from app import workday as wd
from tests.conftest import login


# ------------------------------------------------------------------ función pura: límites inclusivos por arriba
@pytest.mark.parametrize("start,end,key,hours", [
    ("08:00", "08:01", "media", 0.02),
    ("08:00", "13:00", "media", 5.0),
    ("08:00", "14:00", "media", 6.0),                 # 6 h exactas = media (tope inclusivo)
    ("08:00", "14:01", "intermedia", 6.02),           # apenas pasa de 6
    ("08:00", "16:30", "intermedia", 8.5),
    ("08:00", "17:00", "intermedia", 9.0),            # 9 h exactas = intermedia
    ("08:00", "17:01", "completa", 9.02),
    ("08:00", "18:00", "completa", 10.0),
    ("08:00", "20:00", "completa", 12.0),             # 12 h exactas = completa
    ("08:00", "20:01", "extendida", 12.02),
    ("06:00", "23:59", "extendida", 17.98),
    ("00:00", "23:59", "extendida", 23.98),
])
def test_tiers_and_inclusive_bounds(start, end, key, hours):
    w = wd.compute_workday(start, end)
    assert w["key"] == key and w["hours"] == hours and w["label"] == wd.LABELS[key]


def test_labels_are_the_ones_the_owner_decided():
    assert wd.LABELS == {"media": "Media jornada", "intermedia": "Jornada intermedia (entre media y completa)", "completa": "Jornada completa", "extendida": "Jornada extendida"}
    assert wd.KEYS == ("media", "intermedia", "completa", "extendida")


def test_midnight_crossing_values():
    assert wd.compute_workday("22:00", "04:00")["key"] == "media"
    assert wd.compute_workday("18:00", "08:00")["hours"] == 14.0 and wd.compute_workday("18:00", "08:00")["key"] == "extendida"
    assert wd.compute_workday("23:30", "00:30")["hours"] == 1.0


@pytest.mark.parametrize("start,end", [(None, "18:00"), ("08:00", None), (None, None), ("", "18:00"), ("08:00", ""), ("08:00", "08:00"),
                                      ("25:00", "18:00"), ("08:60", "18:00"), ("ocho", "18:00"), (800, "18:00"), ("08:00", "24:00")])
def test_without_valid_hours_there_is_no_workday(start, end):
    assert wd.compute_workday(start, end) is None


def test_lenient_time_formats():
    assert wd.compute_workday("8:00", "17:00")["key"] == "intermedia"
    assert wd.compute_workday("08:00:00", "18:00:30")["hours"] == 10.0
    from datetime import time
    assert wd.compute_workday(time(8, 0), time(18, 0))["key"] == "completa"


def test_hours_text_uses_comma_and_no_trailing_zeros():
    assert wd.compute_workday("08:00", "18:00")["hours_text"] == "10 h"
    assert wd.compute_workday("08:00", "16:30")["hours_text"] == "8,5 h"
    assert wd.compute_workday("08:00", "16:15")["hours_text"] == "8,25 h"


def test_every_minute_of_the_day_classifies_consistently():
    """Recorre todas las duraciones posibles (1..1439 min): la clave sube de forma monótona y respeta los topes."""
    order = {k: i for i, k in enumerate(wd.KEYS)}
    last = -1
    for minutes in range(1, 1440):
        h, m = divmod(minutes, 60)
        w = wd.compute_workday("00:00", f"{h:02d}:{m:02d}")
        assert w is not None and order[w["key"]] >= last
        last = order[w["key"]]
        hrs = minutes / 60
        want = "media" if hrs <= 6 else "intermedia" if hrs <= 9 else "completa" if hrs <= 12 else "extendida"
        assert w["key"] == want


def test_event_helpers_work_with_any_object():
    class E:
        event_time_start = "08:00"
        event_time_end = "17:00"
    assert wd.event_workday(E())["key"] == "intermedia"
    assert wd.serialize(E()) == {"workday_key": "intermedia", "workday_label": wd.LABELS["intermedia"], "workday_hours": 9.0}
    assert wd.serialize(object()) == {"workday_key": None, "workday_label": None, "workday_hours": None}


# ------------------------------------------------------------------ plantilla: el campo es opcional, informativo y no tiene valor guardado
def test_factory_template_has_the_field_but_in_no_view():
    t = et.default_template()
    f = next(x for x in t["fields"] if x["key"] == "workday")
    assert f["type"] == "workday" and f["required"] is False and f["retired"] is False and f["title"] == "Jornada"
    assert all("workday" not in s["keys"] for s in t["creation_layout"]["sections"])
    assert all(i["key"] != "workday" for z in t["calendar_layout"]["zones"].values() for i in z)
    assert "workday" in et.BOUND_KEYS and "workday" not in et.BASE_COLUMNS
    assert "workday" not in et.catalog()["locked"] and {t_["type"] for t_ in et.catalog()["types"] if t_["creatable"]}.isdisjoint({"workday"})


def test_workday_is_never_required_even_if_the_payload_says_so():
    t = et.default_template()
    for f in t["fields"]:
        if f["key"] == "workday":
            f["required"] = True
    t["creation_layout"]["sections"][1]["keys"].append("workday")
    out = et.validate_template(t)
    assert next(f for f in out["fields"] if f["key"] == "workday")["required"] is False


def test_workday_can_be_placed_in_creation_and_calendar_and_values_are_ignored():
    t = et.default_template()
    t["creation_layout"]["sections"][1]["keys"].append("workday")
    t["calendar_layout"]["zones"]["right"].append({"key": "workday", "label": True})
    out = et.validate_template(t)
    assert "workday" in out["creation_layout"]["sections"][1]["keys"]
    assert any(i["key"] == "workday" for i in out["calendar_layout"]["zones"]["right"])
    f = next(x for x in out["fields"] if x["key"] == "workday")
    assert et.clean_value(f, "algo que nadie debería mandar") is None
    raw = et.raw_values_from_payload({"workday": "x", "name": "N"}, {})
    assert "workday" not in raw
    cols, extra = et.split_clean({"name": "N"})
    assert "workday" not in cols and "workday" not in extra


def test_a_saved_template_without_the_field_gets_it_back_unplaced():
    t = et.default_template()
    t["fields"] = [f for f in t["fields"] if f["key"] != "workday"]
    merged = et.merge_missing_base(t)
    assert any(f["key"] == "workday" for f in merged["fields"])
    assert all("workday" not in s["keys"] for s in merged["creation_layout"]["sections"])


def test_workday_cannot_be_sent_inside_extra_when_creating():
    t = et.default_template()
    t["creation_layout"]["sections"][1]["keys"].append("workday")
    res = et.evaluate_creation(t, {"workday": "x"}, extra_keys=["workday"])
    assert any("no existe en la plantilla" in e for e in res["errors"])


def test_js_fixture_still_matches():
    import json
    import os
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "js", "event_template_default.json"), encoding="utf-8"))
    assert any(f["key"] == "workday" for f in fx["fields"])


# ------------------------------------------------------------------ API: sale en el evento y en el calendario, sin guardarse
@pytest.fixture()
def admin(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    return client


def _place(client, creation=True, calendar=True):
    tpl = client.get("/api/event-template").json()
    body = {"version": tpl["version"], "fields": copy.deepcopy(tpl["fields"]), "creation_layout": copy.deepcopy(tpl["creation_layout"]), "calendar_layout": copy.deepcopy(tpl["calendar_layout"])}
    if creation:
        body["creation_layout"]["sections"][1]["keys"].append("workday")
    if calendar:
        body["calendar_layout"]["zones"]["right"].append({"key": "workday", "label": False})
    r = client.put("/api/event-template", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_template_with_workday_saves_and_round_trips(admin):
    saved = _place(admin)
    assert any("workday" in s["keys"] for s in saved["creation_layout"]["sections"])
    assert any(i["key"] == "workday" for i in saved["calendar_layout"]["zones"]["right"])
    again = admin.get("/api/event-template").json()
    assert next(f for f in again["fields"] if f["key"] == "workday")["type"] == "workday"


def test_creating_an_event_returns_the_computed_workday(admin, factory):
    _place(admin)
    coord = factory.staff("coordinador", "coord")
    payload = {"tenant_id": "acme", "event_code": "JOR-1", "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
               "start_date": "2026-11-01", "end_date": "2026-11-03", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
               "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord.id, "commercial_staff_id": None}
    com = factory.staff("comercial", "com")
    payload["commercial_staff_id"] = com.id
    r = admin.post("/api/events", json=payload)
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["workday_key"] == "completa" and ev["workday_hours"] == 10.0 and ev["workday_label"] == "Jornada completa"
    assert "workday" not in ev["extra"]                          # evento de varios días: la jornada es la del día de trabajo, y no se guarda


def test_event_without_hours_has_no_workday_and_changing_hours_updates_it(admin, factory):
    ev = factory.event(event_time_start="08:00", event_time_end="12:00")
    row = next(e for e in admin.get("/api/events").json() if e["id"] == ev.id)
    assert row["workday_key"] == "media" and row["workday_hours"] == 4.0
    r = admin.patch(f"/api/events/{ev.id}", json={"event_time_end": "23:00"})
    assert r.status_code == 200, r.text
    assert r.json()["workday_key"] == "extendida"
    bare = factory.event()
    row2 = next(e for e in admin.get("/api/events").json() if e["id"] == bare.id)
    assert row2["workday_key"] is None and row2["workday_label"] is None and row2["workday_hours"] is None


def test_calendar_endpoint_carries_the_workday(admin, factory):
    from datetime import date
    factory.event(event_time_start="22:00", event_time_end="04:00", start_date=date(2026, 11, 10), end_date=date(2026, 11, 12))
    events = admin.get("/api/events/calendar?start=2026-11-01&end=2026-11-30").json()
    assert any(e["workday_key"] == "media" and e["workday_label"] == "Media jornada" for e in events)
