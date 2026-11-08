"""D5 (decisión del dueño, 8-nov-2026): «Aceptación web cuando la base no trae fecha de nacimiento» es un AJUSTE del evento: `any` (el comportamiento de siempre) o `require_personal_link`
(sin el enlace personal del correo no se acepta con selfie). Eventos existentes: `any`; eventos nuevos (creados por la API): `require_personal_link`."""
import pytest

from app.models import AuditConsentLog
from app.routers import aceptar
from app.storage import get_storage, photo_key
from tests.conftest import login
from tests.test_accept_link import _accept, _setup, engine, env  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("engine")


def _no_birth(factory, db, mode, **kw):
    ev, u, token = _setup(factory, db, birth=None, accept_no_birth_mode=mode, **kw)
    return ev, u, token


def test_default_of_existing_events_is_any_and_keeps_todays_behavior(factory, db):
    ev, _u, _t = _no_birth(factory, db, "any")
    assert ev.accept_no_birth_mode == "any"


def test_any_mode_accepts_a_typed_adult_date_without_link_as_before(client, factory, db):
    ev, _u, _t = _no_birth(factory, db, "any")
    r = _accept(client, ev, "", cedula="1001")
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_require_mode_refuses_the_cedula_only_path_when_the_base_has_no_birth_date(client, factory, db):
    ev, _u, _t = _no_birth(factory, db, "require_personal_link")
    r = _accept(client, ev, "", cedula="1001")
    assert r.status_code == 403 and r.json()["detail"] == aceptar.NEED_LINK_MSG and "enlace personal" in r.json()["detail"]
    assert db.query(AuditConsentLog).count() == 0                                         # nada se registró
    assert not get_storage().exists(photo_key(ev.tenant_id, "1001"))                      # ni se guardó selfie
    chk = client.post(f"/api/aceptar/{ev.event_code}/check", data={"cedula": "1001", "birth_date": "1990-04-02"})
    assert chk.status_code == 403                                                           # tampoco avanza a la cámara


def test_require_mode_still_accepts_with_the_personal_link(client, factory, db):
    ev, _u, token = _no_birth(factory, db, "require_personal_link")
    r = _accept(client, ev, token)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert db.query(AuditConsentLog).filter_by(user_id="1001").count() == 1


def test_require_mode_does_not_change_people_whose_base_has_a_birth_date(client, factory, db):
    from datetime import date
    ev, _u, _t = _setup(factory, db, birth=date(1990, 4, 2), accept_no_birth_mode="require_personal_link")
    r = _accept(client, ev, "", cedula="1001", birth="1990-04-02")
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_the_refusals_count_against_that_cedula_like_other_failures(client, factory, db):
    ev, _u, _t = _no_birth(factory, db, "require_personal_link")
    codes = [_accept(client, ev, "", cedula="1001").status_code for _ in range(aceptar.CEDULA_MAX_FAILS + 1)]
    assert codes[:aceptar.CEDULA_MAX_FAILS] == [403] * aceptar.CEDULA_MAX_FAILS and codes[-1] == 429


def test_new_events_default_to_require_personal_link_and_the_setting_is_editable(client, factory, db):
    from app.models import Event
    from tests.test_coordinador_crea_eventos import _payload
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    r = client.post("/api/events", json=_payload(coord.id))
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert db.get(Event, eid).accept_no_birth_mode == "require_personal_link"            # evento NUEVO
    cfg = client.get(f"/api/events/{eid}/biometric-setup").json()["config"]
    assert cfg["accept_no_birth_mode"] == "require_personal_link"
    bad = client.put(f"/api/events/{eid}/biometric-setup", json={"accept_no_birth_mode": "cualquiera"})
    assert bad.status_code == 400 and "fecha de nacimiento" in bad.json()["detail"]
    ok = client.put(f"/api/events/{eid}/biometric-setup", json={"accept_no_birth_mode": "any"})
    assert ok.status_code == 200 and ok.json()["config"]["accept_no_birth_mode"] == "any"
    db.expire_all()
    assert db.get(Event, eid).accept_no_birth_mode == "any"


def test_the_parameters_screen_shows_the_setting_with_help_in_spanish():
    src = open("templates/kiosk_parametros.html", encoding="utf-8").read()
    assert 'id="ccNoBirth"' in src and "Exigir el enlace personal del correo" in src and "accept_no_birth_mode" in src
    assert "onclick=" not in src[src.index('id="ccNoBirth"') - 200:src.index('id="ccNoBirth"') + 2500]
