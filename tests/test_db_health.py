"""Chequeo semanal de salud de la base (app/db_health.py): reglas puras, decisión de reiniciar y programación semanal. Sin base: simulaciones."""
import pytest

from app import db_health

TH = {"size_warn_gb": 6, "size_crit_gb": 9, "conn_warn_pct": 60, "conn_crit_pct": 85, "long_query_s": 300, "idle_tx_s": 600, "blocked_crit": 5}
GB = 1024 ** 3


def stats(**kw):
    base = {"size_bytes": GB // 4, "max_connections": 100, "connections": 10, "idle_tx": 0, "longest_s": 0, "blocked": 0}
    base.update(kw)
    return base


def test_ok_when_everything_is_calm():
    v = db_health.evaluate(stats(), TH)
    assert v["level"] == "ok" and not v["findings"] and not v["restart_recommended"]


def test_unreachable_is_critical_and_restarts():
    v = db_health.evaluate(None, TH)
    assert v["level"] == "critical" and v["restart_recommended"]


@pytest.mark.parametrize("kw,level", [({"connections": 65}, "warn"), ({"connections": 90}, "critical"), ({"size_bytes": 7 * GB}, "warn"), ({"size_bytes": 10 * GB}, "critical"),
                                      ({"blocked": 1}, "warn"), ({"blocked": 6}, "critical"), ({"longest_s": 400}, "warn"), ({"idle_tx": 2}, "warn")])
def test_levels(kw, level):
    v = db_health.evaluate(stats(**kw), TH)
    assert v["level"] == level and v["restart_recommended"] == (level == "critical")


def test_critical_wins_over_warn():
    v = db_health.evaluate(stats(connections=95, longest_s=999), TH)
    assert v["level"] == "critical" and len(v["findings"]) == 2


def _run(monkeypatch, st, events=0, restart_ok=True, back=True, configured=True):
    calls = {"restart": 0, "notified": []}
    monkeypatch.setattr(db_health, "collect", lambda *a, **k: st)
    monkeypatch.setattr(db_health, "running_events", lambda: events)
    monkeypatch.setattr(db_health, "neon_configured", lambda: configured)

    def restart():
        calls["restart"] += 1
        if not restart_ok:
            raise RuntimeError("falló")
        return "ok"
    monkeypatch.setattr(db_health, "restart_compute", restart)
    monkeypatch.setattr(db_health, "_wait_back", lambda *a, **k: back)
    monkeypatch.setattr(db_health, "notify", lambda level, findings, action: calls["notified"].append((level, action)) or 1)
    return calls


def test_healthy_run_does_nothing(monkeypatch):
    c = _run(monkeypatch, stats())
    assert db_health.run().startswith("base sana") and c["restart"] == 0 and not c["notified"]


def test_critical_restarts_when_no_event_and_alerts(monkeypatch):
    c = _run(monkeypatch, stats(connections=95))
    assert "reinició" in db_health.run() and c["restart"] == 1 and c["notified"][0][0] == "critical"


def test_does_not_restart_with_event_running(monkeypatch):
    c = _run(monkeypatch, stats(connections=95), events=1)
    with pytest.raises(RuntimeError):
        db_health.run()
    assert c["restart"] == 0 and "NO se reinició" in c["notified"][0][1]


def test_unreachable_restarts_even_without_knowing_events(monkeypatch):
    c = _run(monkeypatch, None)
    db_health.run()
    assert c["restart"] == 1


def test_restart_disabled_by_env(monkeypatch):
    monkeypatch.setenv("DB_HEALTH_RESTART", "0")
    c = _run(monkeypatch, stats(connections=95))
    with pytest.raises(RuntimeError):
        db_health.run()
    assert c["restart"] == 0


def test_restart_failure_is_reported_not_hidden(monkeypatch):
    c = _run(monkeypatch, stats(connections=95), restart_ok=False)
    with pytest.raises(RuntimeError):
        db_health.run()
    assert "falló" in c["notified"][0][1]


def test_still_down_after_restart_raises(monkeypatch):
    _run(monkeypatch, None, back=False)
    with pytest.raises(RuntimeError):
        db_health.run()


def test_warn_alerts_without_restart(monkeypatch):
    c = _run(monkeypatch, stats(longest_s=500))
    assert "warn" in db_health.run() and c["restart"] == 0 and c["notified"][0][0] == "warn"


def test_neon_restart_endpoint_and_schedule_wiring():
    import pathlib
    src = pathlib.Path(db_health.__file__).read_text(encoding="utf-8")
    assert "/restart" in src and "DELETE" not in src and "DROP TABLE" not in src.upper() and "TRUNCATE" not in src.upper()          # nunca borra datos
    runner = (pathlib.Path(db_health.__file__).parent / "ops_runner.py").read_text(encoding="utf-8")
    assert '"db-health"' in runner and "OPS_HEALTH_WEEKDAY" in runner


def test_economic_runs_db_health_only_on_sunday_morning(monkeypatch):
    from datetime import datetime

    from app import ops_runner, ops_state
    ran = []
    monkeypatch.setattr(ops_state, "save_steps", lambda s: None)
    monkeypatch.setattr(ops_state, "recently_active", lambda now_utc=None: False)
    for fn in ("backup_db", "purge", "archive_events", "check_backups", "offsite_copy", "sweep", "warmup", "warmup_down", "purge_reports", "import_infra_costs"):
        monkeypatch.setattr(ops_runner, fn, lambda *a, **k: "ok")
    monkeypatch.setattr(ops_runner, "db_health", lambda: ran.append("db") or "ok")
    monkeypatch.delenv("GCP_BILLING_EXPORT_TABLE", raising=False)
    probe = lambda *a: {"running": 0, "near": 0, "jobs_due": 0}          # noqa: E731
    sunday_early = datetime(2026, 11, 22, 5, 5)            # domingo 5:05: aún no es la hora
    sunday = datetime(2026, 11, 22, 6, 5)
    monday = datetime(2026, 11, 23, 6, 5)
    for when in (sunday_early, monday):
        ops_runner.economic(now=when, now_utc=when, steps={}, probe_fn=probe)
    assert ran == []
    ops_runner.economic(now=sunday, now_utc=sunday, steps={}, probe_fn=probe)
    assert ran == ["db"]
