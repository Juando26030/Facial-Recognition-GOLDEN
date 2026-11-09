"""Fase 3, cierre de huecos de CRUD (7-nov-2026): estados de evento (archivar/restaurar/borrar), plantillas de formulario, histórico de accesos de una persona (solo super_admin, con
confirmación fuerte), recordatorios del calendario y borrado en bloque de digitadores temporales. Todo deja rastro en audit_actions."""
import inspect
from datetime import date

from app.models import AccessLog, AuditAction, CalendarNote, EventState, SavedFormTemplate, StaffUser
from tests.conftest import login


def _acts(db, entity=None):
    q = db.query(AuditAction)
    if entity:
        q = q.filter(AuditAction.entity == entity)
    return [(a.action, a.entity) for a in q.order_by(AuditAction.id)]


# ------------------------------------------------------------------ estados de evento
def _state(db, name, base="creado"):
    s = EventState(name=name, base_status=base, position=db.query(EventState).count())
    db.add(s)
    db.commit()
    return s


def test_event_state_archive_restore_delete(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    a, b = _state(db, "A"), _state(db, "B")
    aid = a.id
    login(client, "adm")
    assert client.delete(f"/api/event-states/{aid}").status_code == 403                    # admin ya no borra
    assert client.post(f"/api/event-states/{aid}/archive").status_code == 200
    assert client.post(f"/api/event-states/{aid}/archive").status_code == 400
    assert aid not in {s["id"] for s in client.get("/api/event-states").json()["states"]}
    assert aid in {s["id"] for s in client.get("/api/event-states", params={"include_archived": "true"}).json()["states"]}
    assert client.patch(f"/api/event-states/{aid}", json={"name": "Otro"}).status_code == 400          # archivado no se edita
    assert client.delete(f"/api/event-states/{aid}").status_code == 403
    assert client.post(f"/api/event-states/{aid}/restore").json()["is_active"] is True
    assert client.post(f"/api/event-states/{aid}/archive").status_code == 200
    login(client, "sup")
    assert client.delete(f"/api/event-states/{aid}").status_code == 200
    db.expire_all()
    assert db.get(EventState, aid) is None
    assert [a for a, _ in _acts(db, "event_state")] == ["archive", "restore", "archive", "delete"]   # el admin archiva, restaura y vuelve a archivar; el super_admin borra
    assert db.get(EventState, b.id) is not None


def test_event_state_delete_needs_archived_and_unused(client, factory, db):
    factory.staff("super_admin", "sup")
    a, _b = _state(db, "A"), _state(db, "B")
    login(client, "sup")
    assert client.delete(f"/api/event-states/{a.id}").status_code == 400                   # sin archivar
    factory.event("creado", state_id=a.id)
    assert client.post(f"/api/event-states/{a.id}/archive").status_code == 400             # con eventos
    assert client.get("/api/event-states", params={"include_archived": "true"}).status_code == 200


def test_event_state_archived_list_is_admin_plus(client, factory, db):
    factory.staff("coordinador", "co")
    login(client, "co")
    assert client.get("/api/event-states").status_code == 200
    assert client.get("/api/event-states", params={"include_archived": "true"}).status_code == 403
    assert client.post("/api/event-states/1/archive").status_code == 403


# ------------------------------------------------------------------ plantillas de formulario
def test_form_template_library_archive(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("coordinador", "co")
    ev = factory.event()
    tpl = SavedFormTemplate(tenant_id=ev.tenant_id, name="Base", design_json='{"fields": {}}')
    db.add(tpl)
    db.commit()
    tid = tpl.id
    login(client, "co")
    assert client.delete(f"/api/events/{ev.id}/form-templates/{tid}").status_code == 403   # coordinador ya no borra
    assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/archive").status_code == 200   # cambio 7-nov: coordinador+ archiva y restaura
    assert client.get(f"/api/events/{ev.id}/form-templates", params={"include_archived": "true"}).status_code == 200
    assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/restore").status_code == 200
    for role in ("comercial", "digitador", "cliente"):
        s = factory.staff(role, f"u_{role}")
        factory.authorize(ev, s)
        login(client, f"u_{role}")
        want = 200 if role == "comercial" else 403
        assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/archive").status_code == want
        if want == 200:
            assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/restore").status_code == 200
        else:
            assert client.get(f"/api/events/{ev.id}/form-templates", params={"include_archived": "true"}).status_code == 403
    login(client, "adm")
    assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/archive").status_code == 200
    assert client.get(f"/api/events/{ev.id}/form-templates").json() == []
    assert [t["id"] for t in client.get(f"/api/events/{ev.id}/form-templates", params={"include_archived": "true"}).json()] == [tid]
    assert client.delete(f"/api/events/{ev.id}/form-templates/{tid}").status_code == 403   # admin tampoco: super_admin
    assert client.post(f"/api/events/{ev.id}/form-templates/{tid}/restore").status_code == 200
    assert len(client.get(f"/api/events/{ev.id}/form-templates").json()) == 1
    factory.staff("super_admin", "sup")
    login(client, "sup")
    assert client.delete(f"/api/events/{ev.id}/form-templates/{tid}").status_code == 400   # sin archivar
    client.post(f"/api/events/{ev.id}/form-templates/{tid}/archive")
    assert client.delete(f"/api/events/{ev.id}/form-templates/{tid}").status_code == 200
    assert [a for a, _ in _acts(db, "saved_form_template")] == ["archive", "restore"] * 3 + ["archive", "delete"]   # coordinador, comercial y admin archivan+restauran; el super_admin archiva y borra


# ------------------------------------------------------------------ histórico de accesos de una persona
def test_delete_user_logs_super_admin_with_strong_confirmation(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", record_type="Existente", event_id=ev.id))
    db.commit()
    login(client, "adm")
    assert client.delete(f"/api/users/1001/logs?event_id={ev.id}&confirm=1001").status_code == 403
    login(client, "sup")
    assert client.delete(f"/api/users/1001/logs?event_id={ev.id}").status_code == 400                     # sin confirmación
    assert client.delete(f"/api/users/1001/logs?event_id={ev.id}&confirm=9999").status_code == 400        # confirmación equivocada
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == 1
    assert client.delete(f"/api/users/1001/logs?event_id={ev.id}&confirm=1001").status_code == 200
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=ev.id).count() == 0
    rows = db.query(AuditAction).filter_by(entity="access_logs").all()
    assert len(rows) == 1 and rows[0].action == "delete" and "1001" not in f"{rows[0].entity_id}{rows[0].entity_name}{rows[0].detail}"      # nunca la cédula


# ------------------------------------------------------------------ recordatorios del calendario
def test_calendar_note_delete_author_or_admin_and_audited(client, factory, db):
    factory.staff("coordinador", "co1")
    factory.staff("coordinador", "co2")
    factory.staff("admin", "adm")
    login(client, "co1")
    n1 = client.post("/api/calendar/notes", json={"date": date.today().isoformat(), "text": "llamar al cliente"}).json()["id"]
    n2 = client.post("/api/calendar/notes", json={"date": date.today().isoformat(), "text": "otro"}).json()["id"]
    login(client, "co2")
    assert client.delete(f"/api/calendar/notes/{n1}").status_code == 403                  # no es el autor
    login(client, "co1")
    assert client.delete(f"/api/calendar/notes/{n1}").status_code == 200                   # el autor
    login(client, "adm")
    assert client.delete(f"/api/calendar/notes/{n2}").status_code == 200                   # admin+
    db.expire_all()
    assert db.query(CalendarNote).count() == 0
    rows = db.query(AuditAction).filter_by(entity="calendar_note").all()
    assert len(rows) == 2 and all("llamar" not in f"{r.entity_name}{r.detail}" for r in rows)       # el texto no se copia al registro


# ------------------------------------------------------------------ borrado en bloque de digitadores temporales
def test_purge_temporary_deletes_for_real(client, factory, db):
    factory.staff("coordinador", "co")
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "55667788")
    factory.authorize(ev, dig)
    dig_id = dig.id
    login(client, "co")
    r = client.post(f"/api/events/{ev.id}/staff-users/purge-temporary")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1 and r.json()["kept_archived"] == 0
    db.expire_all()
    assert db.get(StaffUser, dig_id) is None                                                       # se borró de verdad
    acts = db.query(AuditAction).filter_by(entity="staff_user").all()
    assert len(acts) == 1 and acts[0].action == "delete" and "55667788" not in f"{acts[0].entity_name}{acts[0].detail}"


def test_sources_guard_roles():
    from app.routers import api, event_states, forms
    for fn in (event_states.archive_state, event_states.restore_state):
        assert 'require_role("admin")' in inspect.getsource(fn)
    for fn in (event_states.delete_state, forms.delete_template, api.delete_user_logs):
        assert 'require_role("super_admin")' in inspect.getsource(fn) or "SUPER" in inspect.getsource(fn)
