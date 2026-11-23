"""Cierre de sesión por inactividad del personal (app/idle.py, docs/22_SESION_INACTIVIDAD.md): el servidor lo hace cumplir con la última actividad guardada en la cookie de sesión."""
import pytest

from app import idle
from app.models import Event
from tests.conftest import login

HTML = {"accept": "text/html,application/xhtml+xml"}
PASSIVE = {"X-Gw-Passive": "1"}


@pytest.fixture()
def clock(monkeypatch):
    """Reloj falso: `clock.t` son los segundos «de ahora» para app/idle.py."""
    class C:
        t = 1_800_000_000

        def advance(self, minutes=0, seconds=0):
            self.t += minutes * 60 + seconds
    c = C()
    monkeypatch.setattr(idle, "now", lambda: c.t)
    monkeypatch.delenv("SESSION_IDLE_MINUTES", raising=False)
    return c


def _staff(client, factory, role="digitador", username="dig", event=None):
    ev = event or factory.event("en_proceso")
    s = factory.staff(role, username)
    factory.authorize(ev, s)
    assert login(client, username).status_code == 302
    return ev, s


def test_default_is_ten_minutes_and_env_overrides(monkeypatch):
    monkeypatch.delenv("SESSION_IDLE_MINUTES", raising=False)
    assert idle.general_minutes() == 10
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "25")
    assert idle.general_minutes() == 25
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "xx")
    assert idle.general_minutes() == 10
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")
    assert idle.general_minutes() == 0


def test_session_survives_under_ten_minutes_and_dies_after(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=9, seconds=50)
    assert client.get("/api/ping-auth").status_code == 200           # una llamada de fondo no renueva, pero todavía vale
    clock.advance(seconds=20)                                        # ya pasaron 10 min y 10 s desde el inicio de sesión
    r = client.get("/api/ping-auth")
    assert r.status_code == 401 and r.json()["detail"] == "session_expired"
    assert client.get("/api/ping-auth").status_code == 401           # la sesión quedó borrada


def test_expired_page_redirects_to_login_with_message(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=11)
    r = client.get("/", headers=HTML)
    assert r.status_code == 302 and r.headers["location"] == "/login?expirada=1"
    page = client.get("/login?expirada=1")
    assert page.status_code == 200 and "Tu sesión se cerró por inactividad" in page.text


def test_background_polls_do_not_renew_the_session(client, factory, clock):
    _staff(client, factory)
    for _ in range(5):                                               # sondeos cada 2 min durante 10 min: ninguno cuenta como uso
        clock.advance(minutes=2)
        client.get("/api/ping-auth", headers=PASSIVE)
        client.get("/api/session/idle")
    clock.advance(seconds=30)
    assert client.get("/api/ping-auth").status_code == 401


def test_idle_info_endpoint_is_passive(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=4)
    j = client.get("/api/session/idle").json()
    assert j["enabled"] is True and j["idle_seconds"] == 600 and j["remaining"] == 360 and j["warn_seconds"] == 60
    clock.advance(minutes=1)
    assert client.get("/api/session/idle").json()["remaining"] == 300        # consultar no renovó nada


def test_touch_renews_the_session(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=9)
    j = client.post("/api/session/touch").json()
    assert j["remaining"] == 600
    clock.advance(minutes=9)
    assert client.get("/api/ping-auth").status_code == 200
    clock.advance(minutes=2)
    assert client.get("/api/ping-auth").status_code == 401


def test_touch_marked_passive_does_not_renew(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=9)
    client.post("/api/session/touch", headers=PASSIVE)
    clock.advance(minutes=2)
    assert client.get("/api/ping-auth").status_code == 401


def test_page_navigation_renews_the_session(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=9)
    assert client.get("/", headers=HTML).headers.get("location") != "/login?expirada=1"
    clock.advance(minutes=9)
    assert client.get("/api/ping-auth").status_code == 200


def test_touch_after_expiry_is_401_and_without_session_is_401(client, factory, clock):
    assert client.post("/api/session/touch").status_code == 401
    assert client.get("/api/session/idle").status_code == 401
    _staff(client, factory)
    clock.advance(minutes=11)
    r = client.post("/api/session/touch")
    assert r.status_code == 401 and r.json()["detail"] == "session_expired"


def test_env_value_applies(client, factory, clock, monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "3")
    _staff(client, factory)
    clock.advance(minutes=2, seconds=50)
    assert client.get("/api/ping-auth").status_code == 200
    clock.advance(seconds=20)
    assert client.get("/api/ping-auth").status_code == 401


