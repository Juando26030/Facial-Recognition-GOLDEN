"""Login, límite de intentos, restablecer/cambiar contraseña, CSRF y jerarquía de cuentas (Sprint 4, ítem 3)."""
from datetime import datetime, timedelta

from tests.conftest import PASSWORD, login


# ------------------------------- login y rate limiting -------------------------------
def test_login_ok_and_bad_password(client, factory):
    factory.staff("coordinador", "ana")
    assert login(client, "ana").status_code == 302
    client.post("/logout")
    bad = login(client, "ana", "incorrecta")
    assert bad.status_code == 401
    assert "incorrectos" in bad.text


def test_unknown_user_gets_same_message_as_bad_password(client, factory):
    factory.staff("coordinador", "ana")
    a = login(client, "ana", "mala")
    b = login(client, "no_existe", "mala")
    assert a.status_code == b.status_code == 401
    assert "Usuario o contraseña incorrectos" in a.text and "Usuario o contraseña incorrectos" in b.text


def test_login_locks_after_five_failures_even_with_right_password(client, factory):
    factory.staff("coordinador", "ana")
    for _ in range(5):
        assert login(client, "ana", "mala").status_code == 401
    locked = login(client, "ana", PASSWORD)
    assert locked.status_code == 429
    assert "minuto" in locked.text
    # otro usuario no queda bloqueado por los intentos de "ana"
    factory.staff("coordinador", "beto")
    assert login(client, "beto").status_code == 302


def test_lock_also_applies_to_nonexistent_usernames(client):
    for _ in range(5):
        login(client, "fantasma", "x")
    assert login(client, "fantasma", "x").status_code == 429


def test_successful_login_resets_counter(client, factory):
    factory.staff("coordinador", "ana")
    for _ in range(4):
        login(client, "ana", "mala")
    assert login(client, "ana").status_code == 302
    client.post("/logout")
    for _ in range(4):
        assert login(client, "ana", "mala").status_code == 401  # sigue contando desde cero, no bloquea


def test_lock_expires_after_window(client, factory, db):
    from app.models import RateLimitEvent

    factory.staff("coordinador", "ana")
    for _ in range(5):
        login(client, "ana", "mala")
    assert login(client, "ana", PASSWORD).status_code == 429
    db.query(RateLimitEvent).update({"created_at": datetime.utcnow() - timedelta(minutes=16)})
    db.commit()
    assert login(client, "ana", PASSWORD).status_code == 302


