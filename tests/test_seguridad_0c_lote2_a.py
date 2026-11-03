"""0C, lote 2, grupo A: C7 (bloqueo de login por usuario+IP), C8 (contador por cédula en /aceptar), C11 (política de contraseñas al crear personal) y C4/C15 (cédula amarrada al enlace)."""
from datetime import timedelta

from app import security
from app.models import RateLimitEvent
from app.timeutil import utcnow
from tests.conftest import PASSWORD


def _ip(n):
    return {"cf-connecting-ip": f"203.0.113.{n}"}


def _login(client, user, password, ip):
    return client.post("/login", data={"username": user, "password": password}, headers=_ip(ip))


# ------------------------------------------------------------------------------------------------------------------------------------ C7
def test_c7_an_outside_ip_cannot_lock_the_owner_out(client, factory):
    factory.staff("super_admin", "root")
    for _ in range(security.LOGIN_MAX_FAILS):
        assert _login(client, "root", "mala", 1).status_code == 401
    assert _login(client, "root", "mala", 1).status_code == 429                      # el atacante queda bloqueado...
    assert _login(client, "root", PASSWORD, 2).status_code == 302                    # ...pero el dueño entra desde otra IP


def test_c7_the_pair_locks_even_with_the_right_password(client, factory):
    factory.staff("coordinador", "ana")
    for _ in range(security.LOGIN_MAX_FAILS):
        _login(client, "ana", "mala", 5)
    locked = _login(client, "ana", PASSWORD, 5)
    assert locked.status_code == 429 and "minuto" in locked.text


def test_c7_ip_cap_still_applies_across_many_usernames(client):
    for i in range(security.LOGIN_MAX_FAILS_PER_IP):
        _login(client, f"fantasma{i}", "x", 7)
    assert _login(client, "otro_usuario", "x", 7).status_code == 429
    assert _login(client, "otro_usuario", "x", 8).status_code == 401


def test_c7_global_user_cap_blocks_distributed_brute_force(client, factory, db):
    factory.staff("coordinador", "ana")
    now = utcnow()
    for i in range(security.LOGIN_MAX_FAILS_PER_USER):                                # fallos repartidos en muchas IPs (cada par queda lejos de su tope)
        db.add(RateLimitEvent(kind="login_fail", key="ana", ip=f"198.51.100.{i}", created_at=now))
    db.commit()
    assert _login(client, "ana", PASSWORD, 99).status_code == 429
    db.query(RateLimitEvent).update({"created_at": utcnow() - timedelta(minutes=16)})
    db.commit()
    assert _login(client, "ana", PASSWORD, 99).status_code == 302


def test_c7_below_the_global_cap_distributed_failures_do_not_block(client, factory, db):
    factory.staff("coordinador", "ana")
    for i in range(security.LOGIN_MAX_FAILS_PER_USER - 1):
        db.add(RateLimitEvent(kind="login_fail", key="ana", ip=f"198.51.100.{i}", created_at=utcnow()))
    db.commit()
    assert _login(client, "ana", PASSWORD, 99).status_code == 302


def test_c7_without_a_trusted_ip_the_pair_is_just_the_user(db):
    for _ in range(security.LOGIN_MAX_FAILS):
        security.record_event(db, "login_fail", "ana", None)
    assert security.login_minutes_locked(db, "ana", None) > 0
    assert security.login_minutes_locked(db, "beto", None) == 0


def test_c7_a_correct_login_clears_every_failure_of_the_user_from_any_ip(client, factory, db):
    factory.staff("coordinador", "ana")
    for ip in (1, 2, 3):
        for _ in range(2):
            _login(client, "ana", "mala", ip)
    assert _login(client, "ana", PASSWORD, 4).status_code == 302
    assert db.query(RateLimitEvent).filter_by(kind="login_fail", key="ana").count() == 0
