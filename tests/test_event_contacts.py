"""Contactos del cliente en el evento (16-nov-2026). DATOS SINTÉTICOS."""
import pytest

from app import event_contacts as ec


def test_clean_rules():
    assert ec.clean(None) == [] and ec.clean([]) == []
    out = ec.clean([{"name": " Ana ", "email": "ANA@x.co", "phone": "300", "note": "Jefe de compras"}, {"name": "Luis", "crm_contact_id": 7}], {7})
    assert [o["is_primary"] for o in out] == [True, False] and out[0]["name"] == "Ana" and out[1]["email"] is None
    out = ec.clean([{"name": "A", "email": "a@x.co", "phone": "1"}, {"name": "B", "email": "b@x.co", "phone": "2", "is_primary": True}])
    assert [o["is_primary"] for o in out] == [False, True]
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": "A", "email": "a@x.co", "phone": "1", "is_primary": True}, {"name": "B", "email": "b@x.co", "phone": "2", "is_primary": True}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": ""}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": "A", "email": "no-es-correo"}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": str(i), "email": "a@x.co", "phone": "1"} for i in range(ec.MAX_CONTACTS + 1)])
    with pytest.raises(ec.ContactError):                                  # a mano: teléfono y correo obligatorios
        ec.clean([{"name": "Solo nombre"}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": "Sin correo", "phone": "300"}])


def test_clean_drops_foreign_crm_ids():
    out = ec.clean([{"name": "A", "crm_contact_id": 5}, {"name": "B", "crm_contact_id": 9, "email": "b@x.co", "phone": "2"}], {5})
    assert out[0]["crm_contact_id"] == 5 and out[1]["crm_contact_id"] is None


def test_replace_copy_and_primary(db, factory):
    pytest.importorskip("sqlalchemy")
    from tests.test_event_transfer import _build
    ev = _build(db, factory)
    ec.replace(db, ev, [{"name": "Ana", "email": "ana@x.co", "phone": "301", "note": "Compras"}, {"name": "Luis", "phone": "300", "email": "luis@x.co"}])
    db.commit()
    assert [c["name"] for c in ec.list_for(db, ev.id)] == ["Ana", "Luis"]
    assert ec.primary(db, ev.id) == {"name": "Ana", "email": "ana@x.co", "phone": "301"}
    ec.replace(db, ev, [{"name": "Luis", "phone": "300", "email": "luis@x.co"}])
    assert ec.primary(db, ev.id)["email"] == "luis@x.co" and len(ec.list_for(db, ev.id)) == 1
    other = _build(db, factory)
    assert ec.copy_to(db, ev.id, other.id) == 1 and ec.list_for(db, other.id)[0]["is_primary"] is True


def test_inactive_contacts_are_not_offered():
    class C:                                                                    # solo lo que mira _is_inactive
        def __init__(self, f, l=""):
            self.first_name, self.last_name = f, l
    assert ec._is_inactive(C("INACTIVOBELKIS", "ARZOLA")) and ec._is_inactive(C("XIMENA RODRIGUEZ (inactivo)")) and ec._is_inactive(C("Inactivo -CESAR QUINTERO"))
    assert not ec._is_inactive(C("Viviana", "Rubio"))
