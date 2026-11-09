"""Fase 5 · notificaciones (campana + correo) y avisos del inventario (9-nov-2026): anticipación (1 día misma ciudad / 1 semana otra), falta de material y existencias. NUNCA bloquean."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import inventory_alerts as ia
from app import jobs, notifications
from app.models import EventInventoryItem, InventoryProduct, Notification
from app.timeutil import utcnow
from tests.conftest import login

SRC = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 9)


# ------------------------------------------------------------------ parte pura
def test_lead_rule_same_city_needs_one_day_and_other_city_one_week():
    assert ia.lead_warning(TODAY + timedelta(days=1), TODAY, True) is None
    assert "1 día de anticipación" in ia.lead_warning(TODAY, TODAY, True) and "empieza hoy" in ia.lead_warning(TODAY, TODAY, True)
    assert ia.lead_warning(TODAY + timedelta(days=7), TODAY, False) is None
    msg = ia.lead_warning(TODAY + timedelta(days=3), TODAY, False)
    assert "1 semana" in msg and "3 días" in msg
    assert ia.lead_warning(None, TODAY, False) is None


def test_same_city_ignores_accents_case_and_unknown_city():
    assert ia.same_city("bogota", "Bogotá") and ia.same_city("  BOGOTÁ ", "Bogotá") and ia.same_city(None, "Bogotá") and not ia.same_city("Cali", "Bogotá")


def test_shortage_and_overlap():
    assert ia.shortage(None, 50, 50) == 0 and ia.shortage(10, 4, 6) == 0 and ia.shortage(10, 6, 6) == 2
    d = date
    assert ia._overlaps(d(2026, 12, 1), d(2026, 12, 3), d(2026, 12, 3), None) and not ia._overlaps(d(2026, 12, 1), d(2026, 12, 2), d(2026, 12, 3), d(2026, 12, 4)) and not ia._overlaps(None, None, d(2026, 12, 3), None)


# ------------------------------------------------------------------ con base de datos
@pytest.fixture
def mails(monkeypatch):
    sent = []

    def fake(to, subject, body, attachments=None, html=None, reply_to=None):
        sent.append({"to": to, "subject": subject, "body": body})
        return {"sent": True, "detail": "prueba"}

    monkeypatch.setattr("app.notifications.send_mail", fake)
    return sent


def _world(factory, db, total=None):
    factory.staff("super_admin", "sup")
    factory.staff("almacen", "alm", email="alm@ejemplo.com")
    com = factory.staff("comercial", "com", email="com@ejemplo.com")
    prod = InventoryProduct(name="Carpa 3x3", unit="unidad", qty_total=total)
    db.add(prod)
    db.commit()
    return prod, com


def _plan(client, ev_id, prod_id, qty):
    return client.put(f"/api/events/{ev_id}/inventory-plan", json={"lines": [{"product_id": prod_id, "assigned": qty}]})


def _soon(days):
    return utcnow().date() + timedelta(days=days)


def test_late_reservation_warns_by_bell_and_email_but_never_blocks(client, factory, db, mails):
    prod, com = _world(factory, db)
    ev = factory.event("creado", commercial=com, start_date=_soon(0), city="Bogotá")
    login(client, "sup")
    r = _plan(client, ev.id, prod.id, 3)
    assert r.status_code == 200 and any("1 día de anticipación" in w for w in r.json()["warnings"])          # avisa, no bloquea
    jobs.drain()
    db.expire_all()
    rows = db.query(Notification).filter(Notification.event_id == ev.id).all()
    assert len(rows) == 2 and all(n.kind == "inventory_lead" and n.read_at is None for n in rows)          # almacén y la comercial; no quien hizo el cambio
    assert sorted(m["to"] for m in mails) == ["alm@ejemplo.com", "com@ejemplo.com"]
    assert db.query(EventInventoryItem).filter(EventInventoryItem.event_id == ev.id).one().qty_assigned == 3
    _plan(client, ev.id, prod.id, 4)          # mismo aviso: no se repite
    db.expire_all()
    assert db.query(Notification).filter(Notification.event_id == ev.id).count() == 2


def test_other_city_needs_a_week(client, factory, db, mails):
    prod, com = _world(factory, db)
    ev = factory.event("creado", commercial=com, start_date=_soon(3), city="Cali")
    ok = factory.event("creado", commercial=com, start_date=_soon(8), city="Cali")
    login(client, "sup")
    assert any("1 semana" in w for w in _plan(client, ev.id, prod.id, 1).json()["warnings"])
    assert _plan(client, ok.id, prod.id, 1).json()["warnings"] == []
    same = factory.event("creado", commercial=com, start_date=_soon(1), city="Bogotá")
    assert _plan(client, same.id, prod.id, 1).json()["warnings"] == []


def test_not_enough_stock_warns_to_rent_and_never_blocks(client, factory, db, mails):
    prod, com = _world(factory, db, total=10)
    a = factory.event("creado", commercial=com, start_date=_soon(20), end_date=_soon(22), city="Bogotá")
    b = factory.event("creado", commercial=com, start_date=_soon(21), end_date=_soon(23), city="Bogotá")
    far = factory.event("creado", commercial=com, start_date=_soon(40), end_date=_soon(41), city="Bogotá")
    login(client, "sup")
    assert _plan(client, a.id, prod.id, 6).json()["warnings"] == []
    r = _plan(client, b.id, prod.id, 6)
    assert r.status_code == 200 and any("faltan 2" in w and "alquilar" in w for w in r.json()["warnings"])
    assert _plan(client, far.id, prod.id, 9).json()["warnings"] == []          # fechas que no se cruzan: alcanza
    jobs.drain()
    db.expire_all()
    assert db.query(Notification).filter(Notification.kind == "inventory_stock", Notification.event_id == b.id).count() == 2
    finished = factory.event("finalizado", start_date=_soon(21), city="Bogotá")
    assert ia.warnings_for_event(db, finished) == []


def test_stock_is_set_and_cleared_from_the_catalog(client, factory, db):
    factory.staff("super_admin", "sup")
    login(client, "sup")
    p = client.post("/api/inventory/products", json={"name": "Silla", "unit": "unidad", "stock": 40}).json()
    assert p["stock"] == 40
    assert client.patch(f"/api/inventory/products/{p['id']}", json={"stock": ""}).json()["stock"] is None
    assert client.patch(f"/api/inventory/products/{p['id']}", json={"stock": -3}).status_code == 400


def test_bell_api_shows_only_my_notifications(client, factory, db):
    a, b = factory.staff("coordinador", "ana"), factory.staff("coordinador", "beto")
    db.add_all([Notification(staff_user_id=a.id, kind="x", title="Para Ana", created_at=utcnow()), Notification(staff_user_id=b.id, kind="x", title="Para Beto", created_at=utcnow())])
    db.commit()
    mine = db.query(Notification).filter(Notification.staff_user_id == a.id).one()
    theirs = db.query(Notification).filter(Notification.staff_user_id == b.id).one()
    login(client, "ana")
    d = client.get("/api/notifications").json()
    assert d["unread"] == 1 and [i["title"] for i in d["items"]] == ["Para Ana"]
    assert client.post(f"/api/notifications/{theirs.id}/read").status_code == 404          # no se leen las de otro
    assert client.post(f"/api/notifications/{mine.id}/read").json()["unread"] == 0
    assert client.get("/api/notifications?unread=1").json()["items"] == []
    assert client.post("/api/notifications/read-all").json()["unread"] == 0
    client.post("/logout")
    assert client.get("/api/notifications").status_code == 401


def test_notify_dedupes_and_mail_skips_people_without_email(factory, db, mails):
    with_mail, without = factory.staff("comercial", "c1", email="c1@ejemplo.com"), factory.staff("comercial", "c2")
    n = notifications.notify(db, [with_mail.id, without.id, with_mail.id], kind="t", title="Hola", body="Cuerpo", dedupe_key="k1")
    db.commit()
    assert n == 2 and notifications.notify(db, [with_mail.id], kind="t", title="Hola", dedupe_key="k1") == 0
    db.commit()
    jobs.drain()
    assert [m["to"] for m in mails] == ["c1@ejemplo.com"]


def test_job_and_migration_are_declared():
    assert notifications.KIND in jobs.GENERAL_KINDS and jobs.HANDLER_MODULES[notifications.KIND] == "app.notifications"
    assert '@jobs.handler("notification_mail")' in (SRC / "app" / "notifications.py").read_text(encoding="utf-8")
    src = (SRC / "alembic" / "versions" / "0110_notifications.py").read_text(encoding="utf-8")
    assert 'revision = "0110_notifications"' in src and len("0110_notifications") <= 32 and 'down_revision = "0109_inventory_unify"' in src and "qty_total" in src
