"""Revisión de seguridad F5-9 D (eventos, inventario, panel interno). Ver docs/seguridad/F5-9_D_eventos.md."""
import pytest

from app import auth, event_history as eh, inventory_alerts, notifications
from tests.conftest import login


# ---------------------------------------------------------------- D1: una cuenta SOLO de almacén/contabilidad no abre datos de asistentes
@pytest.mark.parametrize("role", ["almacen", "contabilidad"])
def test_inventory_only_account_cannot_open_attendee_directory(client, factory, role):
    factory.staff(role, "solo")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "solo")
    assert client.get(f"/api/users?event_id={ev.id}").status_code == 403                     # antes: 200 con el directorio completo (sin enmascarar)
    assert client.get(f"/api/users/changes?event_id={ev.id}").status_code == 403
    assert client.get(f"/api/events/{ev.id}/person-form").status_code == 403
    assert client.get(f"/api/events/{ev.id}/categories").status_code == 403
    assert client.get("/api/my-events").json()["events"] == []                                # antes: todos los eventos en proceso con su detalle
    assert client.get(f"/kiosk/{ev.id}", follow_redirects=False).status_code in (302, 303, 307)
    assert client.get(f"/api/events/{ev.id}/inventory-plan").status_code == 200               # su puerta (el inventario) sigue abierta


def test_get_event_for_staff_blocks_inventory_only_but_not_mixed_accounts(factory, db):
    ev = factory.event("en_proceso")
    solo = factory.staff("almacen", "a_solo")
    mixed = factory.staff("coordinador", "a_mix", extra_roles="almacen")
    with pytest.raises(Exception) as exc:
        auth.get_event_for_staff(ev.id, db, solo)
    assert getattr(exc.value, "status_code", None) == 403
    assert auth.get_event_for_staff(ev.id, db, mixed).id == ev.id


# ---------------------------------------------------------------- D2: avisos sólo a cuentas que ven el cliente del evento
def test_notice_recipients_skip_other_tenants_when_isolation_is_on(factory, db, monkeypatch):
    factory.tenant("otra")
    ev = factory.event("creado", tenant_id="acme")
    mine = factory.staff("almacen", "alm_acme", email="a@ejemplo.com", tenant_id="acme")
    other = factory.staff("almacen", "alm_otra", email="b@ejemplo.com", tenant_id="otra")
    golden = factory.staff("contabilidad", "con_golden", email="c@ejemplo.com")          # sin tenant = personal de Golden (global)
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "0")
    assert other.id in inventory_alerts.recipients(db, ev, None)                          # apagado: igual que siempre
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    got = inventory_alerts.recipients(db, ev, None)
    assert mine.id in got and other.id not in got
    got = eh.recipients(db, ev, None)
    assert mine.id in got and golden.id in got and other.id not in got


# ---------------------------------------------------------------- D3: la campana solo enlaza rutas internas
@pytest.mark.parametrize("url,expected", [("/inventario", "/inventario"), ("//evil.example", None), ("/\\evil.example", None), ("https://evil.example", None),
                                          ("javascript:alert(1)", None), ("/a b", None), (None, None)])
def test_notification_url_must_be_internal(url, expected):
    assert notifications.internal_url(url) == expected


# ---------------------------------------------------------------- D4: rango de quien edita = el efectivo (almacén con admin sumado no da 500; coordinador con admin sumado no edita a otro admin)
def test_profile_and_email_edit_use_effective_rank(client, factory, db):
    factory.staff("super_admin", "sup")
    boss = factory.staff("almacen", "alm_admin", extra_roles="admin")
    coord = factory.staff("coordinador", "coord_x")
    adm = factory.staff("admin", "adm_x")
    login(client, "alm_admin")
    assert client.patch(f"/api/staff/{coord.id}/email", json={"email": "c@ejemplo.com"}).status_code == 200          # antes: 500 (STAFF_ROLES.index("almacen"))
    assert client.patch(f"/api/staff/{coord.id}/profile", json={"full_name": "Coord X"}).status_code == 200
    assert client.patch(f"/api/staff/{adm.id}/email", json={"email": "a@ejemplo.com"}).status_code in (403, 404)          # un admin no toca a otro admin
    assert boss.id
