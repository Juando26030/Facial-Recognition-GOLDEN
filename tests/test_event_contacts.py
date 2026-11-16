"""Contactos del cliente en el evento (16-nov-2026). DATOS SINTÉTICOS."""
import pytest

from app import event_contacts as ec


def test_clean_rules():
    assert ec.clean(None) == [] and ec.clean([]) == []
    out = ec.clean([{"name": " Ana ", "email": "ANA@x.co", "phone": "300", "note": "Jefe de compras"}, {"name": "Luis"}])
    assert [o["is_primary"] for o in out] == [True, False] and out[0]["name"] == "Ana" and out[1]["email"] is None
    out = ec.clean([{"name": "A"}, {"name": "B", "is_primary": True}])
    assert [o["is_primary"] for o in out] == [False, True]
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": "A", "is_primary": True}, {"name": "B", "is_primary": True}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": ""}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": "A", "email": "no-es-correo"}])
    with pytest.raises(ec.ContactError):
        ec.clean([{"name": str(i)} for i in range(ec.MAX_CONTACTS + 1)])


def test_clean_drops_foreign_crm_ids():
    out = ec.clean([{"name": "A", "crm_contact_id": 5}, {"name": "B", "crm_contact_id": 9}], {5})
    assert out[0]["crm_contact_id"] == 5 and out[1]["crm_contact_id"] is None


def test_replace_copy_and_primary(db, factory):
    pytest.importorskip("sqlalchemy")
    from tests.test_event_transfer import _build
    ev = _build(db, factory)
    ec.replace(db, ev, [{"name": "Ana", "email": "ana@x.co", "note": "Compras"}, {"name": "Luis", "phone": "300"}])
    db.commit()
    assert [c["name"] for c in ec.list_for(db, ev.id)] == ["Ana", "Luis"]
    assert ec.primary(db, ev.id) == {"name": "Ana", "email": "ana@x.co", "phone": ""}
    ec.replace(db, ev, [{"name": "Luis", "phone": "300"}])                       # principal sin correo: nada que enviar
    assert ec.primary(db, ev.id) is None and len(ec.list_for(db, ev.id)) == 1
    other = _build(db, factory)
    assert ec.copy_to(db, ev.id, other.id) == 1 and ec.list_for(db, other.id)[0]["is_primary"] is True
