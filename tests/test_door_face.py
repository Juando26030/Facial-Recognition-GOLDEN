"""B1 «Entrar con mi rostro» (app/routers/door.py): autoservicio, ingreso automático solo con coincidencia clara, nada guardado sin coincidencia, franja de supervisión,
«revisar», límite por equipo y contador numérico."""
import io
import json
from datetime import timedelta

import numpy as np
import pytest
from PIL import Image

from app import appmode, faces
from app.models import AccessLog, PersonChange, RateLimitEvent, SystemEvent, User
from app.routers import door
from app.storage import get_storage, photo_key
from app.timeutil import utcnow
from tests.conftest import accept, login


def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 120, 120)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def station(client, factory, db):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, face_door_enabled=True, face_door_liveness=False)      # la prueba de movimiento tiene sus propias pruebas (test_liveness.py)
    st = factory.staff("digitador", "puerta1")
    factory.authorize(ev, st)
    for uid in ("1001", "1002"):
        factory.person(ev, uid, f"P{uid}", "Prueba")
    login(client, "puerta1")
    return ev


def _ranked(monkeypatch, status, ranked):
    monkeypatch.setattr(faces, "recognize", lambda db, event, raw, ungated=False: (status, ranked))


def _scan(client, ev):
    return client.post("/api/door-face", data={"event_id": str(ev.id)}, files={"file": ("f.jpg", _jpg(), "image/jpeg")})


def _logs(db, ev):
    db.expire_all()
    return db.query(AccessLog).filter_by(event_id=ev.id).all()


# ------------------------------------------------------------------------------------------------------------------------------------ cuándo entra solo
def test_a_clear_match_registers_the_entry_automatically_without_showing_the_name(client, db, station, monkeypatch):
    _ranked(monkeypatch, "MATCH", [("1001", 0.42), ("1002", 0.61)])
    r = _scan(client, station)
    assert r.status_code == 200 and r.json() == {"result": "OK", "message": door.OK_MSG}
    assert "P1001" not in r.text                                                                           # la pantalla pública no muestra datos de la persona
    logs = _logs(db, station)
    assert len(logs) == 1 and logs[0].user_id == "1001" and logs[0].registration_method == "rostro_autoservicio"


@pytest.mark.parametrize("status, ranked", [
    ("MATCH", [("1001", 0.52), ("1002", 0.70)]),        # dentro de 0,55 pero por encima de 0,50: no entra solo
    ("MATCH", [("1001", 0.40), ("1002", 0.44)]),        # margen 0,04 < 0,06: dudoso
    ("NO_MATCH", []),
])
def test_without_a_clear_match_nobody_enters_and_the_message_is_the_auditors(client, db, station, monkeypatch, status, ranked):
    _ranked(monkeypatch, status, ranked)
    r = _scan(client, station)
    assert r.json() == {"result": "NO_MATCH", "message": door.NOT_FOUND_FACE} and "acreditación con tu cédula o QR" in door.NOT_FOUND_FACE
    assert _logs(db, station) == []


def test_no_face_asks_to_try_again(client, db, station, monkeypatch):
    _ranked(monkeypatch, "NO_FACE", [])
    assert _scan(client, station).json()["result"] == "NO_FACE" and _logs(db, station) == []


def test_a_second_scan_of_someone_already_inside_does_not_duplicate(client, db, station, monkeypatch):
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    _scan(client, station)
    r = _scan(client, station)
    assert r.json() == {"result": "ALREADY", "message": door.REPEAT_MSG} and len(_logs(db, station)) == 1


def test_nothing_is_stored_from_the_frame(client, db, station, monkeypatch):
    _ranked(monkeypatch, "NO_MATCH", [])
    before = {u.id: (u.face_encoding, get_storage().exists(photo_key(station.tenant_id, u.id))) for u in db.query(User)}
    _scan(client, station)
    db.expire_all()
    assert {u.id: (u.face_encoding, get_storage().exists(photo_key(station.tenant_id, u.id))) for u in db.query(User)} == before