def test_general_zero_turns_it_off(client, factory, clock, monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")
    _staff(client, factory)
    clock.advance(minutes=600)
    assert client.get("/api/ping-auth").status_code == 200
    assert client.get("/api/session/idle").json() == {"enabled": False}


def test_event_in_progress_uses_its_own_time(client, factory, db, clock):
    ev = factory.event("en_proceso", idle_minutes=20)
    _staff(client, factory, event=ev)
    assert client.get(f"/kiosk/{ev.id}/registro", headers=HTML).status_code == 200
    j = client.get("/api/session/idle").json()
    assert j["idle_seconds"] == 1200 and j["event_limit"] is True
    clock.advance(minutes=15)
    assert client.get("/api/ping-auth").status_code == 200           # con 10 min ya habría muerto
    clock.advance(minutes=6)
    assert client.get("/api/ping-auth").status_code == 401


def test_event_time_only_while_in_progress(client, factory, db, clock):
    ev = factory.event("creado", idle_minutes=30)
    _staff(client, factory, role="coordinador", username="coord", event=ev)
    r = client.get(f"/kiosk/{ev.id}/parametros", headers=HTML)
    assert r.status_code == 200
    assert client.get("/api/session/idle").json()["idle_seconds"] == 600     # creado: rige el general
    ev.status = "en_proceso"
    db.commit()
    client.get(f"/kiosk/{ev.id}/parametros", headers=HTML)
    assert client.get("/api/session/idle").json()["idle_seconds"] == 1800


def test_leaving_the_event_goes_back_to_the_general_time(client, factory, clock):
    ev = factory.event("en_proceso", idle_minutes=30)
    _staff(client, factory, event=ev)
    client.get(f"/kiosk/{ev.id}/registro", headers=HTML)
    assert client.get("/api/session/idle").json()["idle_seconds"] == 1800
    client.get("/", headers=HTML)                                    # otra página que no es de un evento
    assert client.get("/api/session/idle").json()["idle_seconds"] == 600


def test_set_idle_minutes_validates_range_and_blank(client, factory, db):
    ev = factory.event("en_proceso")
    c = factory.staff("coordinador", "coord")
    factory.authorize(ev, c)
    login(client, "coord")
    for good in (5, 30, 60, "45"):
        r = client.put(f"/api/events/{ev.id}/idle-minutes", json={"value": good})
        assert r.status_code == 200 and r.json()["idle_minutes"] == int(good)
    db.expire_all()
    assert db.get(Event, ev.id).idle_minutes == 45
    for bad in (0, 4, 61, -5, "abc", 7.5, True):
        r = client.put(f"/api/events/{ev.id}/idle-minutes", json={"value": bad})
        assert r.status_code == 400, bad
    db.expire_all()
    assert db.get(Event, ev.id).idle_minutes == 45
    for blank in (None, ""):
        assert client.put(f"/api/events/{ev.id}/idle-minutes", json={"value": 20}).status_code == 200
        r = client.put(f"/api/events/{ev.id}/idle-minutes", json={"value": blank})
        assert r.status_code == 200 and r.json()["idle_minutes"] is None
    db.expire_all()
    assert db.get(Event, ev.id).idle_minutes is None


def test_digitador_cannot_set_idle_minutes(client, factory):
    ev, _ = _staff(client, factory)
    assert client.put(f"/api/events/{ev.id}/idle-minutes", json={"value": 20}).status_code == 403


def test_parameters_screen_shows_the_field_and_the_value(client, factory):
    ev = factory.event("en_proceso", idle_minutes=25)
    c = factory.staff("coordinador", "coord")
    factory.authorize(ev, c)
    login(client, "coord")
    html = client.get(f"/kiosk/{ev.id}/parametros", headers=HTML).text
    assert 'id="idleMinutes"' in html and 'value="25"' in html and "General: 10" in html


def test_print_station_with_event_in_progress_is_exempt_with_expiry(client, factory, clock, monkeypatch):
    monkeypatch.delenv("IDLE_EXEMPT_HOURS", raising=False)
    factory.event("en_proceso")
    factory.staff("digitador", "impresora", print_station=True)
    assert login(client, "impresora").status_code == 302
    clock.advance(minutes=300)
    assert client.get("/api/ping-auth").status_code == 200
    assert client.get("/api/session/idle").json() == {"enabled": False}
    clock.advance(minutes=60 * 12)                                   # pasadas las 12 h de la exención rige el tiempo general
    assert client.get("/api/ping-auth").status_code == 401


def test_print_station_without_event_in_progress_is_not_exempt(client, factory, clock):
    factory.event("finalizado")
    factory.staff("digitador", "impresora", print_station=True)
    assert login(client, "impresora").status_code == 302
    clock.advance(minutes=11)
    assert client.get("/api/ping-auth").status_code == 401


def _host_with_route(factory, db, status="en_proceso", shared=True):
    from app.models import PrintRoute
    ev = factory.event(status)
    ev.shared_print_enabled = shared
    host = factory.staff("coordinador", "anfitrion")
    other = factory.staff("digitador", "otro")
    db.add(PrintRoute(event_id=ev.id, staff_user_id=other.id, printer_staff_id=host.id))
    db.commit()
    return host


def test_host_with_shared_print_in_running_event_is_exempt(client, factory, db, clock):
    _host_with_route(factory, db)
    assert login(client, "anfitrion").status_code == 302
    clock.advance(minutes=120)
    assert client.get("/api/ping-auth").status_code == 200
    assert client.get("/api/session/idle").json() == {"enabled": False}


@pytest.mark.parametrize("status,shared", [("finalizado", True), ("en_proceso", False)])
def test_host_with_stale_route_is_not_exempt(client, factory, db, clock, status, shared):
    _host_with_route(factory, db, status=status, shared=shared)
    assert login(client, "anfitrion").status_code == 302
    clock.advance(minutes=11)
    assert client.get("/api/ping-auth").status_code == 401


def test_admin_has_no_special_treatment(client, factory, clock):
    factory.event("en_proceso")
    factory.staff("super_admin", "dueno")
    assert login(client, "dueno").status_code == 302
    assert client.get("/api/session/idle").json()["idle_seconds"] == 600
    clock.advance(minutes=11)
    assert client.get("/api/ping-auth").status_code == 401


def test_limit_seconds_ignores_legacy_true_and_expired_marks(clock):
    assert idle.limit_seconds({"idle_off": True}) == 600              # un True antiguo no exime
    assert idle.limit_seconds({"idle_off": clock.t - 1}) == 600       # vencida
    assert idle.limit_seconds({"idle_off": clock.t + 60}) == 0        # vigente


def test_old_session_without_marker_is_not_expelled_on_deploy(client, factory, clock, monkeypatch):
    """Una sesión creada antes de este cambio (sin `la`) sigue válida: el tiempo corre desde su primera petición."""
    monkeypatch.setattr(idle, "start", lambda session, db=None, staff=None: None)      # el inicio de sesión no deja marca, como en una cookie vieja
    _staff(client, factory)
    clock.advance(minutes=120)
    assert client.get("/api/ping-auth").status_code == 200           # primera petición: se marca; no se expulsa
    clock.advance(minutes=11)
    assert client.get("/api/ping-auth").status_code == 401


def test_exempt_paths_never_expire_or_renew():
    for p in ("/static/js/toast.js", "/health", "/f/abc", "/internal/jobs/run", "/login", "/logout", "/webhooks/wompi", "/b/token", "/aceptar/EV1"):
        assert idle.exempt_path(p), p
    for p in ("/", "/kiosk/1/registro", "/api/recognize", "/api/session/touch"):
        assert not idle.exempt_path(p), p


def test_public_form_page_with_a_stale_staff_cookie_is_not_blocked(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=60)
    r = client.get("/f/no-existe", headers=HTML)
    assert r.status_code != 401 and r.headers.get("location") != "/login?expirada=1"


def test_logout_still_works_after_expiry(client, factory, clock):
    _staff(client, factory)
    clock.advance(minutes=60)
    assert client.post("/logout").status_code == 302


def test_is_navigation_rules():
    assert idle.is_navigation("GET", {"accept": "text/html"})
    assert not idle.is_navigation("GET", {"accept": "*/*"})
    assert not idle.is_navigation("POST", {"accept": "text/html"})
    assert idle.is_navigation("POST", {"sec-fetch-mode": "navigate"})
    assert not idle.is_navigation("GET", {"sec-fetch-mode": "cors", "accept": "text/html"})


def test_login_page_template_and_pages_include_the_script(client, factory):
    ev, _ = _staff(client, factory)
    assert "js/idle-session.js" in client.get(f"/kiosk/{ev.id}/registro", headers=HTML).text


def test_print_pages_do_not_load_the_idle_script():
    import pathlib
    for name in ("badge_print.html", "impresion_usb.html", "form_public.html", "digital_badge.html", "certificate_public.html"):
        assert "idle-session.js" not in pathlib.Path("templates", name).read_text(encoding="utf-8"), name


def test_session_ping_is_passive_and_answers_session_expired_without_touching_staff_lookup(client, factory, clock):
    """El sondeo de toast.js (/api/session/ping, cada 8 s) no renueva la actividad; vencida la sesión responde 401 «session_expired» desde la cookie, sin consultar la base."""
    _staff(client, factory)
    for _ in range(4):
        clock.advance(minutes=2)
        assert client.get("/api/session/ping").status_code == 200
    clock.advance(minutes=3)
    r = client.get("/api/session/ping")
    assert r.status_code == 401 and r.json()["detail"] == "session_expired"


# ---------------------------------------------------------------------------------------------------- 20-nov-2026: tiempo general elegido en Apariencia y volver a la misma página
def test_admin_sets_the_general_minutes_and_everybody_follows(client, factory, clock):
    factory.staff("admin", "adm")
    assert login(client, "adm").status_code == 302
    d = client.get("/api/settings/session-minutes").json()
    assert d["minutes"] == 10 and d["min"] == 5 and d["max"] == 480 and d["forced_by_env"] is False
    for bad in (4, 481, "x", None):
        assert client.put("/api/settings/session-minutes", json={"minutes": bad}).status_code == 400
    assert client.put("/api/settings/session-minutes", json={"minutes": 30}).json()["minutes"] == 30
    assert idle.general_minutes() == 30
    clock.advance(minutes=20)
    assert client.get("/api/ping-auth").status_code == 200           # con 10 ya habría vencido; con 30 sigue
    clock.advance(minutes=11)
    assert client.get("/api/ping-auth").status_code == 401


def test_only_admins_change_the_general_minutes_and_the_env_var_wins(client, factory, monkeypatch):
    factory.staff("coordinador", "coord")
    assert login(client, "coord").status_code == 302
    assert client.get("/api/settings/session-minutes").status_code == 403
    assert client.put("/api/settings/session-minutes", json={"minutes": 30}).status_code == 403
    client.cookies.clear()
    factory.staff("admin", "adm")
    login(client, "adm")
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "7")
    d = client.get("/api/settings/session-minutes").json()
    assert d["minutes"] == 7 and d["forced_by_env"] is True


