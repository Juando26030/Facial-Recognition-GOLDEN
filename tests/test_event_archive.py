"""Fase 3, oleada 2 (7-nov-2026): archivar eventos finalizados (admin+), restaurar, ocultarlos de listas/calendario, dejarlos de solo lectura (sin registro ni formularios públicos),
y borrado definitivo solo de super_admin sobre un evento ya archivado. Todo deja rastro en audit_actions."""
import inspect
from datetime import date, timedelta

import pytest

from app.models import AuditAction, Event, WebForm
from tests.conftest import login


def _finished(factory, db, **kw):
    ev = factory.event("en_proceso", **kw)
    ev.status = "finalizado"
    db.commit()
    return ev


def _ids(client, url="/api/events", **params):
    return {e["id"] for e in client.get(url, params=params).json()}


def test_sources_guard_roles():
    from app.routers import events
    assert 'require_role("admin")' in inspect.getsource(events.archive_event)
    assert 'require_role("admin")' in inspect.getsource(events.restore_event)
    assert 'require_role("super_admin")' in inspect.getsource(events.delete_event)


def test_only_finished_events_can_be_archived(client, factory, db):
    factory.staff("admin", "adm")
    login(client, "adm")
    for status in ("creado", "en_proceso"):
        ev = factory.event(status)
        r = client.post(f"/api/events/{ev.id}/archive")
        assert r.status_code == 400 and "finalizados" in r.json()["detail"]
    ev = _finished(factory, db)
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 400            # ya archivado


@pytest.mark.parametrize("role", ["coordinador", "comercial"])
def test_below_admin_cannot_archive_restore_or_list_archived(client, factory, db, role):
    ev = _finished(factory, db)
    factory.staff(role, "actor")
    login(client, "actor")
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 403
    assert client.post(f"/api/events/{ev.id}/restore").status_code == 403
    assert client.get("/api/events", params={"include_archived": "true"}).status_code == 403
    assert client.get("/api/events/search", params={"include_archived": "true"}).status_code == 403


def test_archived_event_is_hidden_everywhere_by_default_and_admin_sees_it_on_request(client, factory, db):
    ev = _finished(factory, db, start_date=date.today(), end_date=date.today())
    keep = factory.event("creado", start_date=date.today(), end_date=date.today())
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200
    assert _ids(client) == {keep.id}
    assert _ids(client, "/api/events/search") == {keep.id}
    assert _ids(client, "/api/events", tenant_id="acme") == {keep.id}
    cal = client.get("/api/events/calendar", params={"start": str(date.today() - timedelta(days=1)), "end": str(date.today() + timedelta(days=1))}).json()
    assert {e["id"] for e in cal} == {keep.id}
    assert _ids(client, include_archived="true") == {ev.id, keep.id}
    flagged = {e["id"]: e["archived"] for e in client.get("/api/events", params={"include_archived": "true"}).json()}
    assert flagged == {ev.id: True, keep.id: False}
    assert client.post(f"/api/events/{ev.id}/restore").status_code == 200
    assert _ids(client) == {ev.id, keep.id}


def test_archive_keeps_the_data_and_logs_it_without_personal_data(client, factory, db):
    from app.models import EventAttendee
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    ev.status = "finalizado"
    db.commit()
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200
    assert client.post(f"/api/events/{ev.id}/restore").status_code == 200
    db.expire_all()
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 1
    rows = db.query(AuditAction).order_by(AuditAction.id).all()
    assert [(r.action, r.entity, r.entity_id, r.actor_role) for r in rows] == [("archive", "event", str(ev.id), "admin"), ("restore", "event", str(ev.id), "admin")]
    assert "Ana" not in " ".join(str(r.detail) + str(r.entity_name) for r in rows)


def test_archived_event_cannot_be_edited_or_reopened_until_restored(client, factory, db):
    ev = _finished(factory, db)
    factory.staff("admin", "adm")
    login(client, "adm")
    client.post(f"/api/events/{ev.id}/archive")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso"}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}", json={"notes": "x"}).status_code == 400
    client.post(f"/api/events/{ev.id}/restore")
    assert client.patch(f"/api/events/{ev.id}", json={"notes": "x"}).status_code == 200


def test_archived_event_blocks_registration_even_with_a_state_that_allows_it(db, factory):
    import json

    from app import event_rules
    from app.models import EventState
    ev = _finished(factory, db)
    st = EventState(name="Abierto", base_status="finalizado", is_active=True, position=1, rules_json=json.dumps({"registration": True, "client_access": True}))
    db.add(st)
    db.commit()
    ev.state_id = st.id
    db.commit()
    assert event_rules.allowed(ev, "registration") is True and event_rules.allowed(ev, "client_access") is True            # sin archivar, el estado configurable manda
    ev.archived_at = ev.finalized_at
    assert not any(event_rules.effective_rules(ev)[k] for k in event_rules.ARCHIVED_OFF)


def test_kiosk_recognition_gate_refuses_archived_event(db, factory):
    from fastapi import HTTPException

    from app.auth import require_event_in_progress
    ev = factory.event("en_proceso")
    require_event_in_progress(ev)                                  # abierto: pasa
    ev.archived_at = ev.created_at
    with pytest.raises(HTTPException) as exc:
        require_event_in_progress(ev)
    assert exc.value.status_code == 403


def test_archive_closes_public_forms_and_they_cannot_be_reopened_while_archived(client, factory, db):
    from tests.test_forms import _create, _event, _open
    ev = _event(client, factory)
    form = _create(client, ev)
    _open(client, ev, form)
    client.post("/logout")
    assert db.query(WebForm).one().manual_status == "activo"
    factory.staff("admin", "adm")
    login(client, "adm")
    ev.status = "finalizado"
    db.commit()
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200
    db.expire_all()
    f = db.query(WebForm).one()
    assert f.manual_status == "finalizado" and f.use_schedule is False
    r = client.put(f"/api/events/{ev.id}/forms/{form['id']}/status", json={"manual_status": "activo"})
    assert r.status_code == 400
    client.post("/logout")
    assert client.get(f"/f/{ev.id}/{form['slug']}").status_code == 404            # el público ya no lo ve


def test_hard_delete_needs_super_admin_and_an_archived_event_and_is_logged(client, factory, db):
    ev = _finished(factory, db)
    keep = _finished(factory, db)
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    client.post(f"/api/events/{ev.id}/archive")
    assert client.delete(f"/api/events/{ev.id}").status_code == 403            # admin ya no borra
    login(client, "sup")
    assert client.delete(f"/api/events/{keep.id}").status_code == 400            # sin archivar no se borra
    assert client.delete(f"/api/events/{ev.id}").status_code == 200
    db.expire_all()
    assert db.query(Event).filter_by(id=ev.id).first() is None and db.query(Event).filter_by(id=keep.id).first() is not None
    row = db.query(AuditAction).filter_by(action="delete").one()
    assert row.entity == "event" and row.entity_id == str(ev.id) and row.actor_role == "super_admin"


def test_auto_archived_event_is_restored_only_by_super_admin(client, factory, db):
    from app import event_archive
    ev = _finished(factory, db)
    from app.timeutil import utcnow
    ev.finalized_at = utcnow() - timedelta(days=100)
    db.commit()
    assert event_archive.auto_archive_due(db)["archived"] == 1
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    assert client.post(f"/api/events/{ev.id}/restore").status_code == 403
    assert client.get("/api/events", params={"include_archived": "true"}).json()[0]["archived_auto"] is True
    login(client, "sup")
    assert client.post(f"/api/events/{ev.id}/restore").status_code == 200
