"""Fase 1B · reimpresión configurable por evento con permisos (docs/1B_reimpresion_permisos.md).

Modos: habilitada (por defecto) · deshabilitada · deshabilitada con permiso. Solo el coordinador de ESE evento (o admin+) decide; el permiso es de un solo uso y vence; el correo de respaldo lleva un enlace
de un solo uso (el GET no aprueba nada); la puerta es la del SERVIDOR (print-jobs y reprint-requests/use); y cada hecho queda en la auditoría."""
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app import jobs, reprint
from app.database import SessionLocal
from app.models import AccessLog, Event, Job, PrintLog, PrintRoute, ReprintAudit, ReprintLink, ReprintRequest, StaffUser
from app.timeutil import utcnow
from tests.conftest import login

LINK = re.compile(r"/reimpresion/([A-Za-z0-9_\-]+)")


@pytest.fixture()
def env(client, factory, db):
    """Evento con impresión compartida, coordinador asignado, otro coordinador, admin, un digitador (dig) que imprime en el equipo de otro (prn) y dos personas ya impresas."""
    admin = factory.staff("admin", "adm", email="adm@golden.test")
    coord = factory.staff("coordinador", "coord", email="coord@golden.test")
    other = factory.staff("coordinador", "coord2", email="otro@golden.test")
    ev = factory.event("en_proceso", coordinator=coord, shared_print_enabled=True)
    dig = factory.staff("digitador", "dig")
    prn = factory.staff("digitador", "prn")
    for s in (dig, prn):
        factory.authorize(ev, s)
    db.add(PrintRoute(event_id=ev.id, staff_user_id=dig.id, printer_staff_id=prn.id))
    for uid, name in (("1001", "Ana"), ("1002", "Beto"), ("1003", "Cata"), ("1004", "Dani")):
        factory.person(ev, uid, first_name=name)
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional"))
    for uid in ("1001", "1002", "1003"):                                                           # 1004 aún no se imprime
        db.add(PrintLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, printed_by_staff_id=dig.id))
    db.commit()
    return type("Env", (), {"ev": ev, "admin": admin, "coord": coord, "other": other, "dig": dig, "prn": prn})


def _as(client, username):
    client.post("/logout")
    client.cookies.clear()
    login(client, username)


def _disable(client, env, value=True):
    _as(client, "adm")
    r = client.put(f"/api/events/{env.ev.id}/reprint-mode", json={"disabled": value})
    assert r.status_code == 200, r.text


def _job(client, env, uid="1001", reprint_flag=True):
    return client.post(f"/api/events/{env.ev.id}/print-jobs", json={"user_id": uid, "request_id": str(uuid.uuid4()), "reprint": reprint_flag})


def _ask(client, env, uid="1001"):
    _as(client, "dig")
    return client.post(f"/api/events/{env.ev.id}/reprint-requests", json={"user_id": uid})


def _decide(client, who, rid, choice):
    _as(client, who)
    return client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": choice})


def _kinds(db, rid):
    db.expire_all()
    return [a.kind for a in db.query(ReprintAudit).filter_by(request_id=rid).order_by(ReprintAudit.id)]


def _due(db, stage=None):
    """Adelanta los trabajos de aviso (sus horas son +25 s y +2 min): `stage` = solo el de «presence» o el de «timeout»."""
    for j in db.query(Job).filter(Job.kind == "reprint_notify", Job.status == "queued"):
        if stage is None or f'"{stage}"' in j.payload_json:
            j.run_at = utcnow() - timedelta(seconds=1)
    db.commit()
    jobs.drain()


# ---------------------------------------------------------------------------------------------------- los tres modos
def test_enabled_by_default_reprint_goes_through_without_permission(client, env):
    assert env.ev.reprint_disabled is False
    _as(client, "dig")
    assert _job(client, env, "1001", True).status_code == 200


