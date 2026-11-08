"""Fase 3 (7-nov-2026): super eventos. Editar/archivar/restaurar coordinador+ (con alcance por cliente); borrado definitivo solo super_admin, de uno archivado y sin eventos; todo en audit_actions.
Archivar NO toca los eventos ni la asistencia hermana."""
import inspect

import pytest

from app.models import AccessLog, AuditAction, Event, SuperEvent
from tests.conftest import login


def _mk(client, name="Congreso", tenant="acme"):
    r = client.post("/api/super-events", json={"tenant_id": tenant, "name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ids(client, tenant="acme", **params):
    return {s["id"] for s in client.get("/api/super-events", params={"tenant_id": tenant, **params}).json()}


def test_sources_guard_roles():
    from app.routers import super_events as m
    for fn in (m.update_super_event, m.archive_super_event, m.restore_super_event):
        assert 'require_role("coordinador")' in inspect.getsource(fn)
        assert "assert_same_tenant(" in inspect.getsource(m._super_or_404)
    assert 'require_role("super_admin")' in inspect.getsource(m.delete_super_event)


def test_models_boot_with_explicit_columns():
    from sqlalchemy.orm import configure_mappers
    configure_mappers()
    assert "archived_at" in SuperEvent.__table__.c and "archived_by_id" in SuperEvent.__table__.c


@pytest.mark.parametrize("role", ["coordinador", "comercial", "admin", "super_admin"])
def test_coordinator_plus_edits_archives_restores(client, factory, role):
    factory.tenant("acme")
    factory.staff(role, "actor")
    login(client, "actor")
    sid = _mk(client)
    r = client.patch(f"/api/super-events/{sid}", json={"name": "  Congreso 2027 "})
    assert r.status_code == 200 and r.json()["name"] == "Congreso 2027"
    assert client.post(f"/api/super-events/{sid}/archive").status_code == 200
    assert sid not in _ids(client)
    assert sid in _ids(client, include_archived="true")
    assert client.post(f"/api/super-events/{sid}/restore").status_code == 200
    assert sid in _ids(client)


@pytest.mark.parametrize("role", ["digitador", "cliente"])
def test_digitador_and_cliente_cannot(client, factory, db, role):
    factory.tenant("acme")
    sup = SuperEvent(tenant_id="acme", name="X")
    db.add(sup)
    db.commit()
    factory.staff(role, "actor")
    login(client, "actor")
    assert client.patch(f"/api/super-events/{sup.id}", json={"name": "Y"}).status_code == 403
    assert client.post(f"/api/super-events/{sup.id}/archive").status_code == 403
    assert client.post(f"/api/super-events/{sup.id}/restore").status_code == 403
    assert client.get("/api/super-events", params={"tenant_id": "acme", "include_archived": "true"}).status_code == 403


def test_edit_rules(client, factory):
    factory.tenant("acme")
    factory.staff("coordinador", "coord")
    login(client, "coord")
    a, b = _mk(client, "A"), _mk(client, "B")
    assert client.patch(f"/api/super-events/{a}", json={"name": "   "}).status_code == 400
    assert client.patch(f"/api/super-events/{a}", json={"name": "B"}).status_code == 400          # nombre repetido
    assert client.patch(f"/api/super-events/{a}", json={"tenant_id": "otro"}).status_code == 400          # el cliente no cambia
    assert client.patch(f"/api/super-events/{a}", json={"tenant_id": "acme", "name": "A2"}).status_code == 200
    client.post(f"/api/super-events/{b}/archive")
    assert client.patch(f"/api/super-events/{b}", json={"name": "B2"}).status_code == 400          # archivado no se edita
    assert client.post(f"/api/super-events/{b}/archive").status_code == 400
    assert client.post(f"/api/super-events/{a}/restore").status_code == 400
    assert client.patch("/api/super-events/9999", json={"name": "Z"}).status_code == 404


def test_tenant_scope_blocks_other_client(client, factory, db):
    factory.tenant("acme")
    factory.tenant("otro")
    sup = SuperEvent(tenant_id="otro", name="Ajeno")
    db.add(sup)
    db.commit()
    coord = factory.staff("coordinador", "coord", tenant_id="acme")
    login(client, "coord")
    from app import tenant_scope
    if not tenant_scope.staff_tenant_enforced(coord):
        pytest.skip("ENFORCE_STAFF_TENANT apagado: el alcance por cliente no se aplica en este entorno")
    assert client.patch(f"/api/super-events/{sup.id}", json={"name": "X"}).status_code in (403, 404)
    assert client.post(f"/api/super-events/{sup.id}/archive").status_code in (403, 404)


def test_archive_keeps_events_and_sibling_attendance(client, factory, db):
    from app.routers.super_events import sibling_attendance
    factory.staff("coordinador", "coord")
    login(client, "coord")
    e1 = factory.event(tenant_id="acme")
    e2 = factory.event(tenant_id="acme")
    sid = _mk(client)
    e1.super_event_id = e2.super_event_id = sid
    factory.person(e1, "1001")
    db.add(AccessLog(event_id=e1.id, tenant_id="acme", user_id="1001", record_type="Existente", registration_method="tradicional"))
    db.commit()
    assert client.post(f"/api/super-events/{sid}/archive").status_code == 200
    db.expire_all()
    assert db.query(Event).filter_by(id=e1.id).one().super_event_id == sid          # los eventos no se tocan
    assert db.query(Event).filter_by(id=e1.id).one().archived_at is None
    assert [s["event_id"] for s in sibling_attendance(db, db.query(Event).filter_by(id=e2.id).one(), "1001")] == [e1.id]          # la asistencia hermana sigue contando


def test_archived_super_event_not_assignable_to_events_but_kept_if_already_set(client, factory, db):
    factory.staff("coordinador", "coord")
    login(client, "coord")
    ev = factory.event(tenant_id="acme")
    s_old, s_new = _mk(client, "Viejo"), _mk(client, "Nuevo")
    client.patch(f"/api/events/{ev.id}", json={"super_event_id": s_old})
    client.post(f"/api/super-events/{s_old}/archive")
    client.post(f"/api/super-events/{s_new}/archive")
    assert client.patch(f"/api/events/{ev.id}", json={"super_event_id": s_new}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}", json={"super_event_id": s_old}).status_code == 200          # conservar el actual no estorba


def test_hard_delete_rules(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    ev = factory.event(tenant_id="acme")
    login(client, "adm")
    vacio, conev = _mk(client, "Vacio"), _mk(client, "ConEventos")
    ev.super_event_id = conev
    db.commit()
    assert client.delete(f"/api/super-events/{vacio}").status_code == 403
    login(client, "sup")
    assert client.delete(f"/api/super-events/{vacio}").status_code == 400          # primero archivar
    client.post(f"/api/super-events/{vacio}/archive")
    client.post(f"/api/super-events/{conev}/archive")
    r = client.delete(f"/api/super-events/{conev}")
    assert r.status_code == 400 and "eventos asociados" in r.json()["detail"]
    assert client.delete(f"/api/super-events/{vacio}").status_code == 200
    db.expire_all()
    assert db.query(SuperEvent).filter_by(id=vacio).first() is None
    assert db.query(SuperEvent).filter_by(id=conev).first() is not None


def test_actions_are_logged(client, factory, db):
    factory.staff("super_admin", "sup")
    login(client, "sup")
    sid = _mk(client)
    client.patch(f"/api/super-events/{sid}", json={"name": "Nuevo nombre"})
    client.post(f"/api/super-events/{sid}/archive")
    client.post(f"/api/super-events/{sid}/restore")
    client.post(f"/api/super-events/{sid}/archive")
    client.delete(f"/api/super-events/{sid}")
    db.expire_all()
    rows = db.query(AuditAction).filter_by(entity="super_event").order_by(AuditAction.id).all()
    assert [r.action for r in rows] == ["edit", "archive", "restore", "archive", "delete"]
    assert all(r.entity_id == str(sid) and r.actor_role == "super_admin" for r in rows)
    assert "Nuevo nombre" not in " ".join(str(r.detail) for r in rows)
