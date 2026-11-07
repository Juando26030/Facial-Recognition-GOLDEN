"""Fase 3, oleada de personas y formularios (7-nov-2026). Archivar = ocultar y restaurar (admin+); borrado definitivo solo super_admin, de algo ya archivado; todo deja rastro en audit_actions
sin datos personales. Las rutas de privacidad (purge-data, revocación) y audit_consent_logs no se tocan. Formularios: archivado = cerrado al público pero con respuestas y pagos intactos."""
import inspect

import pytest

from app.models import AuditAction, AuditConsentLog, EventAttendee, FormSubmission, User, WebForm
from tests.conftest import accept, login
from tests.test_forms import _create, _open, _person_values, _submit, _url


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _ids(client, ev, **params):
    r = client.get("/api/users", params={"event_id": ev.id, **params})
    assert r.status_code == 200, r.text
    return {u["id"] for u in r.json()}


def _people(factory, ev_status="en_proceso"):
    ev = factory.event(ev_status)
    factory.person(ev, "1001", "Ana", "Mora")
    factory.person(ev, "1002", "Beto", "Rios")
    return ev


# --------------------------------------------------------------------------- personas
def test_sources_guard_roles():
    from app.routers import api, forms
    assert 'require_role("admin")' in inspect.getsource(api.archive_person)
    assert 'require_role("admin")' in inspect.getsource(api.restore_person)
    assert 'require_role("super_admin")' in inspect.getsource(api.delete_user_from_event)
    assert "ADMIN" in inspect.getsource(forms.archive_form) and "ADMIN" in inspect.getsource(forms.restore_form)
    assert 'require_role("super_admin")' in inspect.getsource(forms.delete_form)
    assert "ADMIN" in inspect.getsource(forms.delete_submission)


def test_archived_person_is_hidden_by_default_and_listed_for_admin_only(client, factory):
    ev = _people(factory)
    factory.staff("admin", "adm")
    login(client, "adm")
    assert _ids(client, ev) == {"1001", "1002"}
    assert client.post(f"/api/users/1001/archive?event_id={ev.id}").status_code == 200
    assert _ids(client, ev) == {"1002"}
    assert _ids(client, ev, archived="true") == {"1001"}
    r = client.get("/api/users", params={"event_id": ev.id, "limit": 10, "offset": 0})
    assert r.headers["X-Total-Count"] == "1"
    assert client.post(f"/api/users/1001/archive?event_id={ev.id}").status_code == 400          # ya archivada
    assert client.post(f"/api/users/1001/restore?event_id={ev.id}").status_code == 200
    assert _ids(client, ev) == {"1001", "1002"} and _ids(client, ev, archived="true") == set()
    assert client.post(f"/api/users/1001/restore?event_id={ev.id}").status_code == 400          # ya no está archivada


def test_archive_is_scoped_to_one_event(client, factory):
    ev = _people(factory)
    other = factory.event("en_proceso")
    factory.person(other, "1001")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.post(f"/api/users/1001/archive?event_id={ev.id}").status_code == 200
    assert _ids(client, other) == {"1001"}


@pytest.mark.parametrize("role", ["digitador", "coordinador", "comercial"])
def test_only_admin_plus_archives_restores_lists_archived_and_nobody_below_super_deletes(client, factory, role):
    ev = _people(factory)
    staff = factory.staff(role, "actor")
    factory.authorize(ev, staff)
    login(client, "actor")
    assert client.post(f"/api/users/1001/archive?event_id={ev.id}").status_code == 403
    assert client.post(f"/api/users/1001/restore?event_id={ev.id}").status_code == 403
    assert client.get("/api/users", params={"event_id": ev.id, "archived": "true"}).status_code == 403
    assert client.delete(f"/api/users/1001?event_id={ev.id}").status_code == 403


