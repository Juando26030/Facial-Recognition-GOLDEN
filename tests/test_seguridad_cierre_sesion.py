"""Revisión de seguridad S (6-nov-2026): ingreso controlado de digitadores (S1), sesiones que sí se invalidan (S2), límites de intentos (S3, S5, S7), tiempo
constante para usuarios inexistentes (S6), tokens fuera del log (S8), GET que cambia estado (S9), /ready sin detalles (S10) y SECRET_KEY (S11)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import RateLimitEvent, StaffUser
from app.timeutil import utcnow
from tests.conftest import PASSWORD, login


@pytest.fixture()
def second():
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture()
def control(monkeypatch):
    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "1")


@pytest.fixture()
def env(factory):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "80123456", password="80123456")
    factory.authorize(ev, dig)
    return ev, coord, dig


def _state(c, ev):
    return {a["id"]: a for a in c.get(f"/api/events/{ev.id}/staff-users/login-state").json()["accounts"]}


# ---------------------------------------------------------------------------------------------------- funciones puras
def test_ipv6_is_grouped_by_its_64_and_ipv4_stays():
    from app.security import bucket_ip
    assert bucket_ip("2001:db8:1:2:aaaa::1") == bucket_ip("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert bucket_ip("2001:db8:1:3::1") != bucket_ip("2001:db8:1:2::1")
    assert bucket_ip("190.25.3.4") == "190.25.3.4" and bucket_ip("::ffff:190.25.3.4") == "190.25.3.4" and bucket_ip("?") == "?"


def test_secret_key_is_refused_outside_development_when_missing_example_or_short():
    from app import secretcheck
    assert secretcheck.problem("development", None) is None and secretcheck.problem(None, "") is None
    assert secretcheck.problem("production", None)
    assert secretcheck.problem("production", "cambia-esto-por-un-valor-aleatorio-largo")
    assert secretcheck.problem("staging", "corta")
    assert secretcheck.problem("production", "x" * 48) is None


def test_reset_tokens_are_masked_in_the_request_log():
    from app.obs import mask_url
    assert mask_url("/restablecer/abcDEF123_-xyz") == "/restablecer/[token]"


# ---------------------------------------------------------------------------------------------------- S1 (a): solo con un evento en proceso
def test_digitador_without_an_event_in_progress_gets_the_generic_error(client, factory, control):
    ev = factory.event("finalizado")
    dig = factory.staff("digitador", "1012345678", password="1012345678")
    factory.authorize(ev, dig)
    r = login(client, "1012345678", "1012345678")
    assert r.status_code == 401 and "Usuario o contraseña incorrectos" in r.text
    assert client.get("/api/session/ping").status_code == 401                           # sin sesión


# ---------------------------------------------------------------------------------------------------- S1 (b): bloqueo tras 3 fallos
def test_three_bad_passwords_lock_the_digitador_until_the_coordinator_unlocks(client, second, env, db, control):
    ev, coord, dig = env
    assert login(client, "80123456", "mala").status_code == 401
    assert login(client, "80123456", "mala").status_code == 401
    third = login(client, "80123456", "mala")
    assert third.status_code == 403 and "Tu cuenta está bloqueada. Pídele al coordinador que la desbloquee." in third.text
    still = login(client, "80123456", "80123456")                                        # ni con la contraseña correcta
    assert still.status_code == 403 and "bloqueada" in still.text
    db.expire_all()
    assert db.get(StaffUser, dig.id).locked_at is not None

    login(second, "coord")
    assert _state(second, ev)[dig.id]["locked"] is True
    assert second.post(f"/api/events/{ev.id}/staff-users/{dig.id}/unlock").status_code == 200
    db.expire_all()
    row = db.get(StaffUser, dig.id)
    assert row.locked_at is None and row.failed_logins == 0
    assert login(client, "80123456", "80123456").status_code == 303                     # vuelve a poder pedir el ingreso


def test_a_good_login_resets_the_counter(client, factory):
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "55555555", password="55555555")
    factory.authorize(ev, dig)
    login(client, "55555555", "mala")
    login(client, "55555555", "mala")
    assert login(client, "55555555", "55555555").status_code == 302                     # control apagado (conftest): entra directo y el contador vuelve a 0
    client.post("/logout")
    login(client, "55555555", "mala")
    login(client, "55555555", "mala")
    assert login(client, "55555555", "55555555").status_code == 302


def test_a_commercial_cannot_unlock_and_a_digitador_of_another_event_is_404(client, factory, env, control):
    ev, coord, dig = env
    factory.staff("comercial", "com")
    login(client, "com")
    assert client.post(f"/api/events/{ev.id}/staff-users/{dig.id}/unlock").status_code == 403
    client.post("/logout")
    other = factory.event("en_proceso")
    login(client, "coord")
    assert client.post(f"/api/events/{other.id}/staff-users/{dig.id}/unlock").status_code == 404


# ---------------------------------------------------------------------------------------------------- S1 (c): el coordinador autoriza cada ingreso
def test_the_login_waits_until_the_coordinator_allows_it_and_is_single_use(client, second, env, db, control):
    ev, coord, dig = env
    r = login(client, "80123456", "80123456")
    assert r.status_code == 303 and r.headers["location"] == "/ingreso/espera"
    assert client.get("/api/session/ping").status_code == 401                           # todavía no hay sesión
    assert client.get("/ingreso/espera").status_code == 200
    assert client.post("/api/ingreso/estado").json()["status"] == "pending"
    db.expire_all()
    row = db.get(StaffUser, dig.id)
    assert row.login_req_hash and len(row.login_req_hash) == 64 and row.login_req_status == "pending"     # en la base solo el SHA-256

    login(second, "coord")
    st = _state(second, ev)[dig.id]
    assert st["login_pending"] is True and 0 < st["expires_in"] <= 300
    assert second.post(f"/api/events/{ev.id}/staff-users/{dig.id}/login-request", json={"allow": True}).status_code == 200

    ok = client.post("/api/ingreso/estado").json()
    assert ok["status"] == "approved" and ok["redirect"] == "/"
    assert client.get("/api/session/ping").status_code == 200                           # la sesión quedó creada con el mismo código de /login
    assert client.post("/api/ingreso/estado").json()["status"] == "none"                # un solo uso
    db.expire_all()
    assert db.get(StaffUser, dig.id).login_req_hash is None

    client.post("/logout")                                                               # cada ingreso nuevo vuelve a pedir autorización
    assert login(client, "80123456", "80123456").status_code == 303


def test_the_coordinator_can_refuse_the_login(client, second, env, control):
    ev, coord, dig = env
    login(client, "80123456", "80123456")
    login(second, "coord")
    assert second.post(f"/api/events/{ev.id}/staff-users/{dig.id}/login-request", json={"allow": False}).status_code == 200
    d = client.post("/api/ingreso/estado").json()
    assert d["status"] == "denied" and d["message"] == "El coordinador no autorizó el ingreso."
    assert client.get("/api/session/ping").status_code == 401
    assert second.post(f"/api/events/{ev.id}/staff-users/{dig.id}/login-request", json={"allow": True}).status_code == 409       # ya se respondió


def test_another_browser_cannot_complete_someone_elses_request(client, second, factory, env, control):
    ev, coord, dig = env
    login(client, "80123456", "80123456")
    from app.main import app
    with TestClient(app, follow_redirects=False) as boss:
        login(boss, "coord")
        boss.post(f"/api/events/{ev.id}/staff-users/{dig.id}/login-request", json={"allow": True})
    assert second.post("/api/ingreso/estado").json()["status"] == "none"                # sin la cookie del navegador que pidió el ingreso no hay nada
    assert second.get("/api/session/ping").status_code == 401
    assert client.post("/api/ingreso/estado").json()["status"] == "approved"


def test_a_new_attempt_replaces_the_old_request_and_requests_expire(client, second, env, db, control):
    ev, coord, dig = env
    login(client, "80123456", "80123456")
    login(second, "80123456", "80123456")                                               # otro intento (otro navegador) reemplaza al primero
    assert client.post("/api/ingreso/estado").json()["status"] == "none"
    assert second.post("/api/ingreso/estado").json()["status"] == "pending"
    db.query(StaffUser).filter_by(id=dig.id).update({"login_req_at": utcnow() - timedelta(minutes=6)})
    db.commit()
    assert second.post("/api/ingreso/estado").json()["status"] == "expired"


def test_print_station_and_other_roles_do_not_need_approval(client, factory, control):
    factory.staff("coordinador", "c2")
    assert login(client, "c2").status_code == 302


# ---------------------------------------------------------------------------------------------------- S2: sesiones que sí se invalidan
def test_logout_does_not_bring_back_a_replaced_session(client, second, factory):
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "dig1")
    factory.authorize(ev, dig)
    login(client, "dig1")
    login(second, "dig1")                                                                # la del primer equipo queda reemplazada
    second.post("/logout")
    assert client.get("/api/session/ping").status_code == 401                           # antes: el token NULL la volvía a dar por buena


def test_changing_the_password_closes_the_other_sessions_and_keeps_this_one(client, second, factory):
    factory.staff("admin", "adm")
    login(client, "adm")
    login(second, "adm")
    r = client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": "Nueva#Clave2026", "confirm": "Nueva#Clave2026"})
    assert r.status_code == 302
    assert client.get("/api/session/ping").status_code == 200
    assert second.get("/api/session/ping").status_code == 401


def test_a_manager_reset_closes_the_target_sessions(client, second, factory):
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "dig9")
    factory.authorize(ev, dig)
    factory.staff("coordinador", "coord9")
    login(second, "dig9")
    assert second.get("/api/session/ping").status_code == 200
    login(client, "coord9")
    assert client.put(f"/api/staff/{dig.id}/password", json={"use_username": True}).status_code == 200
    assert second.get("/api/session/ping").status_code == 401


# ---------------------------------------------------------------------------------------------------- S3, S5, S6, S7: intentos
def test_the_global_cap_does_not_lock_the_owner_out_from_a_known_ip(client, factory):
    factory.staff("super_admin", "jefe")
    assert client.post("/login", data={"username": "jefe", "password": PASSWORD}, headers={"CF-Connecting-IP": "200.1.1.1"}).status_code == 302
    client.post("/logout")
    for i in range(40):                                                                  # 40 fallos repartidos en 8 IPs (5 por IP)
        client.post("/login", data={"username": "jefe", "password": "mala"}, headers={"CF-Connecting-IP": f"10.0.0.{i // 5}"})
    assert client.post("/login", data={"username": "jefe", "password": PASSWORD}, headers={"CF-Connecting-IP": "9.9.9.9"}).status_code == 429   # IP nueva: frenada
    assert client.post("/login", data={"username": "jefe", "password": PASSWORD}, headers={"CF-Connecting-IP": "200.1.1.1"}).status_code == 302  # el dueño entra


def test_the_attempt_is_recorded_before_bcrypt(client, factory, db, monkeypatch):
    factory.staff("coordinador", "ana")
    from app.routers import auth as auth_router
    from app.database import SessionLocal
    seen = []
    real = auth_router.verify_password

    def spy(raw, hashed):
        s = SessionLocal()
        seen.append(s.query(RateLimitEvent).filter_by(kind="login_fail", key="ana").count())
        s.close()
        return real(raw, hashed)
    monkeypatch.setattr(auth_router, "verify_password", spy)
    login(client, "ana", "mala")
    assert seen == [1]


def test_an_unknown_user_still_pays_for_bcrypt(client, monkeypatch):
    from app.routers import auth as auth_router
    calls = []
    real = auth_router.verify_password
    monkeypatch.setattr(auth_router, "verify_password", lambda raw, hashed: calls.append(1) or real(raw, hashed))
    assert login(client, "no_existe", "x").status_code == 401
    assert calls == [1]


def test_the_current_password_on_change_is_rate_limited(client, factory):
    factory.staff("coordinador", "ana")
    login(client, "ana")
    codes = [client.post("/cambiar-contrasena", data={"current": "mala", "password": "Nueva#Clave2026", "confirm": "Nueva#Clave2026"}).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429


# ---------------------------------------------------------------------------------------------------- S9: GET que cambia estado
def test_print_jobs_next_refuses_a_navigation(client, factory):
    ev = factory.event("en_proceso", shared_print_enabled=True)
    factory.staff("coordinador", "op")
    login(client, "op")
    nav = client.get(f"/api/events/{ev.id}/print-jobs-next?manual=1&batch=50", headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "cross-site"})
    assert nav.status_code == 403
    assert client.get(f"/api/events/{ev.id}/print-jobs-next", headers={"Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}).status_code == 200


# ---------------------------------------------------------------------------------------------------- código fuente
def test_the_waiting_page_and_its_script_follow_the_frontend_rules():
    page = open("templates/ingreso_espera.html", encoding="utf8").read()
    js = open("static/js/ingreso-espera.js", encoding="utf8").read()
    assert "url_for('static', path='js/ingreso-espera.js')" in page and "onclick" not in page
    assert "alert(" not in js and "confirm(" not in js and "/api/ingreso/estado" in js and "method: 'POST'" in js
    usuarios = open("static/js/usuarios.js", encoding="utf8").read()
    assert "visibilityState" in usuarios and "login-state" in usuarios and "Bloqueada" in usuarios and "Está intentando ingresar" in usuarios


def test_a_replaced_login_request_cannot_be_approved_with_the_old_code(client, second, env, control):
    """Fase 3 (B6): si otra solicitud reemplaza a la que el coordinador estaba mirando, su clic sobre la vieja no aprueba a ciegas la nueva."""
    from app.main import app
    ev, coord, dig = env
    assert login(client, "80123456", "80123456").status_code == 303
    login(second, "coord")
    seen = _state(second, ev)[dig.id]["req"]
    with TestClient(app, follow_redirects=False) as other:                  # otro navegador con la misma cédula/clave: reemplaza la solicitud
        assert login(other, "80123456", "80123456").status_code == 303
    url = f"/api/events/{ev.id}/staff-users/{dig.id}/login-request"
    assert second.post(url, json={"allow": True, "req": seen}).status_code == 409
    fresh = _state(second, ev)[dig.id]["req"]
    assert fresh != seen
    assert second.post(url, json={"allow": True, "req": fresh}).status_code == 200
