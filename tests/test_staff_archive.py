"""Fase 3, oleada 2 (7-nov-2026): usuarios del personal. Archivar = no inicia sesión y no sale en listas ni selectores (admin+, dentro de su alcance); restaurar; borrado definitivo solo super_admin, de una
cuenta archivada y sin eventos asignados; todo deja rastro en audit_actions."""
import inspect

from app.models import AuditAction, StaffUser
from tests.conftest import login


def _ids(client, **params):
    return {s["id"] for s in client.get("/api/staff", params=params).json()}


def test_sources_guard_roles():
    from app.routers import staff
    assert 'require_role("admin")' in inspect.getsource(staff.archive_staff)
    assert 'require_role("admin")' in inspect.getsource(staff.restore_staff)
    assert 'require_role("super_admin")' in inspect.getsource(staff.delete_staff)


def test_archived_hidden_by_default_and_listed_on_request(client, factory):
    factory.staff("admin", "adm")
    coord = factory.staff("coordinador", "coord")
    login(client, "adm")
    assert client.post(f"/api/staff/{coord.id}/archive").status_code == 200
    assert coord.id not in _ids(client)
    assert coord.id in _ids(client, include_archived="true")
    assert coord.id not in {c["id"] for c in client.get("/api/staff/coordinators").json()}
    assert client.post(f"/api/staff/{coord.id}/restore").status_code == 200
    assert coord.id in _ids(client)


def test_archived_cannot_login_and_restore_leaves_it_inactive_until_reactivated(client, factory):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com")
    login(client, "adm")
    assert client.post(f"/api/staff/{com.id}/archive").status_code == 200
    assert client.patch(f"/api/staff/{com.id}/activate").status_code == 400          # archivada: primero restaurar
    client.cookies.clear()
    login(client, "com")
    assert client.get("/api/staff/coordinators").status_code in (401, 403)          # no hay sesión: una cuenta archivada no ingresa
    client.cookies.clear()
    login(client, "adm")
    assert client.post(f"/api/staff/{com.id}/restore").status_code == 200
    assert client.patch(f"/api/staff/{com.id}/activate").status_code == 200


def test_only_admin_plus_and_not_self_nor_higher_ranks(client, factory):
    adm = factory.staff("admin", "adm")
    other_adm = factory.staff("admin", "adm2")
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    login(client, "coord")
    assert client.post(f"/api/staff/{com.id}/archive").status_code == 403
    assert client.get("/api/staff", params={"include_archived": "true"}).status_code == 403
    login(client, "adm")
    assert client.post(f"/api/staff/{adm.id}/archive").status_code == 400          # a sí mismo
    assert client.post(f"/api/staff/{other_adm.id}/archive").status_code == 403    # un admin no archiva a otro admin
    assert client.post(f"/api/staff/{coord.id}/archive").status_code == 200


def test_cannot_archive_last_super_admin_but_can_when_another_remains(client, factory):
    sup = factory.staff("super_admin", "sup")
    sup2 = factory.staff("super_admin", "sup2")
    login(client, "sup")
    assert client.post(f"/api/staff/{sup.id}/archive").status_code == 400          # a sí mismo
    assert client.post(f"/api/staff/{sup2.id}/archive").status_code == 200         # queda sup activo
    assert client.post(f"/api/staff/{sup2.id}/restore").status_code == 200
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post(f"/api/staff/{sup2.id}/archive").status_code == 403         # solo otro super_admin


def test_cannot_archive_coordinator_or_commercial_of_event_in_progress(client, factory):
    factory.staff("admin", "adm")
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    ev = factory.event("en_proceso", coordinator=coord, commercial=com)
    login(client, "adm")
    assert client.post(f"/api/staff/{coord.id}/archive").status_code == 400
    assert client.post(f"/api/staff/{com.id}/archive").status_code == 400
    from app.database import SessionLocal
    with SessionLocal() as s:
        from app.models import Event
        s.query(Event).filter(Event.id == ev.id).update({"status": "finalizado"})
        s.commit()
    assert client.post(f"/api/staff/{coord.id}/archive").status_code == 200
    assert client.post(f"/api/staff/{com.id}/archive").status_code == 200


def test_hard_delete_rules(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    libre = factory.staff("comercial", "libre")
    ocupado = factory.staff("coordinador", "ocupado")
    factory.event("finalizado", coordinator=ocupado)
    libre_id, ocupado_id = libre.id, ocupado.id
    login(client, "adm")
    assert client.delete(f"/api/staff/{libre_id}").status_code == 403              # solo super_admin
    login(client, "sup")
    assert client.delete(f"/api/staff/{libre_id}").status_code == 400              # primero archivar
    assert client.post(f"/api/staff/{libre_id}/archive").status_code == 200
    assert client.post(f"/api/staff/{ocupado_id}/archive").status_code == 200
    assert client.delete(f"/api/staff/{ocupado_id}").status_code == 400            # tiene eventos asignados
    assert client.delete(f"/api/staff/{libre_id}").status_code == 200
    db.expire_all()
    assert db.query(StaffUser).filter_by(id=libre_id).first() is None
    assert db.query(StaffUser).filter_by(id=ocupado_id).first() is not None


def test_actions_are_logged_without_cedula_of_temporary_digitador(client, factory, db):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com")
    dig = factory.staff("digitador", "1012345678")
    login(client, "adm")
    client.post(f"/api/staff/{com.id}/archive")
    client.post(f"/api/staff/{com.id}/restore")
    client.post(f"/api/staff/{dig.id}/archive")
    db.expire_all()
    rows = db.query(AuditAction).order_by(AuditAction.id).all()
    assert [r.action for r in rows] == ["archive", "restore", "archive"]
    assert all(r.entity == "staff_user" and r.actor_role == "admin" for r in rows)
    assert rows[0].entity_name == "com"
    assert rows[2].entity_name is None and "1012345678" not in " ".join(str(r.detail) + str(r.entity_name) for r in rows)