def test_the_real_matrix_only_recognizes_people_who_accepted(client, db, station, monkeypatch):
    vec = np.random.default_rng(3).normal(0, 0.1, 128).round(6).tolist()
    for uid in ("1001", "1002"):
        u = db.query(User).filter_by(id=uid).one()
        u.face_encoding, u.is_biometric_enabled = json.dumps(vec), True
    db.commit()
    monkeypatch.setattr(faces, "extract", lambda image, **kw: vec)
    faces.clear_cache()
    assert _scan(client, station).json()["result"] == "NO_MATCH"                                           # nadie ha aceptado: nadie se reconoce
    accept(db, station, "1002")
    from app import faces_version
    faces_version.bump(db, event_ids=[station.id])
    db.commit()
    assert _scan(client, station).json()["result"] == "OK" and [lg.user_id for lg in _logs(db, station)] == ["1002"]


# ------------------------------------------------------------------------------------------------------------------------------------ interruptor, evento y límite
def test_the_door_only_works_with_the_switch_on_facial_on_and_the_event_in_progress(client, factory, db, station, monkeypatch):
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    station.face_door_enabled = False
    db.commit()
    assert _scan(client, station).status_code == 403
    station.face_door_enabled, station.status = True, "creado"
    db.commit()
    assert _scan(client, station).status_code == 403 and _logs(db, station) == []


def test_five_attempts_per_minute_per_station_without_storing_ip(client, db, station, monkeypatch):
    _ranked(monkeypatch, "NO_MATCH", [])
    for _ in range(door.DOOR_ATTEMPTS_PER_MIN):
        assert _scan(client, station).status_code == 200
    assert _scan(client, station).status_code == 429
    rows = db.query(RateLimitEvent).filter_by(kind="door_face").all()
    assert len(rows) == door.DOOR_ATTEMPTS_PER_MIN and all(r.ip is None for r in rows)
    for r in rows:
        r.created_at = utcnow() - timedelta(minutes=2)
    db.commit()
    assert _scan(client, station).status_code == 200


def test_the_door_endpoint_runs_in_the_biometric_service():
    assert "/api/door-face" in appmode.BIOMETRIC_PATHS
    assert not appmode.route_allowed("/api/door-face", mode="web") and appmode.route_allowed("/api/door-face", mode="biometria")


# ------------------------------------------------------------------------------------------------------------------------------------ supervisión y contador
def test_staff_see_recent_entries_with_the_registration_photo_and_can_revert_one(client, db, station, monkeypatch):
    get_storage().put(photo_key(station.tenant_id, "1001"), _jpg())
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    _scan(client, station)
    entries = client.get(f"/api/events/{station.id}/door-face/recent").json()["entries"]
    assert len(entries) == 1 and entries[0]["user_id"] == "1001" and entries[0]["name"] == "P1001 Prueba"
    log_id = entries[0]["log_id"]
    photo = client.get(f"/api/events/{station.id}/door-face/photo/{log_id}")
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg" and "no-store" in photo.headers["cache-control"]
    assert client.post(f"/api/events/{station.id}/door-face/revert/{log_id}").json() == {"reverted": True}
    assert _logs(db, station) == []
    ch = db.query(PersonChange).filter_by(user_id="1001").one()
    assert ch.new_value == "No registrado" and "rostro" in ch.detail
    assert client.get(f"/api/events/{station.id}/door-face/photo/{log_id}").status_code == 404            # ya no es una entrada por rostro


def test_the_photo_is_only_for_recent_face_entries(client, db, station):
    other = AccessLog(tenant_id=station.tenant_id, user_id="1001", record_type="Existente", event_id=station.id, registration_method="tradicional")
    old = AccessLog(tenant_id=station.tenant_id, user_id="1002", record_type="Existente", event_id=station.id, registration_method="rostro_autoservicio", timestamp=utcnow() - timedelta(hours=13))
    db.add_all([other, old])
    db.commit()
    get_storage().put(photo_key(station.tenant_id, "1001"), _jpg())
    get_storage().put(photo_key(station.tenant_id, "1002"), _jpg())
    assert client.get(f"/api/events/{station.id}/door-face/photo/{other.id}").status_code == 404
    assert client.get(f"/api/events/{station.id}/door-face/photo/{old.id}").status_code == 404