def test_hard_delete_of_a_person_needs_super_admin_and_an_archived_enrollment(client, factory, db):
    ev = _people(factory)
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    client.post(f"/api/users/1001/archive?event_id={ev.id}")
    assert client.delete(f"/api/users/1001?event_id={ev.id}").status_code == 403                # admin archiva, no borra
    login(client, "sup")
    assert client.delete(f"/api/users/1002?event_id={ev.id}").status_code == 400                # sin archivar no se borra
    assert client.delete(f"/api/users/1001?event_id={ev.id}").status_code == 200
    db.expire_all()
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").first() is None
    assert db.get(User, ("1001", ev.tenant_id)) is None and db.get(User, ("1002", ev.tenant_id)) is not None


def test_archiving_does_not_touch_consent_logs_and_logs_without_personal_data(client, factory, db):
    ev = _people(factory)
    accept(db, ev, "1001")
    before = db.query(AuditConsentLog).count()
    assert before >= 1
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    client.post(f"/api/users/1001/archive?event_id={ev.id}")
    client.post(f"/api/users/1001/restore?event_id={ev.id}")
    client.post(f"/api/users/1001/archive?event_id={ev.id}")
    login(client, "sup")
    client.delete(f"/api/users/1001?event_id={ev.id}")
    db.expire_all()
    assert db.query(AuditConsentLog).count() == before                                          # lo legal es inmutable: ni archivar ni borrar a la persona lo toca
    rows = db.query(AuditAction).order_by(AuditAction.id).all()
    assert [r.action for r in rows] == ["archive", "restore", "archive", "delete"] and all(r.entity == "attendee" for r in rows)
    assert [r.actor_role for r in rows] == ["admin", "admin", "admin", "super_admin"]
    blob = " ".join(f"{r.entity_id} {r.entity_name} {r.detail}" for r in rows)
    assert "1001" not in blob.replace(f"evento {ev.id}", "") and "Ana" not in blob and "Mora" not in blob


def test_a_person_with_only_access_logs_can_still_be_archived(client, factory, db):
    from app.models import AccessLog
    ev = factory.event("en_proceso")
    factory.person(ev, "3003", "Sin", "Precarga", attend=False)
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="3003", record_type="Nuevo", event_id=ev.id))
    db.commit()
    factory.staff("admin", "adm")
    login(client, "adm")
    assert _ids(client, ev) == {"3003"}
    assert client.post(f"/api/users/3003/archive?event_id={ev.id}").status_code == 200
    assert _ids(client, ev) == set() and _ids(client, ev, archived="true") == {"3003"}


# --------------------------------------------------------------------------- formularios
def _form_setup(client, factory, with_submission=False):
    factory.staff("admin", "adm1")
    factory.staff("super_admin", "sup1")
    ev = factory.event("en_proceso")
    login(client, "adm1")
    form = _create(client, ev)
    _open(client, ev, form)
    if with_submission:
        assert _submit(client, ev, form, _person_values()).status_code == 200
    login(client, "adm1")
    return ev, form


def _forms(client, ev, **params):
    r = client.get(f"/api/events/{ev.id}/forms", params=params)
    assert r.status_code == 200, r.text
    return {f["id"] for f in r.json()}


def test_archived_form_is_hidden_closed_to_the_public_and_keeps_its_answers(client, factory, db):
    ev, form = _form_setup(client, factory, with_submission=True)
    assert client.get(f"{_url(ev, form)}/state").status_code == 200
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/archive").status_code == 200
    assert _forms(client, ev) == set() and _forms(client, ev, include_archived="true") == {form["id"]}
    client.post("/logout")
    assert client.get(f"{_url(ev, form)}/state").status_code == 404
    assert _submit(client, ev, form, {**_person_values(), "cedula": "2002"}, sid="s2").status_code == 404      # no recibe envíos
    db.expire_all()
    assert db.query(FormSubmission).filter_by(form_id=form["id"], status="confirmed").count() == 1             # la respuesta se conserva
    row = db.get(WebForm, form["id"])
    assert row.archived_at is not None and row.manual_status == "cerrado" and row.use_schedule is False        # al restaurar NO se reabre solo


