"""Fase 4: «Autorizar a todos los pendientes» (POST /api/events/{id}/staff-users/approve-all; app/routers/login_approval.py)."""
from datetime import timedelta
from pathlib import Path

import pytest

from app import login_control
from app.models import AuditAction, StaffUser
from app.timeutil import utcnow
from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def ev(factory):
    factory.staff("coordinador", "coord")
    return factory.event("en_proceso")


def _digitadores(factory, db, ev, n, status=login_control.PENDING):
    out = []
    for i in range(n):
        d = factory.staff("digitador", f"9000{i:04d}")
        factory.authorize(ev, d)
        db.query(StaffUser).filter_by(id=d.id).update({"login_req_hash": f"h{d.id}" * 3, "login_req_at": utcnow(), "login_req_status": status})
        out.append(d.id)
    db.commit()
    return out


def _url(ev):
    return f"/api/events/{ev.id}/staff-users/approve-all"


def _post(client, db, ev, reqs=None):
    """Como el botón: manda el código de cada solicitud pendiente que se está viendo (el `req` de login-state)."""
    if reqs is None:
        db.expire_all()
        reqs = {str(s.id): (s.login_req_hash or "")[:6] for s in db.query(StaffUser).filter(StaffUser.login_req_status == login_control.PENDING)}
    return client.post(_url(ev), json={"reqs": reqs})


def _status(db, sid):
    db.expire_all()
    return db.get(StaffUser, sid).login_req_status


def test_approves_every_pending_one_and_is_idempotent(client, factory, db, ev):
    ids = _digitadores(factory, db, ev, 30)
    login(client, "coord")
    r = _post(client, db, ev)
    assert r.status_code == 200 and r.json()["approved"] == 30 and r.json()["skipped"] == 0 and r.json()["truncated"] is False
    assert all(_status(db, i) == login_control.APPROVED for i in ids)
    again = _post(client, db, ev).json()
    assert again["approved"] == 0 and again["skipped"] == 0
    assert db.query(AuditAction).filter_by(action="approve", entity="login_request").count() == 30       # una sola vez cada uno


def test_skips_locked_expired_and_already_answered(client, factory, db, ev):
    ok, locked, expired, denied = _digitadores(factory, db, ev, 4)
    db.query(StaffUser).filter_by(id=locked).update({"locked_at": utcnow()})
    db.query(StaffUser).filter_by(id=expired).update({"login_req_at": utcnow() - timedelta(minutes=6)})
    db.query(StaffUser).filter_by(id=denied).update({"login_req_status": login_control.DENIED})
    db.commit()
    login(client, "coord")
    d = _post(client, db, ev).json()
    assert d["approved"] == 1 and d["skipped"] == 2
    assert d["skipped_reasons"] == {"cuenta bloqueada": 1, "solicitud vencida": 1}
    assert _status(db, ok) == login_control.APPROVED and _status(db, locked) == login_control.PENDING
    assert _status(db, expired) == login_control.PENDING and _status(db, denied) == login_control.DENIED


def test_other_events_digitadores_are_not_touched(client, factory, db, ev):
    mine = _digitadores(factory, db, ev, 2)
    other = factory.event("en_proceso")
    theirs = _digitadores(factory, db, other, 2)
    login(client, "coord")
    assert _post(client, db, ev).json()["approved"] == 2
    assert all(_status(db, i) == login_control.PENDING for i in theirs) and all(_status(db, i) == login_control.APPROVED for i in mine)


def test_can_approve_hook_skips_with_reason(client, factory, db, ev, monkeypatch):
    a, b = _digitadores(factory, db, ev, 2)
    monkeypatch.setattr(login_control, "can_approve", lambda _db, _ev, t: (False, "compromiso pendiente") if t.id == b else (True, ""))
    login(client, "coord")
    d = _post(client, db, ev).json()
    assert d["approved"] == 1 and d["skipped_reasons"] == {"compromiso pendiente": 1}
    assert _status(db, a) == login_control.APPROVED and _status(db, b) == login_control.PENDING
    assert client.post(f"/api/events/{ev.id}/staff-users/{b}/login-request", json={"allow": True}).status_code == 409          # el botón individual usa el mismo gancho


