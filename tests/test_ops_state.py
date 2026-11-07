"""Modo tranquilo del Job horario (7-nov-2026): sin actividad la base descansa; con actividad o en las horas fijas corre completo; sin poder leer el archivito, corre completo."""
from datetime import datetime, timedelta

from app import ops_state
from app.timeutil import utcnow


def _local(hour):
    return datetime(2026, 11, 9, hour, 5)


def test_runs_fully_in_the_fixed_hours_even_when_idle(monkeypatch):
    monkeypatch.setattr(ops_state, "last_activity", lambda: None)
    for h in (3, 4, 5, 11, 19):
        assert ops_state.idle_skip(_local(h)) is None


def test_skips_other_hours_when_there_was_no_recent_activity(monkeypatch):
    monkeypatch.setattr(ops_state, "last_activity", lambda: None)
    assert "descansa" in ops_state.idle_skip(_local(9))
    monkeypatch.setattr(ops_state, "last_activity", lambda: utcnow() - timedelta(hours=5))
    assert ops_state.idle_skip(_local(9)) is not None


def test_runs_every_hour_with_recent_activity(monkeypatch):
    monkeypatch.setattr(ops_state, "last_activity", lambda: utcnow() - timedelta(minutes=40))
    assert ops_state.idle_skip(_local(9)) is None


def test_unreadable_marker_means_run(monkeypatch):
    def boom():
        raise OSError("sin acceso")
    monkeypatch.setattr(ops_state, "last_activity", boom)
    assert ops_state.idle_skip(_local(9)) is None


def test_main_hourly_skips_without_opening_the_database(monkeypatch, capsys):
    from app import ops_runner
    monkeypatch.setattr(ops_state, "last_activity", lambda: None)
    monkeypatch.setattr(ops_runner, "_local_now", lambda: _local(9))
    monkeypatch.setattr(ops_runner, "hourly", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debía correr")))
    assert ops_runner.main("hourly") == 0
    assert "skipped" in capsys.readouterr().out
