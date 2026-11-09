"""Fase 6: arrendamiento de un evento por un servidor local (la nube lo muestra en solo lectura hasta que vuelva a internet)."""
import pathlib

import pytest
from fastapi import HTTPException

from app import event_lease
from app.models import AuditAction, Event
from tests.conftest import login

SRC = pathlib.Path(__file__).resolve().parent.parent


def test_pure_helpers_clean_name_and_assert_editable():
    assert event_lease.clean_node_name("  Portátil   bodega 1 ") == "Portátil bodega 1"
    with pytest.raises(HTTPException) as e:
        event_lease.clean_node_name("   ")
    assert e.value.status_code == 400
    ev = Event(name="X")
    event_lease.assert_editable(ev)                           # en la nube: editable
    event_lease.take(ev, "Portátil 1", 7)
    with pytest.raises(HTTPException) as e:
        event_lease.assert_editable(ev)
    assert e.value.status_code == 423 and "Portátil 1" in e.value.detail and "aún no ha subido" in e.value.detail
    event_lease.take(ev, "Portátil 1", 7)                     # el mismo servidor: idempotente
    with pytest.raises(HTTPException) as e:
        event_lease.take(ev, "Otro", 7)
    assert e.value.status_code == 409
    event_lease.mark_uploaded(ev)
    assert "última subida" in event_lease.message(ev)
    event_lease.release(ev)
    assert not event_lease.is_leased(ev) and ev.local_since is None and ev.local_by_id is None


def test_migration_0111():
    src = (SRC / "alembic" / "versions" / "0111_event_lease.py").read_text(encoding="utf-8")
    assert 'revision = "0111_event_lease"' in src and len("0111_event_lease") <= 32 and 'down_revision = "0110_notifications"' in src
    for col in ("local_node_name", "local_since", "local_by_id", "local_last_upload_at"):
        assert col in src


@pytest.mark.parametrize("role,allowed", [("coordinador", True), ("comercial", True), ("admin", True), ("almacen", True), ("contabilidad", True), ("digitador", False), ("cliente", False)])
def test_who_can_take_a_lease_on_any_event(client, factory, db, role, allowed):
    factory.staff(role, "u1")
    other = factory.staff("coordinador", "otra")
    ev = factory.event("en_proceso", coordinator=other)          # un evento que NO es suyo
    ev_id = ev.id
    login(client, "u1")
    r = client.post(f"/api/events/{ev_id}/lease", json={"node_name": "Portátil 1"})
    assert (r.status_code == 200) is allowed, r.text


def test_leased_event_is_read_only_in_the_cloud_and_release_restores_it(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    ev_id = ev.id
    login(client, "coord")
    assert client.post(f"/api/events/{ev_id}/lease", json={"node_name": "Portátil 1"}).json()["leased"] is True
    assert client.post(f"/api/events/{ev_id}/lease", json={"node_name": "Otro"}).status_code == 409
    r = client.patch(f"/api/events/{ev_id}", json={"name": "Nuevo nombre"})
    assert r.status_code == 423 and "Portátil 1" in r.json()["detail"]
    listed = [e for e in client.get("/api/events").json() if e["id"] == ev_id][0]
    assert listed["local"]["leased"] is True and listed["local"]["node_name"] == "Portátil 1"
    assert client.post(f"/api/events/{ev_id}/lease/uploaded").json()["last_upload_at"]
    assert client.post(f"/api/events/{ev_id}/lease/release").json()["leased"] is False
    assert client.patch(f"/api/events/{ev_id}", json={"name": "Nuevo nombre"}).status_code == 200
    db.expire_all()
    assert {a.action for a in db.query(AuditAction).filter(AuditAction.entity == "event").all()} >= {"lease_local", "lease_release"}


def test_uploaded_requires_a_lease(client, factory, db):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    ev_id = ev.id
    login(client, "coord")
    assert client.post(f"/api/events/{ev_id}/lease/uploaded").status_code == 409