def test_restore_form_keeps_it_closed_and_archived_form_cannot_be_edited_or_cleaned(client, factory, db):
    ev, form = _form_setup(client, factory, with_submission=True)
    base = f"/api/events/{ev.id}/forms/{form['id']}"
    client.post(f"{base}/archive")
    assert client.put(base, json={"name": "Otro"}).status_code == 400
    assert client.put(f"{base}/status", json={"manual_status": "activo"}).status_code == 400
    sub_id = db.query(FormSubmission).filter_by(form_id=form["id"]).one().id
    assert client.delete(f"{base}/submissions/{sub_id}").status_code == 400
    assert client.post(f"{base}/restore").status_code == 200
    assert _forms(client, ev) == {form["id"]}
    assert client.get(f"{_url(ev, form)}/state").status_code in (200, 404)           # cerrado (o sin acceso), nunca abierto a envíos
    assert _submit(client, ev, form, {**_person_values(), "cedula": "2002"}, sid="s3").status_code != 200


def test_form_archive_permissions_and_hard_delete_rules(client, factory, db):
    ev, form = _form_setup(client, factory, with_submission=True)
    empty = client.post(f"/api/events/{ev.id}/forms", json={"name": "Vacío"}).json()
    base, ebase = f"/api/events/{ev.id}/forms/{form['id']}", f"/api/events/{ev.id}/forms/{empty['id']}"
    factory.staff("coordinador", "coord9")
    login(client, "coord9")
    assert client.post(f"{base}/archive").status_code == 403
    assert client.post(f"{base}/restore").status_code == 403
    assert client.get(f"/api/events/{ev.id}/forms", params={"include_archived": "true"}).status_code == 403
    assert client.delete(ebase).status_code == 403
    login(client, "adm1")
    assert client.delete(ebase).status_code == 403                                      # admin archiva, no borra
    client.post(f"{base}/archive")
    client.post(f"{ebase}/archive")
    login(client, "sup1")
    assert client.delete(base).status_code == 409                                       # con inscripciones: se conserva
    assert client.delete(ebase).status_code == 200                                      # archivado y vacío
    db.expire_all()
    assert db.get(WebForm, empty["id"]) is None and db.get(WebForm, form["id"]) is not None


def test_unarchived_form_cannot_be_hard_deleted_and_actions_are_logged_without_personal_data(client, factory, db):
    ev, form = _form_setup(client, factory)
    base = f"/api/events/{ev.id}/forms/{form['id']}"
    login(client, "sup1")
    assert client.delete(base).status_code == 400
    client.post(f"{base}/archive")
    client.post(f"{base}/restore")
    client.post(f"{base}/archive")
    assert client.delete(base).status_code == 200
    db.expire_all()
    rows = db.query(AuditAction).filter_by(entity="form").order_by(AuditAction.id).all()
    assert [r.action for r in rows] == ["archive", "restore", "archive", "delete"] and all(r.entity_id == str(form["id"]) for r in rows)


def test_delete_submission_is_admin_plus_and_logged(client, factory, db):
    ev, form = _form_setup(client, factory, with_submission=True)
    base = f"/api/events/{ev.id}/forms/{form['id']}"
    sub_id = db.query(FormSubmission).filter_by(form_id=form["id"]).one().id
    factory.staff("coordinador", "coord9")
    login(client, "coord9")
    assert client.delete(f"{base}/submissions/{sub_id}").status_code == 403
    login(client, "adm1")
    assert client.delete(f"{base}/submissions/{sub_id}").status_code == 200
    db.expire_all()
    row = db.query(AuditAction).filter_by(entity="form_submission").one()
    assert row.action == "delete" and "ana@example.com" not in str(row.detail) and "1001" not in str(row.detail)
