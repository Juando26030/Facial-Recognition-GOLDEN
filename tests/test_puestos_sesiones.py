"""Puestos de impresión configurados desde Parámetros (bloque 2) y política de sesiones por rol (bloque 3), 26-oct-2026. Migración 0072 (aditiva)."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import AppSetting, PrintDevice, PrintStation, SessionAudit, StaffUser
from app.timeutil import utcnow
from tests.conftest import login


@pytest.fixture()
def second():
    """Un SEGUNDO dispositivo (otro navegador: sus propias cookies) contra la misma aplicación."""
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture()
def env(client, factory, db):
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso")
    users = {n: factory.staff("digitador", n) for n in ("dig1", "dig2", "puesto")}
    for u in users.values():
        factory.authorize(ev, u)
    return ev, users


def _api_ok(c):
    return c.get("/api/session/ping")


# ---------------------------------------------------------------------------------------------------- bloque 2: configuración por puesto en el servidor
def test_the_station_settings_live_on_the_server_and_the_digitador_cannot_touch_them(client, env, db):
    ev, u = env
    login(client, "adm")
    body = {"print_station": True, "settings": {"mode": "driver", "noDialog": True, "pageWidthMm": 58.9, "dx": 1.2, "dy": -0.4, "usbSerial": "ABC123", "cut": False, "feedMm": 4, "rotation": "auto", "crop": True, "cropMode": "symmetric"}}
    r = client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json=body)
    assert r.status_code == 200 and r.json()["print_station"] is True and r.json()["settings"]["mode"] == "driver" and r.json()["settings"]["pageWidthMm"] == 58.9
    assert db.query(PrintStation).filter_by(event_id=ev.id, staff_user_id=u["puesto"].id).count() == 1
    client.cookies.clear(); login(client, "puesto")
    me = client.get(f"/api/events/{ev.id}/print-station/me").json()
    assert me["admin"] is False and me["station"] is True and me["settings"]["noDialog"] is True and me["settings"]["usbSerial"] == "ABC123"
    for method, path, payload in (("put", f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", {"settings": {"mode": "usb"}}), ("post", f"/api/print-stations/{u['puesto'].id}/release", None),
                                  ("get", "/api/settings/single-session", None), ("put", "/api/settings/single-session", {"enabled": False}), ("get", f"/api/events/{ev.id}/shared-print", None)):
        r = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
        assert r.status_code == 403, (method, path)                                                  # los endpoints de configuración rechazan a los roles sin permiso
    client.cookies.clear(); login(client, "adm")
    assert client.get(f"/api/events/{ev.id}/print-station/me").json()["admin"] is True
    r = client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": None})
    assert r.status_code == 200 and r.json()["settings"] is None and db.query(PrintStation).count() == 0       # sin fila: vuelve a lo de siempre


def test_station_settings_are_validated_and_only_an_admin_marks_the_station(client, env, factory, db):
    ev, u = env
    factory.staff("coordinador", "coord"); factory.authorize(ev, db.query(StaffUser).filter_by(username="coord").one())
    login(client, "coord")
    put = lambda settings, **extra: client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": settings, **extra})
    assert put({"mode": "raro"}).status_code == 400 and put({"pageWidthMm": 500}).status_code == 400 and put({"dx": 9}).status_code == 400 and put({"feedMm": -2}).status_code == 400
    assert put({"mode": "usb", "dx": 2}).status_code == 200
    assert put({"mode": "usb"}, print_station=True).status_code == 403                                 # la casilla es del admin
    assert put({"mode": "usb", "inventado": 1}).json()["settings"] == {"mode": "usb"}                  # solo claves conocidas


def test_a_station_without_a_row_keeps_working_as_today(client, env):
    ev, u = env
    login(client, "dig1")
    me = client.get(f"/api/events/{ev.id}/print-station/me").json()
    assert me == {"admin": False, "station": False, "settings": None}


# ---------------------------------------------------------------------------------------------------- bloque 3: sesiones
def test_admin_can_have_many_sessions_and_none_closes_the_other(client, second, env):
    login(client, "adm"); login(second, "adm")
    assert _api_ok(client).status_code == 200 and _api_ok(second).status_code == 200


def test_digitador_has_a_single_session_the_first_becomes_invalid_with_session_replaced(client, second, env, db):
    login(client, "dig1")
    assert _api_ok(client).status_code == 200
    login(second, "dig1")                                                                          # entra desde otro dispositivo
    assert _api_ok(second).status_code == 200
    r = _api_ok(client)
    assert r.status_code == 401 and r.json()["detail"] == "session_replaced"
    kinds = [a.result for a in db.query(SessionAudit).order_by(SessionAudit.id)]
    assert "reemplazada" in kinds and "cerrada" in kinds
    a = db.query(SessionAudit).first()
    assert a.device and a.browser and not hasattr(a, "ip")                                         # solo lo necesario: sin IP


def test_two_tabs_of_the_same_browser_share_the_session_and_stay_alive(client, env):
    login(client, "dig1")
    for _ in range(3):                                                                              # «pestañas»: la misma cookie
        assert _api_ok(client).status_code == 200
    login(client, "dig1")                                                                           # volver a entrar en el MISMO navegador no se expulsa a sí mismo
    assert _api_ok(client).status_code == 200


def test_a_session_created_before_the_change_stays_valid(client, second, env, db):
    login(client, "dig1")
    u = db.query(StaffUser).filter_by(username="dig1").one()
    assert u.session_token
    u.session_token = None; db.commit()                                                            # una cuenta sin token (anterior al cambio)
    assert _api_ok(client).status_code == 200                                                      # nadie queda fuera por desplegar
    login(second, "dig1")
    assert _api_ok(second).status_code == 200


def test_the_switch_off_returns_to_the_old_behaviour_and_the_env_var_wins(client, second, env, db, monkeypatch):
    db.add(AppSetting(key="single_session", value="0")); db.commit()
    login(client, "dig1"); login(second, "dig1")
    assert _api_ok(client).status_code == 200 and _api_ok(second).status_code == 200              # apagado: las dos viven
    assert db.query(StaffUser).filter_by(username="dig1").one().session_token is None
    monkeypatch.setenv("SINGLE_SESSION", "1")                                                      # la variable de entorno manda sobre el interruptor
    from app import sessions
    assert sessions.single_session_on(db) is True
    monkeypatch.setenv("SINGLE_SESSION", "0")
    db.query(AppSetting).delete(); db.commit()
    assert sessions.single_session_on(db) is False


def test_a_print_station_account_rejects_a_second_login_while_in_use_and_an_admin_can_force_it(client, second, env, db):
    ev, u = env
    p = u["puesto"]; p.print_station = True; db.commit()
    login(client, "puesto")
    assert _api_ok(client).status_code == 200
    db.add(PrintDevice(event_id=ev.id, staff_user_id=p.id, device_id="pc", last_seen_at=utcnow(), printer_connected=True)); db.commit()      # el puesto está imprimiendo ahora
    r = login(second, "puesto")
    assert r.status_code == 403 and "puesto de impresión" in r.text and "ya está en uso" in r.text
    assert _api_ok(client).status_code == 200                                                      # el puesto no se cierra
    assert "rechazada" in [a.result for a in db.query(SessionAudit)]
    adm = TestClient(client.app, follow_redirects=False)
    with adm:
        login(adm, "adm")
        assert adm.post(f"/api/print-stations/{p.id}/release").status_code == 200                  # solo un admin fuerza el cambio
    assert "forzada" in [a.result for a in db.query(SessionAudit)]
    assert _api_ok(client).status_code == 401                                                      # la sesión anterior se cerró
    assert login(second, "puesto").status_code == 302 and _api_ok(second).status_code == 200      # y ahora entra el otro dispositivo


def test_the_station_can_come_back_when_it_stopped_sending_signals_and_logout_frees_it(client, second, env, db):
    ev, u = env
    p = u["puesto"]; p.print_station = True; db.commit()
    login(client, "puesto")
    db.add(PrintDevice(event_id=ev.id, staff_user_id=p.id, device_id="pc", last_seen_at=utcnow() - timedelta(minutes=5), printer_connected=True)); db.commit()
    assert login(second, "puesto").status_code == 302                                              # sin señal hace 5 min: ya no está «en uso»
    second.post("/logout")
    assert db.query(StaffUser).filter_by(username="puesto").one().session_token is None             # cerrar sesión libera la cuenta


def test_the_impression_does_not_depend_on_the_session_of_another_device(client, second, env, db):
    """El celular del admin con la cuenta del puesto (admin: sesiones múltiples) no pisa el estado del puesto: lo cubre tests/test_impresion_compartida.py (latido por dispositivo)."""
    ev, u = env
    login(client, "adm"); login(second, "adm")
    assert _api_ok(client).status_code == 200 and _api_ok(second).status_code == 200


def test_session_audit_older_than_90_days_is_purged_by_the_ops_job(db):
    now = utcnow()
    db.add(SessionAudit(result="cerrada", device="móvil", browser="Chrome", created_at=now - timedelta(days=91)))
    db.add(SessionAudit(result="rechazada", device="computador", browser="Edge", created_at=now - timedelta(days=10)))
    db.commit()
    from app import ops_runner
    out = json.loads(ops_runner.purge())
    assert out["session_audit_rows"] == 1 and db.query(SessionAudit).count() == 1 and db.query(SessionAudit).first().result == "rechazada"


def test_the_guard_script_and_the_requester_message_are_in_place():
    import pathlib
    toast = pathlib.Path("static/js/toast.js").read_text(encoding="utf-8")
    assert "session_replaced" in toast and "gw:session-replaced" in toast and "/api/session/ping" in toast and "Tu sesión se cerró porque entraste con esta cuenta en otro dispositivo" in toast
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "Enviada al puesto ${route.printer_name}: se imprime cuando el puesto la confirme." in sp and "NO está listo para imprimir solo" not in sp
    assert "gw:session-replaced" in sp


# ---------------------------------------------------------------------------------------------------- 27-oct-2026: «Mostrar la configuración de impresión en el Registro» por puesto
def test_show_config_defaults_to_show_and_only_coordinator_or_more_changes_it(client, env, factory, db):
    ev, u = env
    login(client, "dig1")
    assert client.get(f"/api/events/{ev.id}/print-station/me").json()["settings"] is None          # sin configuración: «Mostrar» (lo decide la página: showConfig !== false)
    assert client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": {"showConfig": False}}).status_code == 403
    client.cookies.clear()
    factory.staff("coordinador", "coord"); factory.authorize(ev, db.query(StaffUser).filter_by(username="coord").one())
    login(client, "coord")
    r = client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": {"showConfig": False, "mode": "driver"}})
    assert r.status_code == 200 and r.json()["settings"] == {"showConfig": False, "mode": "driver"}
    assert client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": {"showConfig": "no"}}).status_code == 400
    other = factory.event("en_proceso"); factory.authorize(other, u["puesto"]); factory.authorize(other, db.query(StaffUser).filter_by(username="coord").one())
    client.cookies.clear(); login(client, "puesto")
    assert client.get(f"/api/events/{ev.id}/print-station/me").json()["settings"]["showConfig"] is False
    assert client.get(f"/api/events/{other.id}/print-station/me").json()["settings"] is None       # no se mezcla entre eventos
    client.cookies.clear(); login(client, "dig2")
    assert client.get(f"/api/events/{ev.id}/print-station/me").json()["settings"] is None          # ni entre puestos


def test_no_print_menu_visibility_rule_depends_on_the_role():
    import pathlib
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    body = sp[sp.index("  function render() {"):sp.index("  function stationLine() {")]
    assert "isAdmin" not in body and "role" not in body.lower().replace("rol de", "")             # ninguna regla de visibilidad depende del rol
    assert "const configShown = () => !(stationCfg && stationCfg.showConfig === false);" in sp    # por defecto: Mostrar
    for el in ("#spConnect", "#spQueue", "#spPrefs", "#spHostNote"):
        assert f"bar.querySelector('{el}').hidden = !shown" in body or f"bar.querySelector('{el}').hidden = !({'SHARED && shown' if el == '#spQueue' else 'shown && SHARED && driverOn() && !kiosk'})" in body
