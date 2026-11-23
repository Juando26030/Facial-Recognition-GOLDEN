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
def test_the_station_keeps_only_reader_only_and_show_hide_and_the_digitador_cannot_touch_them(client, env, db):
    ev, u = env
    db.add(PrintStation(event_id=ev.id, staff_user_id=u["puesto"].id, settings_json=json.dumps({"mode": "driver", "noDialog": True, "pageWidthMm": 60, "rotation": 90})))
    db.commit()                                                                                    # lo guardado antes (63a2a8a)
    login(client, "adm")
    r = client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"print_station": True, "settings": {"readerOnly": True, "showConfig": False, "mode": "usb", "dx": 2}})
    assert r.status_code == 200 and r.json()["print_station"] is True
    saved = r.json()["settings"]
    assert saved["readerOnly"] is True and saved["showConfig"] is False
    assert saved["mode"] == "driver" and saved["pageWidthMm"] == 60 and "dx" not in saved       # lo viejo NO se borra (se ignora); lo nuevo de impresión no se guarda
    client.cookies.clear(); login(client, "puesto")
    me = client.get(f"/api/events/{ev.id}/print-station/me").json()
    assert me["admin"] is False and me["station"] is True and me["settings"]["readerOnly"] is True
    for method, path, payload in (("put", f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", {"settings": {"readerOnly": False}}), ("post", f"/api/print-stations/{u['puesto'].id}/release", None),
                                  ("get", "/api/settings/single-session", None), ("put", "/api/settings/single-session", {"enabled": False}), ("get", f"/api/events/{ev.id}/shared-print", None)):
        r = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
        assert r.status_code == 403, (method, path)                                                  # los endpoints de configuración rechazan a los roles sin permiso
    client.cookies.clear(); login(client, "adm")
    r = client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": None})
    assert r.status_code == 200 and r.json()["settings"] is None and db.query(PrintStation).count() == 0       # «Quitar configuración»: vuelve a lo de siempre


def test_station_settings_are_validated_and_only_an_admin_marks_the_station(client, env, factory, db):
    ev, u = env
    factory.staff("coordinador", "coord"); factory.authorize(ev, db.query(StaffUser).filter_by(username="coord").one())
    login(client, "coord")
    put = lambda settings, **extra: client.put(f"/api/events/{ev.id}/print-stations/{u['puesto'].id}", json={"settings": settings, **extra})
    assert put({"showConfig": "no"}).status_code == 400 and put({"readerOnly": 1}).status_code == 400
    assert put({"readerOnly": True}).status_code == 200
    assert put({"readerOnly": True}, print_station=True).status_code == 403                        # la casilla es del admin
    assert put({"readerOnly": True, "mode": "raro", "inventado": 1}).json()["settings"] == {"readerOnly": True}      # lo de impresión ya no se guarda


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
    from app import sessions
    assert db.query(StaffUser).filter_by(username="puesto").one().session_token.startswith(sessions.FREE_PREFIX)    # cerrar sesión libera la cuenta (S2: con un token «libre», no NULL)
    assert login(client, "puesto").status_code == 302                                              # y otro equipo entra sin esperar


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
    assert r.status_code == 200 and r.json()["settings"] == {"showConfig": False}
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
    assert "bar.querySelector('#spConnect').hidden = !shown ||" in body and "bar.querySelector('#spQueue').hidden = !(SHARED && shown)" in body and "bar.querySelector('#spPrefs').hidden = !shown" in body


# ---------------------------------------------------------------------------------------------------- 29-oct-2026: la cuenta que ATIENDE a otros equipos también se protege
def _host_env(env, db):
    from app.models import PrintRoute
    ev, u = env
    host = u["puesto"]
    db.add(PrintRoute(event_id=ev.id, staff_user_id=u["dig1"].id, printer_staff_id=host.id)); db.commit()       # dig1 imprime en el equipo de «puesto»
    return ev, u, host


def test_an_account_that_serves_other_computers_rejects_a_login_from_another_device_while_it_prints(client, second, env, db):
    ev, u, host = _host_env(env, db)
    login(client, "puesto")
    db.add(PrintDevice(event_id=ev.id, staff_user_id=host.id, device_id="pc", last_seen_at=utcnow(), printer_connected=True)); db.commit()        # imprime ahora
    r = login(second, "puesto")
    assert r.status_code == 403 and "imprimiendo para otros equipos" in r.text and "en otro dispositivo" in r.text and "libere" in r.text
    assert _api_ok(client).status_code == 200                                                      # la sesión del anfitrión no se cierra
    assert "rechazada" in [a.result for a in db.query(SessionAudit)]
    assert login(client, "puesto").status_code == 302 and _api_ok(client).status_code == 200      # el MISMO navegador puede volver a entrar (reinicio de pestaña)


def test_the_host_is_released_by_itself_after_60_seconds_without_signal_and_an_admin_can_release_it(client, second, env, db):
    ev, u, host = _host_env(env, db)
    login(client, "puesto")
    dev = PrintDevice(event_id=ev.id, staff_user_id=host.id, device_id="pc", last_seen_at=utcnow(), printer_connected=True)
    db.add(dev); db.commit()
    assert login(second, "puesto").status_code == 403
    adm = TestClient(client.app, follow_redirects=False)
    with adm:
        login(adm, "adm")
        assert adm.post(f"/api/print-stations/{host.id}/release").status_code == 200              # un admin la libera
    assert login(second, "puesto").status_code == 302                                              # y el otro dispositivo entra
    second.post("/logout")
    login(client, "puesto")
    db.refresh(dev); dev.last_seen_at = utcnow() - timedelta(seconds=61); db.commit()
    assert login(second, "puesto").status_code == 302                                              # sin señal hace 61 s: se libera sola


def test_accounts_that_do_not_serve_anyone_and_admins_keep_the_old_behaviour(client, second, env, db):
    ev, u, host = _host_env(env, db)
    login(client, "dig2")
    db.add(PrintDevice(event_id=ev.id, staff_user_id=u["dig2"].id, device_id="pc2", last_seen_at=utcnow(), printer_connected=True)); db.commit()        # con impresora, pero NO atiende a nadie
    assert login(second, "dig2").status_code == 302 and _api_ok(client).status_code == 401        # sesión única de siempre: la primera se reemplaza
    c1, c2 = TestClient(client.app, follow_redirects=False), TestClient(client.app, follow_redirects=False)
    with c1, c2:
        login(c1, "adm"); login(c2, "adm")
        assert _api_ok(c1).status_code == 200 and _api_ok(c2).status_code == 200                  # admin: sesiones múltiples sin límite


# ---------------------------------------------------------------------------------------------------- 20-nov-2026: sesión única SOLO para las cuentas temporales (digitador y cliente)
def test_the_single_session_policy_is_only_for_temporary_accounts():
    from types import SimpleNamespace as NS

    from app import sessions
    for role in ("digitador", "cliente"):
        assert sessions.policy(NS(role=role, print_station=False)) == "single"
        assert sessions.policy(NS(role=role, print_station=True)) == "station"
    for role in ("admin", "super_admin", "coordinador", "comercial"):
        assert sessions.policy(NS(role=role, print_station=False)) == "multi"
        assert sessions.policy(NS(role=role, print_station=True)) == "multi"          # ni la protección de «puesto en uso» les aplica
    assert sessions.ADMIN_ROLES == ("admin", "super_admin")                              # lo exclusivo del admin (liberar puestos, revocar al cerrar sesión) no se amplió


def test_coordinador_and_comercial_can_be_open_on_many_devices_at_once(client, second, env, factory, db):
    factory.staff("coordinador", "coord2"); factory.staff("comercial", "com2")
    for name in ("coord2", "com2"):
        c1, c2 = TestClient(client.app, follow_redirects=False), TestClient(client.app, follow_redirects=False)
        with c1, c2:
            login(c1, name); login(c2, name)
            assert _api_ok(c1).status_code == 200 and _api_ok(c2).status_code == 200
            c2.post("/logout")
            assert _api_ok(c1).status_code == 200                                         # cerrar sesión en un equipo NO cierra el otro (solo el admin revoca todas)


def test_the_temporary_client_account_keeps_a_single_session(client, second, env, factory, db):
    cli = factory.staff("digitador", "cli-prueba")
    cli.client_temp = True
    db.commit()
    factory.authorize(env[0], cli)
    login(client, "cli-prueba"); login(second, "cli-prueba")
    assert _api_ok(second).status_code == 200
    r = _api_ok(client)
    assert r.status_code == 401 and r.json()["detail"] == "session_replaced"
