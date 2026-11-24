"""23-nov-2026 (decisión de Juan David): se eliminó «por verificar». En /aceptar la selfie de quien acepta reemplaza la foto directamente y no queda ninguna foto pendiente."""
import pytest

from app import enroll
from app.storage import get_storage, photo_key
from tests.test_accept_link import _accept, _setup, engine, env  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("engine")

OLD = b"foto-de-registro-del-cliente"


def _keys(ev, uid="1001"):
    return photo_key(ev.tenant_id, uid), enroll.pending_photo_key(ev.tenant_id, uid)


def _with_old_photo(factory, db, **kw):
    ev, _u, _token = _setup(factory, db, **kw)
    cur, pend = _keys(ev)
    get_storage().put(cur, OLD)
    return ev, cur, pend


def test_the_selfie_replaces_the_registration_photo_directly_without_verification(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db)
    r = _accept(client, ev, "", cedula="1001")                                   # sin enlace personal: igual vale
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert get_storage().get(cur) != OLD and not get_storage().exists(pend)      # la selfie reemplazó la foto y no hay pendiente


def test_the_personal_trusted_link_replaces_directly(client, factory, db):
    ev, _u, token = _setup(factory, db, trusted=True)
    cur, pend = _keys(ev)
    get_storage().put(cur, OLD)
    assert _accept(client, ev, token).json()["verified"] is True
    assert get_storage().get(cur) != OLD and not get_storage().exists(pend)


def test_without_a_previous_photo_the_selfie_is_saved_directly(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    cur, pend = _keys(ev)
    assert not get_storage().exists(cur)
    assert _accept(client, ev, "", cedula="1001").status_code == 200
    assert get_storage().exists(cur) and not get_storage().exists(pend)
