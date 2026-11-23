"""Hallazgo 5 de la revisión de seguridad (22-nov-2026), con base: en /aceptar la selfie de quien NO está verificada no pisa la foto de registro existente (queda «pendiente»),
salvo que el evento haya apagado «Verificar antes de reemplazar la foto». Las pruebas puras/de texto están en tests/test_foto_pendiente_puro.py."""
import pytest

from app import enroll, privacy
from app.models import Event
from app.storage import get_storage, photo_key
from tests.conftest import login
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


def test_the_new_column_defaults_to_active_and_the_default_is_the_safe_flow(factory, db):
    ev, _u, _t = _setup(factory, db)
    db.refresh(ev)
    assert ev.accept_verify_photo is True


def test_a_stranger_with_cedula_and_birth_date_cannot_replace_the_registration_photo(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db)
    r = _accept(client, ev, "", cedula="1001")                                   # sin enlace personal: no está verificada
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["verified"] is False
    assert get_storage().get(cur) == OLD                                          # la foto vigente quedó intacta
    assert get_storage().exists(pend)                                             # la selfie quedó aparte, pendiente


def test_verifying_the_person_keeps_both_photos_and_removes_the_pending(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db)
    _accept(client, ev, "", cedula="1001")
    selfie = get_storage().get(pend)
    factory.staff("super_admin", "dueno")
    login(client, "dueno")
    assert client.post(f"/api/events/{ev.id}/web-acceptance/1001/verify").json() == {"verified": True}
    sel = enroll.selfie_photo_key(ev.tenant_id, "1001")
    assert get_storage().get(cur) == OLD                                          # 23-nov: la de registro SIGUE vigente (no se reemplaza)
    assert get_storage().get(sel) == selfie and selfie != OLD                     # y la selfie verificada se conserva como segunda foto
    assert not get_storage().exists(pend)                                         # la pendiente desapareció


def test_the_personal_trusted_link_replaces_directly(client, factory, db):
    ev, _u, token = _setup(factory, db, trusted=True)
    cur, pend = _keys(ev)
    get_storage().put(cur, OLD)
    assert _accept(client, ev, token).json()["verified"] is True
    assert get_storage().get(cur) != OLD and not get_storage().exists(pend)


def test_with_the_setting_off_the_selfie_replaces_the_photo_as_before(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db, accept_verify_photo=False)
    assert _accept(client, ev, "", cedula="1001").status_code == 200
    assert get_storage().get(cur) != OLD and not get_storage().exists(pend)


def test_without_a_previous_photo_the_selfie_is_saved_directly(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    cur, pend = _keys(ev)
    assert not get_storage().exists(cur)
    assert _accept(client, ev, "", cedula="1001").status_code == 200
    assert get_storage().exists(cur) and not get_storage().exists(pend)


def test_the_setting_is_saved_from_parametros_and_listed_in_the_config(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    factory.staff("super_admin", "dueno")
    login(client, "dueno")
    r = client.put(f"/api/events/{ev.id}/biometric-setup", json={"accept_verify_photo": False})
    assert r.status_code == 200 and r.json()["config"]["accept_verify_photo"] is False
    db.expire_all()
    assert db.get(Event, ev.id).accept_verify_photo is False
    assert client.get(f"/api/events/{ev.id}/biometric-setup").json()["config"]["accept_verify_photo"] is False


def test_the_pending_photo_alone_is_not_a_registration_photo_for_the_operator(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db)
    _accept(client, ev, "", cedula="1001")
    get_storage().delete(cur)
    assert enroll.status(db, ev.tenant_id, "1001") == "none"                      # la pendiente sola no cuenta como foto de registro


def test_erasing_the_person_removes_both_photos(client, factory, db):
    ev, cur, pend = _with_old_photo(factory, db)
    _accept(client, ev, "", cedula="1001")
    assert get_storage().exists(cur) and get_storage().exists(pend)
    privacy.purge_person(db, ev.tenant_id, "1001")
    assert not get_storage().exists(cur) and not get_storage().exists(pend)
