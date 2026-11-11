"""Tipos de evento (Fase 10, bloque C): la «Categoría (tipo de evento)» del calendario. Pruebas con base (API, historial, plantilla) y de texto (migración, pantallas, JS)."""
import re
from pathlib import Path

import pytest

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _payload(coord_id, code="TE-1", **extra):
    base = {"tenant_id": "acme", "event_code": code, "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
            "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord_id}
    base.update(extra)
    return base


# ---------- texto: migración, pantallas, JS (corren sin base) ----------

def test_migration_0128_is_chained_and_seeds_the_types():
    src = _read("alembic/versions/0128_event_types.py")
    rev = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    assert rev == "0128_event_types" and len(rev) <= 32
    assert not re.search(r"\bSET\s+(LOCAL\s+|SESSION\s+)?\w+\s*(=|TO)\b", src)
    assert 'down_revision = "0127_person_change_log"' in src
    for name in ("Feria", "Congreso", "Corporativo", "Social", "Otro"):
        assert f'"{name}"' in src
    assert "event_type_id" in src and "nullable=True" in src


def test_configuracion_tab_is_super_admin_only():
    t = _read("templates/configuracion.html")
    assert 'id="tab_tipos"' in t and 'id="tipos"' in t and "event-types-admin.js" in t
    block = t[t.index("is_super"):]
    assert "event-types-admin.js" in block


def test_edit_modal_and_wizard_have_the_field():
    assert "eeEventType" in _read("templates/_event_edit_modal.html")
    js = _read("static/js/event-field-render.js")
    assert "event_type" in js and "eventTypes" in js
    assert "/api/event-types" in _read("static/js/nuevo-evento.js")


def test_calendar_chips_use_the_event_type():
    js = _read("static/js/calendar-cats.js")
    assert "event_type_id" in js and "Sin categoría" in js
    assert "event_type" in _read("app/routers/events.py")


# ---------- plantilla (puro) ----------

def test_template_places_event_type_after_name_in_old_templates():
    from app import event_template as et
    tpl = et.default_template()
    assert "event_type_id" in {f["key"] for f in tpl["fields"]}
    sec = next(s for s in tpl["creation_layout"]["sections"] if s["id"] == "datos")
    assert sec["keys"].index("event_type_id") == sec["keys"].index("name") + 1
    # una plantilla guardada antes del campo lo recibe sola, justo después del nombre
    old = {"fields": [f for f in tpl["fields"] if f["key"] != "event_type_id"],
           "creation_layout": {"sections": [dict(s, keys=[k for k in s["keys"] if k != "event_type_id"]) for s in tpl["creation_layout"]["sections"]]},
           "calendar_layout": tpl["calendar_layout"]}
    merged = et.merge_missing_base(old)
    sec = next(s for s in merged["creation_layout"]["sections"] if s["id"] == "datos")
    assert sec["keys"].index("event_type_id") == sec["keys"].index("name") + 1


# ---------- con base ----------

def test_only_super_admin_writes_and_coordinator_reads(client, factory):
    factory.staff("coordinador", "coord")
    factory.staff("super_admin", "root")
    login(client, "coord")
    r = client.get("/api/event-types")
    assert r.status_code == 200
    assert client.post("/api/event-types", json={"name": "Nuevo"}).status_code == 403
    assert client.get("/api/event-types?include_archived=true").status_code == 403
    login(client, "root")
    assert client.post("/api/event-types", json={"name": "Deportivo", "color": "#112233"}).status_code == 200


def test_validation_duplicates_archive_and_restore(client, factory):
    factory.staff("super_admin", "root")
    login(client, "root")
    assert client.post("/api/event-types", json={"name": "  "}).status_code == 400
    assert client.post("/api/event-types", json={"name": "X" * 81}).status_code == 400
    assert client.post("/api/event-types", json={"name": "Rara", "color": "rojo"}).status_code == 400
    t = client.post("/api/event-types", json={"name": "Rara", "color": "#AABBCC"}).json()
    assert client.post("/api/event-types", json={"name": "rara"}).status_code == 400
    r = client.patch(f"/api/event-types/{t['id']}", json={"name": "Rara 2", "color": ""})
    assert r.status_code == 200 and r.json()["name"] == "Rara 2" and r.json()["color"] == ""
    assert client.post(f"/api/event-types/{t['id']}/restore").status_code == 400
    assert client.post(f"/api/event-types/{t['id']}/archive").status_code == 200
    assert client.post(f"/api/event-types/{t['id']}/archive").status_code == 400
    assert client.patch(f"/api/event-types/{t['id']}", json={"name": "Z"}).status_code == 400
    assert t["id"] not in {x["id"] for x in client.get("/api/event-types").json()["types"]}
    assert t["id"] in {x["id"] for x in client.get("/api/event-types?include_archived=true").json()["types"]}
    assert client.post(f"/api/event-types/{t['id']}/restore").status_code == 200
    assert client.patch("/api/event-types/999999", json={"name": "Z"}).status_code == 404


def test_event_create_update_with_type_and_archived_rules(client, factory):
    factory.tenant("acme")
    root = factory.staff("super_admin", "root")
    login(client, "root")
    a = client.post("/api/event-types", json={"name": "Tipo A", "color": "#010203"}).json()
    b = client.post("/api/event-types", json={"name": "Tipo B"}).json()
    assert client.post("/api/events", json=_payload(root.id, event_type_id=999999)).status_code == 400
    ev = client.post("/api/events", json=_payload(root.id, event_type_id=a["id"])).json()
    assert ev["event_type_id"] == a["id"] and ev["event_type_name"] == "Tipo A" and ev["event_type_color"] == "#010203"
    # archivar A: el evento lo conserva, pero no se puede asignar a otro evento
    client.post(f"/api/event-types/{a['id']}/archive")
    ev2 = client.get(f"/api/events/{ev['id']}").json()
    assert ev2["event_type_id"] == a["id"]
    assert client.post("/api/events", json=_payload(root.id, code="TE-2", event_type_id=a["id"])).status_code == 400
    assert client.patch(f"/api/events/{ev['id']}", json={"event_type_id": a["id"]}).status_code == 200  # conservarlo sí
    r = client.patch(f"/api/events/{ev['id']}", json={"event_type_id": b["id"]})
    assert r.status_code == 200 and r.json()["event_type_name"] == "Tipo B"
    r = client.patch(f"/api/events/{ev['id']}", json={"event_type_id": None})
    assert r.status_code == 200 and r.json()["event_type_id"] is None


def test_history_snapshot_uses_the_type_name(client, factory, db):
    from app import event_history
    factory.tenant("acme")
    root = factory.staff("super_admin", "root")
    login(client, "root")
    t = client.post("/api/event-types", json={"name": "Historial"}).json()
    ev = client.post("/api/events", json=_payload(root.id, code="TE-H", event_type_id=t["id"])).json()
    from app.models import Event
    assert event_history.snapshot(db, db.get(Event, ev["id"]))["event_type_id"] == "Historial"


def test_edit_modal_shows_the_category_in_the_first_group_for_every_event():
    """Bug de staging: el selector estaba en «Superevento y pañoleta» (plegado). Ahora va en «Datos del evento», no depende de la plantilla guardada."""
    t = _read("templates/_event_edit_modal.html")
    first = t.index("Datos del evento")
    second = t.index("Fechas y horarios")
    assert first < t.index('id="eeEventType"') < second
    assert 'if (tpl' not in t[t.index("async function paintEventType"):t.index("window.openEventEditModal")]          # no depende de la plantilla


def test_designer_edits_the_same_catalog():
    d = _read("static/js/event-template-designer.js")
    assert "data-evtype-options" in d and "EventTypeOptions.mount" in d
    o = _read("static/js/event-type-options.js")
    assert "/api/event-types" in o and "canEdit" in o
    assert "event-type-options.js" in _read("templates/plantilla_evento.html")
    assert "data-super" in _read("templates/plantilla_evento.html")
