"""L7 (aprobado por la auditora): a los 90 días de cerrado un evento se ARCHIVA solo (nunca se borra) en el Job horario; idempotente; deja rastro con actor NULL; el super_admin lo desarchiva."""
from datetime import date, timedelta

from app import event_archive, ops_runner
from app.models import AuditAction, Event, EventAttendee, User
from app.timeutil import utcnow


def _finished(factory, db, days_ago, **kw):
    ev = factory.event("en_proceso", **kw)
    ev.status = "finalizado"
    db.commit()
    ev.finalized_at = utcnow() - timedelta(days=days_ago)
    db.commit()
    return ev


def test_only_finished_events_older_than_90_days_are_archived(factory, db):
    old = _finished(factory, db, 91)
    edge = _finished(factory, db, 89)
    running = factory.event("en_proceso")
    created = factory.event("creado")
    r = event_archive.auto_archive_due(db)
    assert r["archived"] == 1 and r["ids"] == [old.id] and r["days"] == 90
    db.expire_all()
    assert db.get(Event, old.id).archived_at is not None and db.get(Event, old.id).archived_by_id is None
    assert all(db.get(Event, e.id).archived_at is None for e in (edge, running, created))


def test_it_is_idempotent_and_logs_with_null_actor_once(factory, db):
    ev = _finished(factory, db, 120)
    assert event_archive.auto_archive_due(db)["archived"] == 1
    assert event_archive.auto_archive_due(db)["archived"] == 0
    rows = db.query(AuditAction).all()
    assert len(rows) == 1
    r = rows[0]
    assert (r.action, r.entity, r.entity_id, r.actor_id, r.actor_role) == ("archive", "event", str(ev.id), None, None)
    assert "automático" in r.detail and "90" in r.detail


def test_it_never_deletes_anything(factory, db):
    ev = _finished(factory, db, 200)
    factory.person(ev, "1001")
    people, attendees = db.query(User).count(), db.query(EventAttendee).count()
    event_archive.auto_archive_due(db)
    db.expire_all()
    assert db.query(User).count() == people and db.query(EventAttendee).count() == attendees and db.get(Event, ev.id) is not None


def test_without_finalized_at_it_falls_back_to_end_date(factory, db):
    ev = _finished(factory, db, 1, end_date=date.today() - timedelta(days=100))
    ev.finalized_at = None
    db.commit()
    assert event_archive.closed_at(ev).date() == ev.end_date
    assert event_archive.auto_archive_due(db)["ids"] == [ev.id]
    fresh = _finished(factory, db, 1, end_date=date.today() - timedelta(days=10))
    fresh.finalized_at = None
    db.commit()
    assert event_archive.auto_archive_due(db)["archived"] == 0


def test_a_restored_event_is_not_archived_again_until_it_is_finished_again(factory, db):
    ev = _finished(factory, db, 100)
    event_archive.auto_archive_due(db)
    sup = factory.staff("super_admin", "sup")
    db.expire_all()
    event_archive.restore(db, db.get(Event, ev.id), sup)
    db.commit()
    r = event_archive.auto_archive_due(db)
    assert r["archived"] == 0 and r["skipped_restored"] == 1            # restaurado a mano: el Job lo respeta
    db.expire_all()
    e = db.get(Event, ev.id)
    e.status = "en_proceso"
    db.commit()
    e.status = "finalizado"
    db.commit()
    e.finalized_at = utcnow() - timedelta(days=95)            # un cierre NUEVO (posterior a la restauración) vuelve a correr su reloj de 90 días
    db.commit()
    from app.models import AuditAction
    db.query(AuditAction).filter(AuditAction.action == "restore").update({"at": utcnow() - timedelta(days=200)})
    db.commit()
    assert event_archive.auto_archive_due(db)["archived"] == 1


def test_days_can_be_changed_by_environment(factory, db, monkeypatch):
    _finished(factory, db, 40)
    assert event_archive.auto_archive_due(db)["archived"] == 0
    monkeypatch.setenv("EVENT_AUTO_ARCHIVE_DAYS", "30")
    assert event_archive.auto_archive_due(db)["archived"] == 1


def test_hourly_job_runs_the_step_and_a_failure_does_not_stop_the_others(monkeypatch):
    ran = []
    monkeypatch.setattr(ops_runner, "backup_db", lambda kind, now=None: ran.append(kind) or kind)
    monkeypatch.setattr(ops_runner, "check_backups", lambda: "ok")
    monkeypatch.setattr(ops_runner, "sweep", lambda: "ok")
    monkeypatch.setattr(ops_runner, "archive_events", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(ops_runner, "purge_reports", lambda: ran.append("reports") or "ok")
    monkeypatch.setattr(ops_runner, "warmup", lambda: ran.append("warmup") or "ok")
    from datetime import datetime
    r = ops_runner.hourly(now=datetime(2026, 11, 7, 9, 5))
    assert r["archive-events"]["ok"] is False and ran == ["hourly", "reports", "warmup"]
    assert "archive-events" in ops_runner.TASKS


def test_archive_events_step_returns_counts_only(factory, db):
    _finished(factory, db, 100)
    out = ops_runner.archive_events()
    assert '"archived": 1' in out