def test_event_minutes_still_win_over_the_general_one(client, factory, db, clock):
    ev, _ = _staff(client, factory)
    ev.idle_minutes = 20
    db.commit()
    idle._general_cache.set("m", 5)                                    # general = 5 min
    assert idle.general_minutes() == 5 and idle.event_minutes(ev) == 20          # el tiempo propio del evento en proceso sigue siendo suyo (no se tocó)


def test_expired_page_comes_back_to_the_same_page_after_login(client, factory, clock):
    from tests.conftest import PASSWORD
    factory.staff("admin", "adm")
    assert login(client, "adm").status_code == 302
    clock.advance(minutes=11)
    r = client.get("/configuracion?x=1", headers=HTML)
    assert r.status_code == 302 and r.headers["location"] == "/login?expirada=1&next=%2Fconfiguracion%3Fx%3D1"
    page = client.get(r.headers["location"])
    assert 'name="next" value="/configuracion?x=1"' in page.text and "seguirás en la misma página" in page.text
    wrong = client.post("/login", data={"username": "adm", "password": "mala", "next": "/configuracion?x=1"})
    assert wrong.status_code == 401 and 'name="next" value="/configuracion?x=1"' in wrong.text          # si se equivoca, no pierde adónde volver
    back = client.post("/login", data={"username": "adm", "password": PASSWORD, "next": "/configuracion?x=1"})
    assert back.status_code == 302 and back.headers["location"] == "/configuracion?x=1"


def test_login_never_goes_to_another_site_or_to_login_or_api(client, factory):
    from tests.conftest import PASSWORD
    factory.staff("admin", "adm")
    for evil in ("https://evil.com", "//evil.com/x", "/\\evil.com", "/logout", "/api/x", "javascript:alert(1)"):
        client.cookies.clear()
        r = client.post("/login", data={"username": "adm", "password": PASSWORD, "next": evil})
        assert r.status_code == 302 and r.headers["location"] == "/"


def test_general_minutes_are_read_from_the_database_when_the_memory_is_empty(db):
    from app.models import AppSetting
    db.add(AppSetting(key=idle.SETTING_KEY, value="45"))
    db.commit()
    idle._general_cache.clear()
    assert idle.general_is_stale() is True
    assert idle.configured_minutes() == 45 and idle.general_is_stale() is False
    idle._general_cache.clear()
    db.get(AppSetting, idle.SETTING_KEY).value = "basura"
    db.commit()
    assert idle.configured_minutes() == 10          # un valor ilegible vuelve al de siempre
