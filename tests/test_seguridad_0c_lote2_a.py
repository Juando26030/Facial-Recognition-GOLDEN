"""0C, lote 2, grupo A: C7 (bloqueo de login por usuario+IP), C8 (contador por cédula en /aceptar), C11 (política de contraseñas al crear personal) y C4/C15 (cédula amarrada al enlace)."""
import hashlib
from datetime import date, timedelta

import pytest

from app import security
from app.models import RateLimitEvent
from app.timeutil import utcnow
from tests.conftest import PASSWORD
from tests.test_accept_link import _setup


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


# ------------------------------------------------------------------------------------------------------------------------------------ C8 y C4/C15 (/aceptar)
@pytest.fixture(autouse=True)
def _company_env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "ejemplo.test",
                 "PUBLIC_BASE_URL": "https://app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)


def _check(client, ev, cedula, birth="1990-04-02", token="", ip=None):
    return client.post(f"/api/aceptar/{ev.event_code}/check", data={"token": token, "cedula": cedula, "birth_date": birth}, headers=_ip(ip) if ip else {})


def test_c8_portal_pauses_a_document_after_five_failures_from_any_ip(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    for i in range(5):
        assert _check(client, ev, "1001", birth="1991-01-01", ip=10 + i).status_code == 404       # cada intento, desde una IP distinta
    blocked = _check(client, ev, "1001", ip=50)                                                    # ni con los datos buenos ni desde otra IP
    assert blocked.status_code == 429 and "Demasiados intentos" in blocked.json()["detail"]
    assert _check(client, ev, "2002", ip=50).status_code == 404                                    # otra cédula no está pausada (y sigue la respuesta genérica)


def test_c8_unknown_documents_are_counted_too_and_the_answer_stays_generic(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    first = _check(client, ev, "9999")
    assert first.status_code == 404 and "No encontramos tu inscripción" in first.json()["detail"]
    for _ in range(4):
        _check(client, ev, "9999")
    assert _check(client, ev, "9999").status_code == 429


def test_c8_a_success_resets_the_counter_and_the_window_expires(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    for _ in range(4):
        _check(client, ev, "1001", birth="1991-01-01")
    assert _check(client, ev, "1001").status_code == 200
    for _ in range(5):
        _check(client, ev, "1001", birth="1991-01-01")
    assert _check(client, ev, "1001").status_code == 429
    db.query(RateLimitEvent).update({"created_at": utcnow() - timedelta(minutes=16)})
    db.commit()
    assert _check(client, ev, "1001").status_code == 200


def test_c8_the_counter_never_stores_the_document_in_clear(client, factory, db):
    ev, _u, _t = _setup(factory, db)
    _check(client, ev, "1001", birth="1991-01-01")
    rows = db.query(RateLimitEvent).filter_by(kind="aceptar_cedula_fail").all()
    assert len(rows) == 1 and rows[0].key != "1001" and len(rows[0].key) == 32 and rows[0].ip is None
    assert rows[0].key == hashlib.sha256(f"{ev.tenant_id}|{ev.id}|1001".encode()).hexdigest()[:32]


def test_c4_c15_the_typed_document_must_be_the_one_of_the_invitation(client, factory, db):
    ev, _u, token = _setup(factory, db)
    other = factory.person(ev, "2002", "Beto", "Mora")
    other.birth_date = date(1990, 4, 2)
    db.commit()
    ok = _check(client, ev, "1001", token=token)
    assert ok.status_code == 200
    for bad in ("2002", "9999", ""):                                                                # otra persona inscrita, una inexistente o vacía
        r = _check(client, ev, bad, token=token)
        assert r.status_code == 404 and "No encontramos tu inscripción" in r.json()["detail"]


def test_c4_c15_a_wrong_link_and_a_wrong_document_answer_exactly_the_same(client, factory, db):
    ev, _u, token = _setup(factory, db)
    wrong_doc = _check(client, ev, "9999", token=token)
    wrong_link = _check(client, ev, "1001", token="enlace-que-no-existe")
    assert wrong_doc.status_code == wrong_link.status_code == 404
    assert wrong_doc.json() == wrong_link.json()


def test_c4_c15_the_same_binding_applies_when_submitting(client, factory, db):
    from app import legal_texts
    from app.models import AuditConsentLog
    ev, _u, token = _setup(factory, db)
    t = legal_texts.render(ev, web=True)
    r = client.post(f"/api/aceptar/{ev.event_code}", data={"token": token, "cedula": "2002", "birth_date": "1990-04-02", "decision": "reject", "text_hash": t["hash"]})
    assert r.status_code == 404 and db.query(AuditConsentLog).count() == 0