def test_the_counter_is_numeric_only(client, db, station, monkeypatch):
    for status, ranked in (("MATCH", [("1001", 0.31), ("1002", 0.70)]), ("NO_MATCH", []), ("NO_FACE", []), ("MATCH", [("1001", 0.31)])):
        _ranked(monkeypatch, status, ranked)
        _scan(client, station)
    st = client.get(f"/api/events/{station.id}/door-face/stats").json()
    assert (st["attempts"], st["matches"], st["no_match"], st["no_face"]) == (4, 2, 2, 1)
    assert st["distances"]["match"] == [0.31, 0.31] and st["auto_max_dist"] == 0.5
    details = [d for (d,) in db.query(SystemEvent.detail).filter_by(kind="door_face")]
    assert sorted(details)[0].split()[0] in ("match", "match_repeat", "no_match", "no_face") and "match d310 m390" in details
    assert not any("1001" in d or "P1001" in d for d in details)


def test_the_switch_lives_in_the_guided_step_and_needs_facial_without_lock(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    url = f"/api/events/{ev.id}/biometric-setup"
    assert client.put(url, json={"facial_enabled": False, "face_door_enabled": True}).status_code == 400
    ok = client.put(url, json={"facial_enabled": True, "aceptar_enabled": True, "face_door_enabled": True})
    assert ok.status_code == 200 and ok.json()["config"]["face_door_enabled"] is True
    assert client.put(url, json={"biometrics_locked": True}).json()["config"]["face_door_enabled"] is False
    assert 'id="ccFaceDoor"' in client.get(f"/kiosk/{ev.id}/parametros").text


def test_the_self_service_page_has_both_buttons_and_hides_the_face_one_offline(client, station):
    page = client.get(f"/kiosk/{station.id}/rostro").text
    assert "Entrar con mi rostro" in page and "Ingresar con cédula o QR" in page
    assert "navigator.onLine" in page and "golden-contingency" in page


# ------------------------------------------------------------------------------------------------------------------------------------ correcciones tras la prueba en staging
def test_someone_already_inside_sees_ya_habias_ingresado_and_the_strip_marks_it(client, db, station, monkeypatch):
    get_storage().put(photo_key(station.tenant_id, "1001"), _jpg())
    db.add(AccessLog(tenant_id=station.tenant_id, user_id="1001", record_type="Existente", event_id=station.id, registration_method="tradicional"))      # entró antes por cédula
    db.commit()
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    r = _scan(client, station)
    assert r.json() == {"result": "ALREADY", "message": "Ya habías ingresado."} and "P1001" not in r.text
    assert len(_logs(db, station)) == 1                                                                    # no se duplica
    entries = client.get(f"/api/events/{station.id}/door-face/recent").json()["entries"]
    assert len(entries) == 1 and entries[0]["repeat"] is True and entries[0]["name"] == "P1001 Prueba"
    assert client.get(f"/api/events/{station.id}/door-face/photo/{entries[0]['log_id']}").status_code == 200      # el digitador ve la foto de registro
    assert client.post(f"/api/events/{station.id}/door-face/revert/{entries[0]['log_id']}").status_code == 404    # la entrada por cédula no se revierte desde aquí
    events = [ref for (ref,) in db.query(SystemEvent.ref).filter_by(kind="door_face_repeat")]
    assert events == [f"{station.id}:{entries[0]['log_id']}"]                                              # solo números internos, sin cédula


def test_the_station_cap_is_high_and_the_per_person_limit_lives_in_the_screen(client, station):
    assert door.DOOR_ATTEMPTS_PER_MIN == 30
    page = client.get(f"/kiosk/{station.id}/rostro").text
    assert "MAX_MISSES = 2" in page and "No te encontramos en la lista con reconocimiento facial" in page


def test_parameters_warn_that_there_is_no_liveness_check_while_the_door_is_on(client, factory, db):
    factory.staff("coordinador", "coord9")
    ev = factory.event("en_proceso", facial_enabled=True, face_door_enabled=True)
    login(client, "coord9")
    assert "Sin prueba de vida: requiere supervisión constante" in client.get(f"/kiosk/{ev.id}/parametros").text
    ev.face_door_enabled = False
    db.commit()
    assert "Sin prueba de vida" not in client.get(f"/kiosk/{ev.id}/parametros").text


def test_after_a_revert_the_person_can_enter_again_by_face_and_the_new_entry_is_marked(client, db, station, monkeypatch):
    get_storage().put(photo_key(station.tenant_id, "1001"), _jpg())
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    assert _scan(client, station).json()["result"] == "OK"
    first = client.get(f"/api/events/{station.id}/door-face/recent").json()["entries"][0]
    assert client.post(f"/api/events/{station.id}/door-face/revert/{first['log_id']}").status_code == 200
    again = _scan(client, station)
    assert again.json()["result"] == "OK"                                                                  # revertir anula SOLO esa entrada
    entries = client.get(f"/api/events/{station.id}/door-face/recent").json()["entries"]
    assert entries[0]["after_revert"] is True and entries[0]["repeat"] is False and len(_logs(db, station)) == 1


def test_with_auto_print_the_face_entry_opens_the_badge_like_the_document_entry(client, db, station, monkeypatch):
    station.auto_print_badge = True
    db.commit()
    _ranked(monkeypatch, "MATCH", [("1001", 0.30)])
    r = _scan(client, station).json()
    assert r["result"] == "OK" and r["print_user_id"] == "1001"
    page = client.get(f"/kiosk/{station.id}/rostro").text
    assert "escarapela/imprimir" in page and "print-log" in page
    station.auto_print_badge = False
    db.commit()
    db.query(AccessLog).delete()
    db.commit()
    assert "print_user_id" not in _scan(client, station).json()


def test_the_door_screen_checks_the_server_actively_and_is_white(client, station):
    page = client.get(f"/kiosk/{station.id}/rostro").text
    assert "/health?t=" in page and "AbortController" in page and "setInterval(ping" in page and "setUp(false)" in page
    assert "background: #fff" in page


def test_registro_has_a_switch_to_open_the_door_screen_only_when_enabled(client, db, station):
    page = client.get(f"/kiosk/{station.id}/registro").text
    assert 'id="openDoorScreen"' in page and f"/kiosk/{station.id}/rostro" in page
    station.face_door_enabled = False
    db.commit()
    assert 'id="openDoorScreen"' not in client.get(f"/kiosk/{station.id}/registro").text


def test_the_door_screen_survives_a_reload_without_network_when_contingency_is_on(client, station, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "contingency_enabled", lambda: True)
    page = client.get(f"/kiosk/{station.id}/rostro").text
    assert "const CONTINGENCY = true" in page and "register('/kiosk/sw.js')" in page                       # el service worker guarda esta pantalla y la de Registro
    assert "const REGISTRO = `/kiosk/${EVENT_ID}/registro`" in page and "location.href = REGISTRO" in page    # sin conexión, «cédula o QR» lleva a Registro (contingencia)
    assert "let serverUp = navigator.onLine" in page and "Ingresar con cédula o QR (sin conexión)" in page
    assert "Sin conexión. Ingresa con tu cédula o QR en el modo sin conexión." in page


def test_with_contingency_off_the_door_screen_does_not_register_anything(client, station, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "contingency_enabled", lambda: False)
    assert "const CONTINGENCY = false" in client.get(f"/kiosk/{station.id}/rostro").text                   # en producción (contingencia apagada) todo esto queda inactivo
    sw = client.get("/kiosk/sw.js")
    assert "kiosk-sw-off" in sw.text or "unregister" in sw.text


def test_the_service_worker_serves_the_door_page_and_never_its_api():
    src = open("static/js/kiosk-sw.js", encoding="utf-8").read()
    assert "(registro|rostro)" in src and "/api/" not in src.split("const KIOSK_PAGE")[1].split("\n")[0]


def test_a_rejected_attempt_records_why_for_diagnosis_without_personal_data(client, db, station, monkeypatch):
    for status, ranked in (("MATCH", [("1001", 0.52), ("1002", 0.80)]), ("MATCH", [("1001", 0.40), ("1002", 0.44)]), ("NO_MATCH", [])):
        _ranked(monkeypatch, status, ranked)
        _scan(client, station)
    details = [d for (d,) in db.query(SystemEvent.detail).filter_by(kind="door_face").order_by(SystemEvent.id)]
    assert details == ["no_match d520 m280 far", "no_match d400 m40 doubtful", "no_match none"]
    st = client.get(f"/api/events/{station.id}/door-face/stats").json()
    assert st["reasons"] == {"far": 1, "doubtful": 1, "none": 1}
    newest = st["recent_attempts"][0]
    assert newest == {"at": newest["at"], "result": "no_match", "dist": None, "margin": None, "reason": "none"} and st["recent_attempts"][2]["dist"] == 0.52
    assert not any("1001" in d for d in details)
