"""CRM C1a: restricciones de las tablas, cascadas y SUPRESIÓN (borrar un contacto borra su historial y sus notas). Necesitan PostgreSQL."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.crm import normalize
from app.crm.erase import erase_account, erase_contact


def _acc(db, code, name="Cuenta", **kw):
    a = m.CrmAccount(code=code, name=name, name_norm=normalize(name), **kw)
    db.add(a)
    db.flush()
    return a


def _contact(db, account, first="Ana", **kw):
    c = m.CrmContact(account_id=account.id, first_name=first, full_name_norm=normalize(first), **kw)
    db.add(c)
    db.flush()
    return c


def test_defaults_status_activo_and_timestamps(db):
    a = _acc(db, 1)
    db.commit()
    assert a.status == "activo" and a.created_at is not None and a.updated_at is not None and a.archived_at is None


def test_code_is_unique(db):
    _acc(db, 7)
    db.commit()
    db.add(m.CrmAccount(code=7, name="Otra", name_norm="otra"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_platform_client_has_at_most_one_crm_account_but_many_accounts_can_have_no_client(db, factory):
    factory.tenant("acme")
    _acc(db, 1, tenant_id="acme")
    _acc(db, 2)
    _acc(db, 3)                                                                              # varias sin cliente: permitido
    db.commit()
    db.add(m.CrmAccount(code=4, name="Duplicada", name_norm="duplicada", tenant_id="acme"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_only_one_primary_contact_per_account(db):
    a, b = _acc(db, 1), _acc(db, 2)
    _contact(db, a, "Ana", is_primary=True)
    _contact(db, a, "Beto", is_primary=False)
    _contact(db, b, "Carla", is_primary=True)                                                # otra cuenta: permitido
    db.commit()
    db.add(m.CrmContact(account_id=a.id, first_name="Dos", full_name_norm="dos", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_suitecrm_id_cannot_be_imported_twice(db):
    _acc(db, 1, legacy_sugar_id="abc-1")
    db.commit()
    db.add(m.CrmAccount(code=2, name="Repetida", name_norm="repetida", legacy_sugar_id="abc-1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_the_platform_client_leaves_the_crm_account_without_link(db, factory):
    factory.tenant("acme")
    _acc(db, 1, tenant_id="acme")
    db.commit()
    db.execute(text("DELETE FROM tenants WHERE id = 'acme'"))
    db.commit()
    assert db.query(m.CrmAccount).one().tenant_id is None


def test_deleting_an_account_removes_its_contacts_and_notes(db):
    a = _acc(db, 1)
    c = _contact(db, a)
    db.add(m.CrmNote(account_id=a.id, contact_id=c.id, body="n1"))
    db.add(m.CrmNote(account_id=a.id, body="n2"))
    db.commit()
    db.delete(a)
    db.commit()
    assert db.query(m.CrmContact).count() == 0 and db.query(m.CrmNote).count() == 0


# ------------------------------------------------------------------------------------------------ supresión (Ley 1581)
def _log(db, entity, entity_id, field="email"):
    db.add(m.CrmChangeLog(entity=entity, entity_id=entity_id, field_key=field, old_value="a@x.test", new_value="b@x.test", source="edit"))


def test_erasing_a_contact_removes_its_change_history_and_its_notes_but_not_the_rest(db):
    a = _acc(db, 1)
    ana, beto = _contact(db, a, "Ana"), _contact(db, a, "Beto")
    db.add_all([m.CrmNote(account_id=a.id, contact_id=ana.id, body="habló Ana"), m.CrmNote(account_id=a.id, contact_id=beto.id, body="habló Beto"), m.CrmNote(account_id=a.id, body="nota de la cuenta")])
    _log(db, "contact", ana.id)
    _log(db, "contact", ana.id, "phone")
    _log(db, "contact", beto.id)
    _log(db, "account", a.id, "name")
    db.commit()
    ana_id = ana.id
    counts = erase_contact(db, ana_id)
    db.commit()
    assert counts == {"contacts": 1, "notes": 1, "changes": 2}
    assert db.get(m.CrmContact, ana_id) is None
    assert db.query(m.CrmNote).filter_by(contact_id=ana_id).count() == 0
    assert db.query(m.CrmChangeLog).filter_by(entity="contact", entity_id=ana_id).count() == 0
    assert db.query(m.CrmContact).count() == 1 and db.query(m.CrmNote).count() == 2                      # Beto y la nota de la cuenta siguen
    assert db.query(m.CrmChangeLog).count() == 2                                                       # el de Beto y el de la cuenta
    assert erase_contact(db, ana_id) == {"contacts": 0, "notes": 0, "changes": 0}                      # repetir no falla


def test_erasing_an_account_removes_contacts_notes_and_every_history(db):
    a, b = _acc(db, 1), _acc(db, 2)
    ca, cb = _contact(db, a, "Ana"), _contact(db, b, "Beto")
    db.add_all([m.CrmNote(account_id=a.id, contact_id=ca.id, body="x"), m.CrmNote(account_id=a.id, body="y"), m.CrmNote(account_id=b.id, body="z")])
    _log(db, "account", a.id, "name")
    _log(db, "contact", ca.id)
    _log(db, "contact", cb.id)
    db.commit()
    aid = a.id
    counts = erase_account(db, aid)
    db.commit()
    assert counts == {"accounts": 1, "contacts": 1, "notes": 2, "changes": 2}
    assert db.get(m.CrmAccount, aid) is None and db.query(m.CrmContact).count() == 1 and db.query(m.CrmNote).count() == 1
    assert [(r.entity, r.entity_id) for r in db.query(m.CrmChangeLog).all()] == [("contact", cb.id)]
    assert erase_account(db, aid)["accounts"] == 0
