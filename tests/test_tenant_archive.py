"""Fase 3, oleada 1 (7-nov-2026): clientes. Archivar = ocultar y restaurar (admin+); editar comercial+; borrado definitivo solo super_admin, de un archivado sin eventos; todo deja rastro en audit_actions."""
import inspect

import pytest

from app.models import AuditAction, Tenant
from tests.conftest import login
from tests.test_coordinador_crea_eventos import _payload


def _ids(client, **params):
    return {t["id"] for t in client.get("/api/tenants", params=params).json()}


def test_sources_guard_roles():
    from app.routers import tenants
    assert 'require_role("admin")' in inspect.getsource(tenants.archive_tenant)
    assert 'require_role("admin")' in inspect.getsource(tenants.restore_tenant)
    assert 'require_role("comercial")' in inspect.getsource(tenants.update_tenant)
    assert 'require_role("super_admin")' in inspect.getsource(tenants.delete_tenant)


def test_archived_tenant_hidden_by_default_and_visible_to_admin_on_request(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post("/api/tenants/acme/archive").status_code == 200
    assert "acme" not in _ids(client)
    assert "acme" in _ids(client, include_archived="true")
    assert client.post("/api/tenants/acme/restore").status_code == 200
    assert "acme" in _ids(client)


def test_only_admin_plus_archives_restores_and_lists_archived(client, factory):
    factory.tenant("acme")
    factory.staff("comercial", "com")
    login(client, "com")
    assert client.post("/api/tenants/acme/archive").status_code == 403
    assert client.post("/api/tenants/acme/restore").status_code == 403
    assert client.get("/api/tenants", params={"include_archived": "true"}).status_code == 403


def test_cannot_archive_with_event_in_progress_but_can_when_finished(client, factory):
    factory.event(status="en_proceso")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post("/api/tenants/acme/archive").status_code == 400
    assert "acme" in _ids(client)
    from app.database import SessionLocal
    with SessionLocal() as s:
        from app.models import Event
        s.query(Event).update({"status": "finalizado"})
        s.commit()
    assert client.post("/api/tenants/acme/archive").status_code == 200


def test_cannot_create_event_for_archived_tenant(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    factory.staff("admin", "adm")
    login(client, "adm")
    payload = _payload(coord.id, commercial_staff_id=com.id)          # el admin debe elegir la comercial: sin ella el 400 sería por otro motivo
    client.post("/api/tenants/acme/archive")
    r = client.post("/api/events", json=payload)
    assert r.status_code == 400 and "archivado" in r.json()["detail"]
    client.post("/api/tenants/acme/restore")
    assert client.post("/api/events", json=payload).status_code == 200


@pytest.mark.parametrize("role,expected", [("coordinador", 403), ("comercial", 200), ("admin", 200), ("super_admin", 200)])
def test_edit_is_commercial_plus(client, factory, role, expected):
    factory.tenant("acme")
    factory.staff(role, "actor")
    login(client, "actor")
    r = client.patch("/api/tenants/acme", json={"contact_name": "  Nuevo contacto "})
    assert r.status_code == expected
    if expected == 200:
        assert r.json()["contact_name"] == "Nuevo contacto"


def test_archived_tenant_cannot_be_edited_and_blank_name_rejected(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.patch("/api/tenants/acme", json={"name": "   "}).status_code == 400
    client.post("/api/tenants/acme/archive")
    assert client.patch("/api/tenants/acme", json={"contact_name": "X"}).status_code == 400


def test_hard_delete_rules(client, factory, db):
    factory.tenant("vacio")
    factory.event(tenant_id="conev", status="finalizado")
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    assert client.delete("/api/tenants/vacio").status_code == 403
    login(client, "sup")
    assert client.delete("/api/tenants/vacio").status_code == 400            # primero hay que archivarlo
    assert client.post("/api/tenants/vacio/archive").status_code == 200
    assert client.post("/api/tenants/conev/archive").status_code == 200
    assert client.delete("/api/tenants/conev").status_code == 400            # tiene eventos
    assert client.delete("/api/tenants/vacio").status_code == 200
    db.expire_all()
    assert db.query(Tenant).filter_by(id="vacio").first() is None
    assert db.query(Tenant).filter_by(id="conev").first() is not None


def test_actions_are_logged_without_personal_data(client, factory, db):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    client.patch("/api/tenants/acme", json={"contact_email": "secreto@example.com", "contact_name": "Persona Privada"})
    client.post("/api/tenants/acme/archive")
    client.post("/api/tenants/acme/restore")
    db.expire_all()
    rows = db.query(AuditAction).order_by(AuditAction.id).all()
    assert [r.action for r in rows] == ["edit", "archive", "restore"]
    assert all(r.entity == "tenant" and r.entity_id == "acme" and r.actor_role == "admin" for r in rows)
    blob = " ".join(str(r.detail) for r in rows)
    assert "secreto@example.com" not in blob and "Persona Privada" not in blob
