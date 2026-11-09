"""Cierre de seguridad «P» (6-nov-2026): autorización, IDOR y aislamiento.

P1/P4 cuentas del personal fuera de alcance · P3 sincronización sin red · P5 recortes por cliente · P6 persona de otro evento · P7 comercial y digitadores ·
P8 coordinador al editar el evento · P9 «Registros por operador» para el cliente. Las pruebas de fuente corren sin base; las demás usan la base de pruebas."""
import inspect
import pathlib
from datetime import date

from app.models import AccessLog, Event, EventAttendee, User
from tests.conftest import login

SRC = pathlib.Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _body(module, name: str) -> str:
    return inspect.getsource(getattr(module, name))


# ------------------------------------------------------------------------------------------------ de fuente (sin base)
def test_staff_management_endpoints_use_the_reach_check():
    from app.routers import staff
    for fn in ("reset_staff_password", "delete_staff", "change_staff_role", "assign_secondary_role", "set_staff_roles", "edit_staff_profile", "deactivate_staff", "activate_staff"):
        assert "_assert_can_manage(db, staff, target)" in _body(staff, fn), fn
    for fn in ("list_staff", "list_assignable_staff"):
        assert "staff_tenant_enforced(staff)" in _body(staff, fn), fn


def test_sync_helper_and_status_changes_check_tenant_and_scope():
    from app.routers import api, events
    body = _body(api, "_event_for_sync")
    assert "assert_event_tenant(event, staff)" in body and "assert_event_scope(event, staff, db)" in body
    body = _body(events, "list_status_changes")
    assert "assert_event_tenant(event, staff)" in body and "assert_event_scope(event, staff, db)" in body


def test_tenant_cuts_in_lists_and_writes():
    from app.routers import calendar, events, super_events, tenants
    assert "scope_events_query(query, staff)" in _body(calendar, "calendar_events")
    assert "staff_tenant_enforced(staff)" in _body(tenants, "list_tenants")
    assert "assert_same_tenant(staff, tenant.id" in _body(tenants, "update_tenant")
    assert "assert_same_tenant(staff, tenant_id" in _body(super_events, "list_super_events")
    assert "assert_same_tenant(staff, tenant_id" in _body(super_events, "create_super_event")
    assert "assert_same_tenant(staff, data.tenant_id" in _body(events, "create_event")
    assert "assert_same_tenant(staff, target.tenant_id" in _body(events, "assign_existing_staff")


def test_person_edits_require_a_person_of_this_event():
    from app.routers import api
    assert "_person_of_event(db, event, user_id)" in _body(api, "update_user")
    assert "_person_of_event(db, event, user_id)" in _body(api, "update_registration_status")
    assert "_clean_extra_fields(extra_fields)" in _body(api, "update_user")


def test_clean_extra_fields_keeps_only_optional_text():
    import pytest
    from fastapi import HTTPException
    from app.routers.api import _clean_extra_fields
    assert _clean_extra_fields({"opcional_1": " cali ", "opcional_2": 3, "opcional_3": None, "role": "x", "__proto__": "y"}) == {"opcional_1": " cali ", "opcional_2": "3", "opcional_3": ""}
    for bad in ({"opcional_1": {"a": 1}}, {"opcional_1": ["a"]}, {"opcional_1": True}, ["opcional_1"]):
        with pytest.raises(HTTPException):
            _clean_extra_fields(bad)


def test_revoke_excludes_pure_commercial_and_patch_validates_coordinator():
    from app.routers import events
    assert "_can_manage_temp(staff)" in _body(events, "revoke_event_staff")
    body = _body(events, "update_event")
    assert "data.coordinator_staff_id" in body and "El coordinador asignado no es válido" in body


def test_operator_chart_only_for_staff_and_never_the_username():
    from app.routers import analytics
    body = _body(analytics, "registro_dashboard")
    assert "with_operators" in body and "s.full_name or s.username" not in body and "Digitador {n}" in body
    assert "with_operators=staff_view" in _body(analytics, "analytics_registro")
    assert "registro_dashboard(db, event)" in _src("app/routers/stats_links.py")          # el enlace público sigue sin operadores (valor por defecto)