def test_disabled_blocks_a_reprint_on_the_server_even_if_the_page_allows_it(client, env):
    _disable(client, env)
    _as(client, "dig")
    r = _job(client, env, "1001", True)
    assert r.status_code == 403 and r.json()["detail"].startswith("No se puede reimprimir")
    assert _job(client, env, "1001", False).status_code == 403            # sin la bandera `reprint` también: es una reimpresión (ya se imprimió y pasó la ventana de 30 s)


def test_disabled_does_not_block_the_first_print_of_someone_not_printed_yet(client, env):
    _disable(client, env)
    _as(client, "dig")
    assert _job(client, env, "1004", False).status_code == 200


def test_disabled_with_an_approved_permission_allows_exactly_one_reprint(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    assert _decide(client, "coord", rid, "approve").json()["status"] == "approved"
    _as(client, "dig")
    first = _job(client, env, "1001", True)
    assert first.status_code == 200
    again = _job(client, env, "1001", True)
    assert again.status_code == 403                                        # el permiso se gastó
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "used"
    assert _kinds(db, rid) == ["requested", "approved", "used"]


def test_a_denied_request_does_not_open_the_door(client, env):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    assert _decide(client, "coord", rid, "deny").json()["status"] == "denied"
    _as(client, "dig")
    assert _job(client, env, "1001", True).status_code == 403


def test_an_expired_permission_is_rejected_and_recorded(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _decide(client, "coord", rid, "approve")
    r = db.get(ReprintRequest, rid)
    r.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    _as(client, "dig")
    assert _job(client, env, "1001", True).status_code == 403
    assert _kinds(db, rid) == ["requested", "approved", "expired"]


def test_the_permission_is_for_that_person_only(client, env):
    _disable(client, env)
    rid = _ask(client, env, "1001").json()["id"]
    _decide(client, "coord", rid, "approve")
    _as(client, "dig")
    assert _job(client, env, "1002", True).status_code == 403              # el permiso era de 1001


def test_approval_minutes_come_from_the_environment(client, env, db, monkeypatch):
    monkeypatch.setenv("REPRINT_APPROVAL_MINUTES", "3")
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _decide(client, "coord", rid, "approve")
    db.expire_all()
    left = db.get(ReprintRequest, rid).expires_at - utcnow()
    assert timedelta(minutes=2) < left <= timedelta(minutes=3)


def test_default_approval_is_fifteen_minutes(monkeypatch):
    monkeypatch.delenv("REPRINT_APPROVAL_MINUTES", raising=False)
    assert reprint.approval_minutes() == 15


# ---------------------------------------------------------------------------------------------------- quién cambia el modo y quién decide
def test_only_admin_changes_the_mode(client, env):
    for who in ("coord", "dig"):
        _as(client, who)
        assert client.put(f"/api/events/{env.ev.id}/reprint-mode", json={"disabled": True}).status_code == 403
    _disable(client, env)


def test_parametros_shows_the_option_enabled_for_admin_and_locked_for_the_coordinator(client, env):
    _as(client, "adm")
    page = client.get(f"/kiosk/{env.ev.id}/parametros").text
    assert 'name="reprintMode"' in page and "Solo un administrador cambia esta opción" not in page
    _as(client, "coord")
    page = client.get(f"/kiosk/{env.ev.id}/parametros").text
    assert "Solo un administrador cambia esta opción" in page


def test_only_the_coordinator_of_that_event_sees_and_decides(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _as(client, "coord")
    assert [r["id"] for r in client.get("/api/reprint-requests/inbox").json()["requests"]] == [rid]
    _as(client, "coord2")
    assert client.get("/api/reprint-requests/inbox").json()["requests"] == []
    assert client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": "approve"}).status_code == 404
    _as(client, "adm")
    assert client.get("/api/reprint-requests/inbox").json()["requests"] == []          # el evento tiene coordinador: no le llega al admin
    _as(client, "dig")
    assert client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": "approve"}).status_code == 403
    assert db.get(ReprintRequest, rid).status == "pending"


def test_an_event_without_a_coordinator_goes_to_the_admins_only(client, env, db, outbox):
    env.ev.coordinator_staff_id = None
    db.commit()
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _as(client, "adm")
    assert [r["id"] for r in client.get("/api/reprint-requests/inbox").json()["requests"]] == [rid]
    _as(client, "coord")
    assert client.get("/api/reprint-requests/inbox").json()["requests"] == []
    _due(db)
    assert [m["to"] for m in outbox] == ["adm@golden.test"]
    _as(client, "adm")
    assert client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": "approve"}).status_code == 200


def test_the_coordinator_of_the_event_reprints_without_asking_but_another_coordinator_does_not(db, env):
    env.ev.reprint_disabled = True
    db.commit()
    reprint.gate(db, env.ev, env.coord, "1001", "shared")                   # no lanza
    reprint.gate(db, env.ev, env.admin, "1001", "shared")
    with pytest.raises(HTTPException) as err:
        reprint.gate(db, env.ev, env.other, "1001", "shared")
    assert err.value.status_code == 403


def test_a_digitador_of_another_event_cannot_ask(client, env, factory):
    _disable(client, env)
    stranger = factory.staff("digitador", "stranger")
    ev2 = factory.event("en_proceso")
    factory.authorize(ev2, stranger)
    _as(client, "stranger")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests", json={"user_id": "1001"}).status_code == 403


def test_asking_is_refused_when_reprint_is_enabled_or_the_person_was_never_printed(client, env):
    _as(client, "dig")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests", json={"user_id": "1001"}).status_code == 409
    _disable(client, env)
    _as(client, "dig")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests", json={"user_id": "1004"}).status_code == 409


# ---------------------------------------------------------------------------------------------------- anti abuso
def test_pending_limit_and_rate(client, env, monkeypatch, factory, db):
    _disable(client, env)
    assert _ask(client, env, "1001").status_code == 200
    assert _ask(client, env, "1002").status_code == 429                    # ritmo: dos solicitudes casi a la vez
    monkeypatch.setattr(reprint, "MIN_GAP_SECONDS", 0)
    assert _ask(client, env, "1002").status_code == 200
    assert _ask(client, env, "1003").status_code == 200
    factory.person(env.ev, "1005")
    db.add(AccessLog(tenant_id=env.ev.tenant_id, user_id="1005", event_id=env.ev.id, record_type="Existente", registration_method="tradicional"))
    db.add(PrintLog(tenant_id=env.ev.tenant_id, user_id="1005", event_id=env.ev.id, printed_by_staff_id=env.dig.id))
    db.commit()
    assert _ask(client, env, "1005").status_code == 429                    # tope de pendientes (3)


def test_asking_twice_for_the_same_person_returns_the_same_request(client, env, monkeypatch):
    monkeypatch.setattr(reprint, "MIN_GAP_SECONDS", 0)
    _disable(client, env)
    a = _ask(client, env).json()
    b = _ask(client, env).json()
    assert a["id"] == b["id"] and a["created"] is True and b["created"] is False


def test_the_requester_sees_the_state_and_print_count_carries_it(client, env):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    mine = client.get(f"/api/events/{env.ev.id}/reprint-requests/mine", params={"user_id": "1001"}).json()
    assert mine["reprint_locked"] is True and mine["request"]["status"] == "pending" and mine["permit"] is False
    _decide(client, "coord", rid, "approve")
    _as(client, "dig")
    count = client.get("/api/users/1001/print-count", params={"event_id": env.ev.id}).json()
    assert count["times_printed"] == 1 and count["reprint_locked"] is True and count["permit"] is True and count["request"]["status"] == "approved"


# ---------------------------------------------------------------------------------------------------- impresión local (USB o ventana)
def test_use_endpoint_spends_the_permission_once(client, env):
    _disable(client, env)
    _as(client, "dig")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1001"}).status_code == 403
    rid = _ask(client, env).json()["id"]
    _decide(client, "coord", rid, "approve")
    _as(client, "dig")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1001"}).status_code == 200
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1001"}).status_code == 403
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1004"}).status_code == 200      # nunca impresa: no hace falta permiso


def test_use_endpoint_is_a_noop_when_reprint_is_enabled(client, env):
    _as(client, "dig")
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1001"}).status_code == 200


# ---------------------------------------------------------------------------------------------------- doble uso concurrente
def test_two_teams_cannot_spend_the_same_permission_twice(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _decide(client, "coord", rid, "approve")

    def attempt(_):
        with SessionLocal() as s:
            ok = reprint.consume(s, s.get(Event, env.ev.id), s.get(StaffUser, env.dig.id), "1001", "shared")
            s.commit()
            return ok

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sorted(results) == [False, False, False, True]
    db.expire_all()
    assert _kinds(db, rid).count("used") == 1


def test_two_clients_cannot_decide_the_same_request_twice(client, env):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    assert _decide(client, "coord", rid, "approve").status_code == 200
    assert _decide(client, "coord", rid, "deny").status_code == 409


# ---------------------------------------------------------------------------------------------------- pantalla del coordinador y respaldo por correo
def test_the_inbox_marks_the_request_as_seen_on_screen(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _as(client, "coord")
    client.get("/api/reprint-requests/inbox")
    client.get("/api/reprint-requests/inbox")
    assert _kinds(db, rid) == ["requested", "screen"]                       # una sola marca aunque sondee varias veces
    assert db.get(ReprintRequest, rid).screen_seen_at is not None


def test_no_email_when_the_coordinator_screen_showed_it_and_he_answers_in_time(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _as(client, "coord")
    client.get("/api/reprint-requests/inbox")
    _due(db, "presence")                                                    # a los 25 s: la pantalla la mostró, no hay correo
    assert outbox == []
    _decide(client, "coord", rid, "approve")
    _due(db, "timeout")                                                     # a los 2 min: ya está decidida, no hay correo
    assert outbox == []


def test_email_goes_out_at_once_when_the_screen_never_showed_it(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db, "presence")
    assert len(outbox) == 1 and outbox[0]["to"] == "coord@golden.test"      # solo al coordinador del evento
    assert LINK.search(outbox[0]["body"]) and "Abrir el enlace no aprueba nada" in outbox[0]["body"]
    _due(db, "timeout")
    assert len(outbox) == 1                                                 # el segundo aviso no repite el correo
    assert _kinds(db, rid) == ["requested", "email"]


def test_email_goes_out_after_two_minutes_without_an_answer_even_if_the_screen_showed_it(client, env, db, outbox):
    _disable(client, env)
    _ask(client, env)
    _as(client, "coord")
    client.get("/api/reprint-requests/inbox")
    _due(db, "presence")
    assert outbox == []
    _due(db, "timeout")
    assert len(outbox) == 1 and outbox[0]["to"] == "coord@golden.test"


def test_if_the_coordinator_has_no_email_the_admins_get_it(client, env, db, outbox):
    env.coord.email = None
    db.commit()
    _disable(client, env)
    _ask(client, env)
    _due(db)
    assert [m["to"] for m in outbox] == ["adm@golden.test"]


def _mail_token(outbox):
    return LINK.search(outbox[-1]["body"]).group(1)


def test_the_email_link_get_only_shows_and_the_post_decides_once(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db)
    token = _mail_token(outbox)
    client.cookies.clear()
    page = client.get(f"/reimpresion/{token}")
    assert page.status_code == 200 and "Aprobar" in page.text and "Negar" in page.text
    assert page.headers["cache-control"] == "no-store"
    client.get(f"/reimpresion/{token}")                                    # un escáner de correo lo abre dos veces
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "pending"                  # el GET no aprobó nada
    ok = client.post(f"/reimpresion/{token}", data={"decision": "approve"})
    assert ok.status_code == 200 and "Permiso aprobado" in ok.text
    db.expire_all()
    r = db.get(ReprintRequest, rid)
    assert r.status == "approved" and r.decided_channel == "email" and r.decided_by_staff_id == env.coord.id
    assert client.post(f"/reimpresion/{token}", data={"decision": "deny"}).status_code == 410      # reuso: enlace muerto
    assert client.get(f"/reimpresion/{token}").status_code == 410
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "approved"
    _as(client, "dig")
    assert _job(client, env, "1001", True).status_code == 200               # y la reimpresión sale una vez
    assert _kinds(db, rid) == ["requested", "email", "approved", "used"]


def test_the_email_link_can_deny(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db)
    client.cookies.clear()
    assert client.post(f"/reimpresion/{_mail_token(outbox)}", data={"decision": "deny"}).status_code == 200
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "denied"


def test_garbage_unknown_and_expired_tokens_are_all_the_same_dead_page(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db)
    token = _mail_token(outbox)
    client.cookies.clear()
    dead = client.get("/reimpresion/" + "x" * 43)
    assert dead.status_code == 410 and client.post("/reimpresion/" + "x" * 43, data={"decision": "approve"}).status_code == 410
    db.get(ReprintRequest, rid).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    expired = client.get(f"/reimpresion/{token}")
    assert expired.status_code == 410 and expired.text == dead.text         # no se distingue «venció» de «nunca existió»
    assert client.post(f"/reimpresion/{token}", data={"decision": "approve"}).status_code == 410
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "pending"


def test_a_token_only_decides_its_own_request(client, env, db, outbox, monkeypatch):
    monkeypatch.setattr(reprint, "MIN_GAP_SECONDS", 0)
    _disable(client, env)
    a = _ask(client, env, "1001").json()["id"]
    b = _ask(client, env, "1002").json()["id"]
    _due(db)
    assert len(outbox) == 2
    by_request = {}
    for m in outbox:
        t = LINK.search(m["body"]).group(1)
        by_request[db.query(ReprintLink).filter_by(token_hash=reprint.hash_token(t)).one().request_id] = t
    token_a = by_request[a]
    client.cookies.clear()
    client.post(f"/reimpresion/{token_a}", data={"decision": "approve"})
    db.expire_all()
    assert db.get(ReprintRequest, a).status == "approved" and db.get(ReprintRequest, b).status == "pending"


def test_the_token_is_stored_only_as_a_hash_and_cannot_be_guessed(client, env, db, outbox):
    _disable(client, env)
    _ask(client, env)
    _due(db)
    token = _mail_token(outbox)
    link = db.query(ReprintLink).one()
    assert link.token_hash == reprint.hash_token(token) and token not in link.token_hash and len(link.token_hash) == 64
    assert len(token) >= 43                                                 # 256 bits


def test_deciding_on_screen_kills_the_email_link(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db)
    token = _mail_token(outbox)
    _decide(client, "coord", rid, "deny")
    client.cookies.clear()
    assert client.post(f"/reimpresion/{token}", data={"decision": "approve"}).status_code == 410
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "denied"


def test_a_cross_site_post_to_the_link_is_refused(client, env, db, outbox):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _due(db)
    token = _mail_token(outbox)
    client.cookies.clear()
    r = client.post(f"/reimpresion/{token}", data={"decision": "approve"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(ReprintRequest, rid).status == "pending"


def test_the_link_page_is_reachable_without_a_session_and_is_exempt_from_idle(client):
    from app import idle
    assert idle.exempt_path("/reimpresion/abc")
    assert client.get("/reimpresion/nada").status_code == 410


# ---------------------------------------------------------------------------------------------------- auditoría
def test_the_audit_chain_is_complete_and_only_the_decider_reads_it(client, env, db):
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    _as(client, "coord")
    client.get("/api/reprint-requests/inbox")
    client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": "approve"})
    _as(client, "dig")
    assert _job(client, env, "1001", True).status_code == 200
    _as(client, "coord")
    h = client.get(f"/api/events/{env.ev.id}/reprint-requests").json()
    assert h["disabled"] is True and len(h["requests"]) == 1
    row = h["requests"][0]
    assert [a["kind"] for a in row["audit"]] == ["requested", "screen", "approved", "used"]
    assert [a["channel"] for a in row["audit"]] == ["screen", "screen", "screen", "shared"]
    assert row["requested_by"] and row["person"] == "Ana Prueba" and row["status"] == "used"
    _as(client, "coord2")
    assert client.get(f"/api/events/{env.ev.id}/reprint-requests").status_code == 403
    _as(client, "dig")
    assert client.get(f"/api/events/{env.ev.id}/reprint-requests").status_code == 403


def test_expiring_a_pending_request_is_recorded_once(db, env):
    now = utcnow()
    r = ReprintRequest(event_id=env.ev.id, tenant_id=env.ev.tenant_id, user_id="1001", requested_by_staff_id=env.dig.id, status="pending", requested_at=now - timedelta(minutes=20), expires_at=now - timedelta(minutes=10))
    db.add(r)
    db.commit()
    assert reprint.expire_due(db) == 1 and reprint.expire_due(db) == 0
    db.commit()
    assert _kinds(db, r.id) == ["expired"]


def test_nothing_personal_goes_to_the_log(client, env, db, caplog):
    import logging
    caplog.set_level(logging.INFO)
    _disable(client, env)
    _ask(client, env)
    for rec in caplog.records:
        assert "1001" not in rec.getMessage() and "Ana" not in rec.getMessage()


def test_the_registration_page_declares_the_flag_and_loads_the_reprint_script(client, env):
    _as(client, "dig")
    page = client.get(f"/kiosk/{env.ev.id}/registro").text
    assert "window.EVENT_REPRINT_DISABLED = false" in page and "js/reprint.js" in page
    _disable(client, env)
    _as(client, "dig")
    assert "window.EVENT_REPRINT_DISABLED = true" in client.get(f"/kiosk/{env.ev.id}/registro").text


def test_the_coordinator_pages_load_the_inbox_script_and_the_digitador_does_not(client, env):
    _as(client, "coord")
    assert "js/reprint-inbox.js" in client.get("/eventos").text
    _as(client, "dig")
    assert "js/reprint-inbox.js" not in client.get(f"/kiosk/{env.ev.id}/registro").text


def test_the_new_job_kinds_are_registered():
    assert {"reprint_notify", "reprint_mail"} <= set(jobs.GENERAL_KINDS)
    assert jobs.HANDLER_MODULES["reprint_notify"] == "app.reprint"


# ---------------------------------------------------------------------------------------------------- revisión de seguridad
def _print_log(client, env, uid):
    return client.post(f"/api/users/{uid}/print-log", params={"event_id": env.ev.id})


def test_undo_and_repeat_does_not_reprint_when_disabled(client, env, db):
    """Deshacer una acreditación no borra el PrintLog: acreditar otra vez NO da otra escarapela sin permiso (ni por print-log ni por la cola compartida)."""
    _disable(client, env)
    _as(client, "dig")
    assert _print_log(client, env, "1004").status_code == 200                 # primera impresión
    db.add(AccessLog(tenant_id=env.ev.tenant_id, user_id="1004", event_id=env.ev.id, record_type="Existente", registration_method="tradicional", client_id="c-undo", registered_by_staff_id=env.dig.id, timestamp=utcnow()))
    db.commit()
    assert client.post(f"/api/events/{env.ev.id}/accreditations/undo", json={"client_id": "c-undo"}).status_code == 200
    db.add(AccessLog(tenant_id=env.ev.tenant_id, user_id="1004", event_id=env.ev.id, record_type="Existente", registration_method="tradicional", client_id="c-again", registered_by_staff_id=env.dig.id, timestamp=utcnow()))
    db.commit()
    again = _print_log(client, env, "1004")
    assert again.status_code == 403 and again.json()["detail"].startswith("No se puede reimprimir")
    assert _job(client, env, "1004", False).status_code == 403
    count = client.get("/api/users/1004/print-count", params={"event_id": env.ev.id}).json()
    assert count["times_printed"] == 1 and count["reprint_locked"] is True       # lo que la pantalla usa para no reimprimir sola


def test_print_log_needs_the_permission_that_was_just_spent(client, env):
    _disable(client, env)
    _as(client, "dig")
    assert _print_log(client, env, "1001").status_code == 403
    rid = _ask(client, env).json()["id"]
    _decide(client, "coord", rid, "approve")
    _as(client, "dig")
    assert _print_log(client, env, "1001").status_code == 403                 # aprobada pero sin gastar: la pantalla la gasta primero
    assert client.post(f"/api/events/{env.ev.id}/reprint-requests/use", json={"user_id": "1001"}).status_code == 200
    assert _print_log(client, env, "1001").status_code == 200


def test_print_log_is_untouched_when_reprint_is_enabled(client, env):
    _as(client, "dig")
    assert _print_log(client, env, "1001").status_code == 200


def test_other_tenant_cannot_change_see_or_decide(client, env, factory):
    factory.tenant("beta")
    factory.staff("admin", "adm_b", tenant_id="beta")
    factory.staff("coordinador", "coord_b", tenant_id="beta")
    _as(client, "adm_b")
    assert client.put(f"/api/events/{env.ev.id}/reprint-mode", json={"disabled": True}).status_code == 404
    _disable(client, env)
    rid = _ask(client, env).json()["id"]
    for who in ("adm_b", "coord_b"):
        _as(client, who)
        body = client.get("/api/reprint-requests/inbox").json()
        assert body["requests"] == [] and body["watch"] is False
        assert client.post(f"/api/reprint-requests/{rid}/decision", json={"decision": "approve"}).status_code == 404
        assert client.get(f"/api/events/{env.ev.id}/reprint-requests").status_code == 403
    _as(client, "coord")
    assert [r["id"] for r in client.get("/api/reprint-requests/inbox").json()["requests"]] == [rid]


def test_inbox_only_asks_to_poll_when_there_is_something_to_watch(client, env):
    _as(client, "coord")
    quiet = client.get("/api/reprint-requests/inbox").json()
    assert quiet["watch"] is False and quiet["requests"] == []               # habilitada: la pantalla deja de sondear
    _disable(client, env)
    _as(client, "coord")
    idle = client.get("/api/reprint-requests/inbox").json()
    assert idle["watch"] is True and idle["poll_ms"] == 30000                # deshabilitada, sin pendientes: 30 s
    _as(client, "coord2")
    assert client.get("/api/reprint-requests/inbox").json()["watch"] is False  # otro coordinador: no es suyo
    _ask(client, env)
    _as(client, "coord")
    busy = client.get("/api/reprint-requests/inbox").json()
    assert busy["poll_ms"] == 10000 and len(busy["requests"]) == 1           # con una pendiente: 10 s


def test_email_link_paths_are_masked_in_logs():
    from app import obs
    assert obs.mask_url("/reimpresion/AbC_dEf-123456") == "/reimpresion/[token]"
    assert "AbC" not in obs.mask_url("/reimpresion/AbC_dEf-123456?x=1")


def test_the_email_link_is_rate_limited_per_ip(client, monkeypatch):
    from app.routers import reprint as router
    monkeypatch.setattr(router, "LINK_GET_MAX", 3)
    monkeypatch.setattr(router, "LINK_POST_MAX", 2)
    codes = [client.get("/reimpresion/nada").status_code for _ in range(5)]
    assert codes[:3] == [410, 410, 410] and codes[3:] == [429, 429]
    codes = [client.post("/reimpresion/nada", data={"decision": "approve"}).status_code for _ in range(4)]
    assert codes == [410, 410, 429, 429]
