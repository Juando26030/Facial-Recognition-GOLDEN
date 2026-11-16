"""Duplicar un evento y borrar la base cargada (16-nov-2026). DATOS SINTÉTICOS."""
from datetime import datetime

from sqlalchemy import func

from app import event_duplicate, roster_delete
from app import models as m
from tests.test_event_transfer import _build


def _n(db, model, **kw):
    return db.query(func.count()).select_from(model).filter_by(**kw).scalar()


def test_duplicate_copies_the_setup_and_people_but_not_the_history(db, factory):
    ev = _build(db, factory)
    staff = factory.staff("admin", "admin_dup")
    new = event_duplicate.duplicate(db, ev, staff)
    assert new.id != ev.id and new.event_code != ev.event_code and new.name.endswith("(copia)") and new.status == "creado"
    assert _n(db, m.EventFieldConfig, event_id=new.id) == _n(db, m.EventFieldConfig, event_id=ev.id)
    assert _n(db, m.EventArea, event_id=new.id) == 1 and _n(db, m.InventoryItem, event_id=new.id) == 1 and _n(db, m.BadgeTemplate, event_id=new.id) == 1
    assert _n(db, m.EventAttendee, event_id=new.id) == _n(db, m.EventAttendee, event_id=ev.id)
    form = db.query(m.WebForm).filter_by(event_id=new.id).one()
    assert form.manual_status == "pruebas"
    for model in (m.AccessLog, m.AreaMovement, m.InventoryDelivery, m.PrintLog, m.PersonChange, m.WebAcceptance, m.FormSubmission, m.FormPayment, m.RouletteDraw):
        assert _n(db, model, event_id=new.id) == 0, model.__name__
    assert _n(db, m.AccessLog, event_id=ev.id) == 2                       # el original no cambia
    assert db.query(m.User).filter(m.User.face_encoding == "VECTOR-SECRETO").count() == 3      # nada biométrico sale ni se pierde


def test_suggested_code_and_name_never_collide(db, factory):
    ev = _build(db, factory)
    s1 = event_duplicate.suggest(db, ev)
    assert s1["event_code"].endswith("-COPIA") and s1["name"].endswith("(copia)")
    staff = factory.staff("admin", "admin_dup2")
    first = event_duplicate.duplicate(db, ev, staff)
    s2 = event_duplicate.suggest(db, ev)
    assert s2["event_code"] != first.event_code and s2["name"] != first.name


def test_delete_loaded_base_keeps_registered_people_and_manual_ones(db, factory):
    ev = _build(db, factory)                                              # 3 personas «base»; 1001 y 1002 tienen ingreso
    factory.person(ev, "2001", "Manu", "Manual")
    db.query(m.EventAttendee).filter_by(event_id=ev.id, user_id="2001").update({"origin": "manual"})
    db.commit()
    p = roster_delete.preview(db, ev)
    assert p["loaded"] == 3 and p["deletable"] == 1 and p["kept_registered"] == 2
    out = roster_delete.delete_loaded(db, ev)
    db.commit()
    assert out["removed"] == 1 and out["kept_registered"] == 2
    left = {a.user_id for a in db.query(m.EventAttendee).filter_by(event_id=ev.id)}
    assert "1003" not in left and {"1001", "1002", "2001"} <= left
    assert db.query(m.User).filter_by(id="1003", tenant_id=ev.tenant_id).first() is None          # no está en otro evento: se va su ficha
    assert db.query(m.User).filter_by(id="1001", tenant_id=ev.tenant_id).first() is not None


def test_duplicate_route_copies_event_contacts(db, factory):
    from app import event_contacts
    ev = _build(db, factory)
    event_contacts.replace(db, ev, [{"name": "Ana", "email": "ana@x.co", "phone": "301", "note": "Compras"}])
    db.commit()
    assert event_contacts.copy_to(db, ev.id, event_duplicate.duplicate(db, ev, factory.staff("admin", "admin_dup2")).id) == 1