# ------------------------------- CSRF (Origin) -------------------------------
def test_cross_site_post_is_rejected_but_same_site_and_no_origin_pass(client, factory):
    factory.staff("admin", "root")
    login(client, "root")
    evil = client.post("/logout", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    same = client.post("/logout", headers={"Origin": "http://testserver"})
    assert same.status_code == 302
    login(client, "root")
    assert client.post("/logout").status_code == 302  # sin Origin (no es un navegador): no se rechaza


def test_null_origin_is_rejected(client):
    assert client.post("/login", data={"username": "x", "password": "y"}, headers={"Origin": "null"}).status_code == 403


# ------------------------------- restablecer contraseña -------------------------------
def _token_from(outbox):
    body = outbox[-1]["body"]
    return body.split("/restablecer/")[1].split()[0]


def test_forgot_password_sends_link_and_response_is_generic(client, factory, outbox):
    factory.staff("coordinador", "ana", email="ana@example.com")
    factory.staff("coordinador", "sinmail")
    ok = client.post("/olvide-contrasena", data={"username": "ana"})
    ghost = client.post("/olvide-contrasena", data={"username": "no_existe"})
    nomail = client.post("/olvide-contrasena", data={"username": "sinmail"})
    generic = "Si la cuenta existe"
    assert generic in ok.text and generic in ghost.text and generic in nomail.text
    assert [m["to"] for m in outbox] == ["ana@example.com"]      # solo la cuenta con correo recibe algo


def test_reset_flow_is_single_use_and_changes_password(client, factory, outbox):
    factory.staff("coordinador", "ana", email="ana@example.com")
    client.post("/olvide-contrasena", data={"username": "ana"})
    token = _token_from(outbox)
    assert client.get(f"/restablecer/{token}").status_code == 200
    short = client.post(f"/restablecer/{token}", data={"password": "corta", "confirm": "corta"})
    assert short.status_code == 400
    mismatch = client.post(f"/restablecer/{token}", data={"password": "Nueva#2026x", "confirm": "otra#2026xx"})
    assert mismatch.status_code == 400
    done = client.post(f"/restablecer/{token}", data={"password": "Nueva#2026x", "confirm": "Nueva#2026x"})
    assert done.status_code == 200 and "quedó cambiada" in done.text
    assert login(client, "ana", PASSWORD).status_code == 401
    assert login(client, "ana", "Nueva#2026x").status_code == 302
    assert client.get(f"/restablecer/{token}").status_code == 410   # ya usado
    assert client.post(f"/restablecer/{token}", data={"password": "Otra#2026xy", "confirm": "Otra#2026xy"}).status_code == 410


def test_expired_and_replaced_tokens_are_invalid(client, factory, outbox, db):
    from app.models import PasswordResetToken

    factory.staff("coordinador", "ana", email="ana@example.com")
    client.post("/olvide-contrasena", data={"username": "ana"})
    first = _token_from(outbox)
    client.post("/olvide-contrasena", data={"username": "ana"})
    second = _token_from(outbox)
    assert client.get(f"/restablecer/{first}").status_code == 410   # el nuevo enlace invalida el anterior
    db.query(PasswordResetToken).update({"expires_at": datetime.utcnow() - timedelta(minutes=1)})
    db.commit()
    assert client.get(f"/restablecer/{second}").status_code == 410  # vencido


def test_token_is_stored_hashed(client, factory, outbox, db):
    from app.models import PasswordResetToken

    factory.staff("coordinador", "ana", email="ana@example.com")
    client.post("/olvide-contrasena", data={"username": "ana"})
    token = _token_from(outbox)
    assert db.query(PasswordResetToken).filter_by(token_hash=token).first() is None
    assert db.query(PasswordResetToken).count() == 1


def test_reset_password_clears_login_lock(client, factory, outbox):
    factory.staff("coordinador", "ana", email="ana@example.com")
    for _ in range(5):
        login(client, "ana", "mala")
    assert login(client, "ana", PASSWORD).status_code == 429
    client.post("/olvide-contrasena", data={"username": "ana"})
    client.post(f"/restablecer/{_token_from(outbox)}", data={"password": "Nueva#2026x", "confirm": "Nueva#2026x"})
    assert login(client, "ana", "Nueva#2026x").status_code == 302


def test_forgot_password_request_is_rate_limited(client, factory, outbox):
    factory.staff("coordinador", "ana", email="ana@example.com")
    codes = [client.post("/olvide-contrasena", data={"username": "ana"}).status_code for _ in range(7)]
    assert 429 in codes


# ------------------------------- cambiar contraseña y must_change -------------------------------
def test_change_password_requires_current_and_a_different_one(client, factory):
    factory.staff("coordinador", "ana")
    login(client, "ana")
    assert client.post("/cambiar-contrasena", data={"current": "mala", "password": "Nueva#2026x", "confirm": "Nueva#2026x"}).status_code == 400
    assert client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": PASSWORD, "confirm": PASSWORD}).status_code == 400
    assert client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": "Nueva#2026x", "confirm": "Nueva#2026x"}).status_code == 302
    client.post("/logout")
    assert login(client, "ana", "Nueva#2026x").status_code == 302


def test_change_password_page_requires_login(client):
    assert client.get("/cambiar-contrasena").status_code == 302


def test_must_change_password_blocks_everything_until_changed(client, factory):
    factory.staff("coordinador", "ana", must_change_password=True)
    r = login(client, "ana")
    assert r.status_code == 302 and r.headers["location"] == "/cambiar-contrasena"
    page = client.get("/clientes", headers={"accept": "text/html"})
    assert page.status_code == 302 and page.headers["location"] == "/cambiar-contrasena"
    assert client.get("/api/events", headers={"accept": "application/json"}).status_code == 403
    assert client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": "Nueva#2026x", "confirm": "Nueva#2026x"}).status_code == 302
    assert client.get("/api/events").status_code == 200


# ------------------------------- jerarquía de cuentas -------------------------------
def test_staff_list_is_admin_only(client, factory):
    for role in ("cliente", "digitador", "coordinador", "comercial"):
        factory.staff(role, f"u_{role}")
    factory.staff("admin", "root")
    for role in ("cliente", "digitador", "coordinador", "comercial"):
        client.post("/logout")
        login(client, f"u_{role}")
        assert client.get("/api/staff").status_code == 403, role
    client.post("/logout")
    login(client, "root")
    assert client.get("/api/staff").status_code == 200


def test_change_role_rules(client, factory):
    admin = factory.staff("admin", "adm")
    coord = factory.staff("coordinador", "coord")
    other_admin = factory.staff("admin", "adm2")
    digi = factory.staff("digitador", "9990001")
    root = factory.staff("super_admin", "boss")
    login(client, "adm")
    assert client.patch(f"/api/staff/{coord.id}/role", json={"role": "comercial"}).json()["role"] == "comercial"
    assert client.patch(f"/api/staff/{coord.id}/role", json={"role": "admin"}).status_code == 403        # solo super_admin nombra admins
    assert client.patch(f"/api/staff/{coord.id}/role", json={"role": "super_admin"}).status_code == 400
    assert client.patch(f"/api/staff/{admin.id}/role", json={"role": "comercial"}).status_code == 400    # no el propio
    assert client.patch(f"/api/staff/{other_admin.id}/role", json={"role": "comercial"}).status_code == 403  # un admin no toca a otro admin
    assert client.patch(f"/api/staff/{digi.id}/role", json={"role": "coordinador"}).status_code == 403  # digitador es de un evento
    assert client.patch(f"/api/staff/{root.id}/role", json={"role": "comercial"}).status_code == 403
    client.post("/logout")
    login(client, "boss")
    assert client.patch(f"/api/staff/{coord.id}/role", json={"role": "admin"}).json()["role"] == "admin"


def test_role_change_drops_incompatible_secondary_role(client, factory, db):
    factory.staff("admin", "adm")
    coord = factory.staff("coordinador", "coord", secondary_role="comercial")
    login(client, "adm")
    client.patch(f"/api/staff/{coord.id}/role", json={"role": "comercial"})
    db.refresh(coord)
    assert coord.role == "comercial" and coord.secondary_role is None


def test_password_reset_by_manager_forces_change_and_respects_hierarchy(client, factory):
    coord = factory.staff("coordinador", "coord")
    digi = factory.staff("digitador", "9990001")
    admin = factory.staff("admin", "adm")
    login(client, "coord")
    weak = client.put(f"/api/staff/{digi.id}/password", json={"new_password": "corta"})
    assert weak.status_code == 400
    assert client.put(f"/api/staff/{digi.id}/password", json={"new_password": "Temporal#2026"}).status_code == 200
    assert client.put(f"/api/staff/{admin.id}/password", json={"new_password": "Temporal#2026"}).status_code == 403
    assert client.put(f"/api/staff/{coord.id}/password", json={"new_password": "Temporal#2026"}).status_code == 400  # la propia: cambiar-contrasena
    client.post("/logout")
    r = login(client, "9990001", "Temporal#2026")
    assert r.status_code == 302 and r.headers["location"] == "/cambiar-contrasena"
    assert login(client, "9990001", PASSWORD).status_code == 401   # la anterior ya no sirve


def test_digitador_and_cliente_cannot_reset_anyones_password(client, factory):
    digi = factory.staff("digitador", "9990001")
    other = factory.staff("digitador", "9990002")
    login(client, "9990001")
    assert client.put(f"/api/staff/{other.id}/password", json={"new_password": "Temporal#2026"}).status_code == 403
