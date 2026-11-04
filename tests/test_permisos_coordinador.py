"""Fase 1A · permisos de coordinador (DECISIÓN DEL DUEÑO, 2026-11-04).

super_admin, admin y TODOS los coordinadores pueden configurar cualquier evento (Parámetros del evento y carga de base: `/api/bulk_roster`, `/api/bulk_roster/preview`, `/api/bulk_register`) y
acceden a TODOS los eventos, sean o no los coordinadores/comercial/creadores. Comercial (puro), digitador y cliente NO configuran. Esto es así porque `ENFORCE_STAFF_EVENT_SCOPE` (candado de
seguridad 0C, A6/A7: pertenencia al evento) queda APAGADO por defecto por decisión del dueño; estas pruebas fijan ese comportamiento para que nadie lo cambie sin darse cuenta.
Los bloqueos por estado del evento (finalizado nunca; en proceso con la base ya cargada) NO cambian y no se prueban aquí."""
import pytest

from tests.conftest import login

PARAM_URLS = ("/api/events/{id}/field-configs", "/api/events/{id}/categories")


def _setup(factory):
    owner = factory.staff("coordinador", "coowner")
    return factory.event(status="creado", coordinator=owner)          # el evento es de OTRO coordinador


def _no_role_block(r):
    """200, o un rechazo legítimo del negocio (400/409/422: falta archivo, estado...), nunca un 401/403/404 de rol o de pertenencia."""
    return r.status_code not in (401, 403, 404)


def _touch_configuration(client, ev):
    out = [client.get(u.format(id=ev.id)) for u in PARAM_URLS]
    out.append(client.put(f"/api/events/{ev.id}/directory-page-size", json={"value": 50}))
    out.append(client.post("/api/bulk_roster/preview", data={"event_id": ev.id}))        # sin archivo: 400 «falta el archivo», no un bloqueo de rol
    out.append(client.post("/api/bulk_roster", data={"event_id": ev.id}))
    return out


@pytest.mark.parametrize("role", ["coordinador", "admin", "super_admin"])
def test_coordinator_admin_superadmin_configure_any_event_by_default(client, factory, role):
    ev = _setup(factory)
    factory.staff(role, "actor1")
    login(client, "actor1")
    for r in _touch_configuration(client, ev):
        assert _no_role_block(r), (str(r.request.url), r.status_code, r.text[:200])
    assert ev.id in {e["id"] for e in client.get("/api/events").json()}      # y lo ve en la lista de eventos


def test_coordinator_plus_commercial_double_role_also_configures(client, factory):
    ev = _setup(factory)
    factory.staff("coordinador", "actor1", secondary_role="comercial")
    login(client, "actor1")
    for r in _touch_configuration(client, ev):
        assert _no_role_block(r), (str(r.request.url), r.status_code)


def test_foreign_coordinator_opens_event_through_get_event_for_staff(factory, db):
    from app.auth import get_event_for_staff
    ev = _setup(factory)
    stranger = factory.staff("coordinador", "coord2")                 # ni coordinador, ni comercial, ni creador, sin autorización
    assert get_event_for_staff(ev.id, db, stranger).id == ev.id


@pytest.mark.parametrize("role", ["comercial", "digitador", "cliente"])
def test_commercial_digitador_client_cannot_configure(client, factory, role):
    ev = _setup(factory)
    factory.staff(role, "actor1")
    login(client, "actor1")
    assert client.get(f"/api/events/{ev.id}/field-configs").status_code == 403
    assert client.put(f"/api/events/{ev.id}/directory-page-size", json={"value": 50}).status_code == 403
    assert client.post("/api/bulk_roster", data={"event_id": ev.id}).status_code == 403
    assert client.post("/api/bulk_roster/preview", data={"event_id": ev.id}).status_code == 403


def test_scope_lock_is_off_by_default(monkeypatch):
    from app.auth import event_scope_enforced
    monkeypatch.delenv("ENFORCE_STAFF_EVENT_SCOPE", raising=False)
    assert event_scope_enforced() is False


def test_with_scope_lock_on_foreign_coordinator_gets_404_but_admin_does_not(client, factory, monkeypatch):
    """ENFORCE_STAFF_EVENT_SCOPE=1 es el candado de seguridad 0C (A6/A7), APAGADO por decisión del dueño: se prueba aquí solo para documentar qué pasaría si se enciende (404 para el coordinador ajeno)."""
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    ev = _setup(factory)
    factory.staff("coordinador", "coord2")
    factory.staff("admin", "adm1")
    login(client, "coord2")
    assert client.get(f"/api/events/{ev.id}/field-configs").status_code == 404
    assert client.post("/api/bulk_roster/preview", data={"event_id": ev.id}).status_code == 404
    assert ev.id not in {e["id"] for e in client.get("/api/events").json()}
    client.post("/logout")
    login(client, "adm1")
    assert client.get(f"/api/events/{ev.id}/field-configs").status_code == 200
