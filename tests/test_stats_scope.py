"""Hotfix 23-nov-2026: estadísticas sobre toda la base, solo registrados o solo no registrados. Lo configurado en Parámetros › Campos
(«Contar a») es lo que abre Estadísticas; el panel lo cambia solo por el momento (pasa `scope` en la consulta). Datos ficticios. Con base de datos."""
from app.models import EventFieldConfig, User
from app.routers import parametros
from tests.conftest import login


def _ev(factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    db.commit()
    for uid, ent, reg in (("1001", "A", True), ("1002", "A", False), ("1003", "B", True), ("1004", "B", False), ("1005", "B", False)):
        factory.person(ev, uid, f"N{uid}", "Prueba", registered=reg)
        u = db.get(User, (uid, ev.tenant_id))
        u.entity = ent
    db.commit()
    return ev


def _counts(client, ev, variable, scope=None):
    params = {"variable": variable} if scope is None else {"variable": variable, "scope": scope}
    r = client.get(f"/api/events/{ev.id}/stats/data", params=params)
    assert r.status_code == 200, r.text
    return {b["label"]: b["count"] for b in r.json()["buckets"]}


def test_scope_filters_people_by_registration(client, factory, db):
    ev = _ev(factory, db)
    login(client, "root")
    assert _counts(client, ev, "entity") == {"A": 2, "B": 3}                       # sin alcance = toda la base (como antes)
    assert _counts(client, ev, "entity", "all") == {"A": 2, "B": 3}
    assert _counts(client, ev, "entity", "registered") == {"A": 1, "B": 1}
    assert _counts(client, ev, "entity", "unregistered") == {"A": 1, "B": 2}
    assert _counts(client, ev, "status", "registered") == {"Registrado": 2}
    assert client.get(f"/api/events/{ev.id}/stats/data", params={"variable": "entity", "scope": "otro"}).status_code == 400


def test_field_config_saves_scope_without_migration(client, factory, db):
    ev = _ev(factory, db)
    login(client, "root")
    body = {"label": "", "required": False, "field_type": "text_short", "options": [], "default_stat_enabled": True, "default_chart_type": "bar", "default_stat_scope": "registered"}
    r = client.put(f"/api/events/{ev.id}/field-configs/entity", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["default_chart_type"] == "bar" and r.json()["default_stat_scope"] == "registered"
    row = db.query(EventFieldConfig).filter_by(event_id=ev.id, field_key="entity").one()
    assert row.default_chart_type == "bar@registered"                               # viaja en la misma columna (sin migración)
    var = next(v for v in client.get(f"/api/events/{ev.id}/stats/variables").json() if v["key"] == "entity")
    assert var["default_stat_enabled"] and var["default_chart_type"] == "bar" and var["default_stat_scope"] == "registered"
    body.update(default_stat_scope="nadie")
    assert client.put(f"/api/events/{ev.id}/field-configs/entity", json=body).status_code == 400
    body.update(default_stat_scope="all")
    client.put(f"/api/events/{ev.id}/field-configs/entity", json=body)
    db.expire_all()
    assert db.query(EventFieldConfig).filter_by(event_id=ev.id, field_key="entity").one().default_chart_type == "bar"      # «toda la base» sin sufijo


def test_split_and_join_chart_scope():
    assert parametros.split_chart_scope(None) == (None, "all")
    assert parametros.split_chart_scope("pie") == ("pie", "all")
    assert parametros.split_chart_scope("bar@unregistered") == ("bar", "unregistered")
    assert parametros.split_chart_scope("bar@raro") == ("bar", "all")
    assert parametros.join_chart_scope("bar", "all") == "bar" and parametros.join_chart_scope("bar", "registered") == "bar@registered"
    assert parametros.join_chart_scope(None, "registered") is None


def test_public_link_accepts_scope_too():
    src = open("app/routers/stats_links.py", encoding="utf-8").read()
    assert 'scope: str = "all"' in src and "data_for(db, event, variable, scope=scope)" in src