def test_roles(client, factory, db, ev):
    ids = _digitadores(factory, db, ev, 1)
    factory.staff("digitador", "dig")
    factory.staff("cliente", "cli")
    factory.staff("comercial", "com")
    for user in ("dig", "cli", "com"):
        login(client, user)
        assert _post(client, db, ev).status_code == 403, user
        client.post("/logout")
    assert _status(db, ids[0]) == login_control.PENDING
    login(client, "coord")
    assert _post(client, db, ev).status_code == 200


def test_foreign_tenant_event_is_refused(client, factory, db):
    factory.staff("coordinador", "coord", tenant_id="acme")
    other = factory.event("en_proceso", tenant_id="otra")
    login(client, "coord")
    assert _post(client, db, other).status_code in (403, 404)


def test_finished_event_is_refused(client, factory, db):
    factory.staff("coordinador", "coord")
    fin = factory.event("finalizado")
    ids = _digitadores(factory, db, fin, 1)
    login(client, "coord")
    assert _post(client, db, fin).status_code == 400
    assert _status(db, ids[0]) == login_control.PENDING


def test_audit_has_event_count_and_actor_without_personal_data(client, factory, db, ev):
    _digitadores(factory, db, ev, 3)
    login(client, "coord")
    _post(client, db, ev)
    row = db.query(AuditAction).filter_by(action="approve_all").one()
    assert row.entity == "event_login_requests" and row.entity_id == str(ev.id) and row.actor_id and row.detail == "autorizados 3; omitidos 0"
    assert "9000" not in (row.detail or "")


def test_rate_limit_per_user(client, factory, db, ev):
    login(client, "coord")
    from app.routers.login_approval import APPROVE_ALL_PER_MINUTE
    for _ in range(APPROVE_ALL_PER_MINUTE):
        assert _post(client, db, ev).status_code == 200
    assert _post(client, db, ev).status_code == 429


def test_cap_per_call(client, factory, db, ev, monkeypatch):
    from app.routers import login_approval
    monkeypatch.setattr(login_approval, "APPROVE_ALL_MAX", 2)
    ids = _digitadores(factory, db, ev, 3)
    login(client, "coord")
    d = _post(client, db, ev).json()
    assert d["approved"] == 2 and d["truncated"] is True
    assert sum(_status(db, i) == login_control.APPROVED for i in ids) == 2


def test_route_is_covered_by_the_archived_base_guard_scan():
    """El guard de base archivada (tests/test_base_archivada_guard.py) escanea toda función con get_event_for_staff: esta debe estar ahí y, al no tocar personas/respuestas/pagos, figurar en su lista ALLOW."""
    from tests.test_base_archivada_guard import ALLOW, _functions_with_event_access
    seen = {(f, n) for f, n, _ in _functions_with_event_access()}
    assert ("login_approval.py", "approve_all_pending") in seen
    assert "approve_all_pending" in ALLOW["login_approval.py"]


def test_frontend_wiring_has_no_inline_js():
    html = (ROOT / "templates" / "kiosk_usuarios.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "usuarios.js").read_text(encoding="utf-8")
    assert 'id="approveAllBtn"' in html and "hidden" in html.split('id="approveAllBtn"')[1].split(">")[0] and "onclick" not in html.split('id="approveAllBtn"')[1].split("</button>")[0]
    assert "staff-users/approve-all" in js and "showConfirm(" in js and "pendingCount < 1" in js


def test_a_request_that_replaced_the_one_being_viewed_is_not_approved_blindly(client, factory, db, ev):
    a, b = _digitadores(factory, db, ev, 2)
    login(client, "coord")
    seen = {str(a): f"h{a}"[:6] + "", str(b): "zzzzzz"}          # b: el código que vio no es el vigente (otra solicitud lo reemplazó)
    seen[str(a)] = db.get(StaffUser, a).login_req_hash[:6]
    d = _post(client, db, ev, seen).json()
    assert d["approved"] == 1 and d["skipped"] == 1
    assert _status(db, a) == login_control.APPROVED and _status(db, b) == login_control.PENDING
    assert client.post(_url(ev)).status_code == 400                                                     # sin la lista de lo visto no se autoriza nada