# ------------------------------------------------------------------------------------------------ con base de pruebas
def test_p1_coordinator_cannot_take_or_delete_a_door_account_of_an_event_out_of_scope(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    mine_coord = factory.staff("coordinador", "coordA")
    other_coord = factory.staff("coordinador", "coordB")
    mine = factory.event("en_proceso", coordinator=mine_coord)
    other = factory.event("en_proceso", coordinator=other_coord)
    digi_mine = factory.staff("digitador", "7000001")
    digi_other = factory.staff("digitador", "7000002")
    factory.authorize(mine, digi_mine)
    factory.authorize(other, digi_other)
    login(client, "coordA")
    assert client.put(f"/api/staff/{digi_other.id}/password", json={"use_username": True}).status_code == 404
    assert client.post(f"/api/staff/{digi_other.id}/archive").status_code == 403          # Fase 3: archivar / borrar definitivo son de admin+ / super_admin
    assert client.delete(f"/api/staff/{digi_other.id}").status_code == 403
    assert client.put(f"/api/staff/{digi_mine.id}/password", json={"use_username": True}).status_code == 200          # el suyo sí


def test_p1_without_the_switches_nothing_changes(client, factory):
    factory.staff("coordinador", "coordA")
    ev = factory.event("en_proceso")
    digi = factory.staff("digitador", "7000003")
    factory.authorize(ev, digi)
    login(client, "coordA")
    assert client.put(f"/api/staff/{digi.id}/password", json={"use_username": True}).status_code == 200


def test_p4_admin_of_a_client_does_not_manage_accounts_of_another_client(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("acme")
    factory.tenant("beta")
    factory.staff("admin", "adminB", tenant_id="beta")
    foreign = factory.staff("coordinador", "coordAcme", tenant_id="acme")
    own = factory.staff("coordinador", "coordBeta", tenant_id="beta")
    login(client, "adminB")
    assert client.put(f"/api/staff/{foreign.id}/password", json={"new_password": "Otra-Clave-Larga-2026!", "must_change": False}).status_code == 404
    assert client.patch(f"/api/staff/{foreign.id}/deactivate").status_code == 404
    assert client.patch(f"/api/staff/{foreign.id}/role", json={"role": "comercial"}).status_code == 404
    ids = {s["id"] for s in client.get("/api/staff").json()}
    assert own.id in ids and foreign.id not in ids


def test_p3_sync_rejects_an_event_of_another_client(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("beta")
    factory.staff("coordinador", "coordB", tenant_id="beta")
    ev_acme = factory.event("en_proceso", tenant_id="acme")
    login(client, "coordB")
    r = client.post(f"/api/events/{ev_acme.id}/outbox/sync", json={"ops": [{"op_id": "x1", "type": "create_person", "fields": {"id": "123", "first_name": "A", "last_name": "B"}}]})
    assert r.status_code == 404
    r = client.post(f"/api/events/{ev_acme.id}/access-logs/sync", json={"records": [{"client_id": "c1", "cedula": "123"}]})
    assert r.status_code == 404


def test_p5_calendar_and_tenants_are_cut_by_client(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("beta")
    factory.staff("coordinador", "coordB", tenant_id="beta")
    factory.staff("comercial", "comB", tenant_id="beta")
    acme = factory.event("en_proceso", tenant_id="acme", start_date=date(2026, 11, 10), end_date=date(2026, 11, 11))
    login(client, "coordB")
    cal = client.get("/api/events/calendar", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert acme.id not in {e["id"] for e in cal}
    assert {t["id"] for t in client.get("/api/tenants").json()} == {"beta"}
    assert client.patch("/api/tenants/acme", json={"contact_email": "x@beta.com"}).status_code == 403      # coordinador no edita clientes (comercial+)
    assert client.get("/api/super-events", params={"tenant_id": "acme"}).status_code == 404
    client.post("/logout")
    login(client, "comB")
    assert client.patch("/api/tenants/acme", json={"contact_email": "x@beta.com"}).status_code == 404      # comercial de otro cliente: no lo ve


def test_p6_edit_and_status_only_for_people_of_this_event(client, factory, db):
    digi = factory.staff("digitador", "7000004")
    ev_a = factory.event("en_proceso")
    ev_b = factory.event("en_proceso")
    factory.authorize(ev_a, digi)
    factory.person(ev_b, "5001", "Solo", "EnB")          # mismo cliente, solo en el evento B
    factory.person(ev_a, "5002", "Si", "EnA")
    login(client, "7000004")
    r = client.patch(f"/api/users/5001?event_id={ev_a.id}", json={"email": "otro@example.com"})
    assert r.json() == {"error": "Usuario no encontrado"}
    assert client.patch(f"/api/events/{ev_a.id}/users/5001/status", json={"status": "registrado"}).status_code == 404
    db.expire_all()
    assert db.query(EventAttendee).filter_by(event_id=ev_a.id, user_id="5001").first() is None
    assert db.query(AccessLog).filter_by(event_id=ev_a.id, user_id="5001").first() is None
    assert db.query(User).filter_by(id="5001").one().email is None
    assert client.patch(f"/api/users/5002?event_id={ev_a.id}", json={"role": "Ingeniera"}).status_code == 200          # la de este evento, sí
    assert client.patch(f"/api/users/5002?event_id={ev_a.id}", json={"extra_fields": {"opcional_1": {"x": 1}}}).status_code == 400


def test_p7_pure_commercial_cannot_revoke_a_door_account(client, factory):
    factory.staff("comercial", "com1")
    ev = factory.event("en_proceso")
    digi = factory.staff("digitador", "7000005")
    factory.authorize(ev, digi)
    login(client, "com1")
    assert client.delete(f"/api/events/{ev.id}/staff-users/{digi.id}").status_code == 403


def test_p8_patch_event_rejects_a_non_coordinator(client, factory, db):
    factory.staff("coordinador", "coordA")
    ev = factory.event("creado")
    digi = factory.staff("digitador", "7000006")
    login(client, "coordA")
    assert client.patch(f"/api/events/{ev.id}", json={"coordinator_staff_id": digi.id}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}", json={"coordinator_staff_id": 999999}).status_code == 400
    db.expire_all()
    assert db.get(Event, ev.id).coordinator_staff_id is None
