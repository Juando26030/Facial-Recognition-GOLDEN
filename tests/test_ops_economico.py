"""Job horario ECONÓMICO (10-nov-2026): cada paso decide por el tiempo desde su última ejecución y la base solo se toca si hace falta.
Pruebas puras (corren con `pytest --noconftest`): sin base, sin nube; todo lo que toca el exterior se reemplaza."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import ops_runner, ops_state

ROOT = Path(__file__).resolve().parent.parent
NOW_UTC = datetime(2026, 11, 10, 15, 5)          # 10:05 en Bogotá
NOW = datetime(2026, 11, 10, 10, 5)              # (el reloj local se pasa a mano)


def _iso(**ago):
    return (NOW_UTC - timedelta(**ago)).replace(microsecond=0).isoformat()


@pytest.fixture
def env(monkeypatch):
    ran = []
    for name in ("OPS_DAILY_HOUR", "OPS_PURGE_HOUR", "OPS_WEEKLY_DAY", "OPS_WEEKLY_HOUR", "OPS_IDLE_EVERY_H", "OPS_IDLE_BACKUP_H", "GCP_BILLING_EXPORT_TABLE"):
        monkeypatch.delenv(name, raising=False)
    saved = {}
    monkeypatch.setattr(ops_state, "save_steps", lambda s: saved.update(s))
    monkeypatch.setattr(ops_state, "recently_active", lambda now_utc=None: False)
    monkeypatch.setattr(ops_runner, "backup_db", lambda kind, now=None: ran.append("backup-" + kind) or kind)
    for fn in ("purge", "archive_events", "check_backups", "offsite_copy", "sweep", "warmup", "warmup_down", "purge_reports", "import_infra_costs"):
        monkeypatch.setattr(ops_runner, fn, (lambda n: lambda: ran.append(n) or "ok")(fn))
    return ran, saved


def _all_fresh(**over):
    steps = {k: _iso(minutes=10) for k in ("probe", "backup", "backup-daily", "purge", "archive-events", "check-backups", "offsite-copy", "reports")}
    steps["warm_up"] = ""
    steps.update(over)
    return steps


def test_nothing_due_and_idle_touches_nothing(env):
    ran, _ = env
    probes = []
    r = ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=_all_fresh(), probe_fn=lambda *a: probes.append(1))
    assert r == {} and ran == [] and probes == []        # ni la consulta de la base


def test_idle_slot_probes_once_and_skips_warmup_and_sweep(env):
    ran, _ = env
    steps = _all_fresh(probe=_iso(hours=5))
    r = ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=steps, probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert r["probe"]["ok"] and set(r) == {"probe"}
    assert "warmup" not in ran and "sweep" not in ran and "backup-hourly" not in ran       # el respaldo sin actividad espera sus 8 h


def test_running_event_warms_sweeps_and_backs_up_hourly(env, monkeypatch):
    ran, saved = env
    steps = _all_fresh(probe=_iso(hours=5), backup=_iso(minutes=55))
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=steps, probe_fn=lambda *a: {"running": 1, "near": 0, "jobs_due": 2})
    assert {"warmup", "sweep", "backup-hourly"} <= set(ran) and saved["warm_up"] == "1"


def test_activity_hint_alone_counts_as_busy(env, monkeypatch):
    ran, _ = env
    monkeypatch.setattr(ops_state, "recently_active", lambda now_utc=None: True)
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=_all_fresh(backup=_iso(minutes=55)), probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert "warmup" in ran and "backup-hourly" in ran


def test_scale_down_runs_once_without_touching_the_database(env):
    ran, saved = env
    steps = _all_fresh(warm_up="1")
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=steps, probe_fn=lambda *a: (_ for _ in ()).throw(AssertionError("no debía consultar")))
    assert ran == ["warmup_down"] and saved["warm_up"] == ""


def test_probe_failure_assumes_the_worst_but_does_not_stop_other_steps(env):
    ran, _ = env
    def boom(*a):
        raise RuntimeError("base caída")
    r = ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=_all_fresh(probe=_iso(hours=5)), probe_fn=boom)
    assert r["probe"]["ok"] is False and "sweep" in ran and "warmup" in ran


def test_daily_backup_and_purge_run_once_per_day_even_if_the_job_misses_their_hour(env):
    ran, saved = env
    steps = _all_fresh(**{"backup-daily": _iso(days=1, hours=1), "purge": _iso(days=1, hours=1)})      # el Job cada 2 h cae a las 10:05, no a las 3 o 4
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=steps, probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert "backup-daily" in ran and "purge" in ran
    assert saved["purge"] == NOW_UTC.isoformat() and saved["backup-daily"] == NOW_UTC.isoformat()
    ran.clear()
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=dict(saved), probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert "purge" not in ran and "backup-daily" not in ran


def test_a_failed_purge_is_not_marked_and_retries_next_time(env, monkeypatch):
    ran, saved = env
    monkeypatch.setattr(ops_runner, "purge", lambda: (_ for _ in ()).throw(RuntimeError("falló al borrar")))
    steps = _all_fresh(purge=_iso(days=2))
    r = ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps=steps, probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert r["purge"]["ok"] is False and saved["purge"] == _iso(days=2)


def test_unreadable_state_means_everything_is_due(env):
    ran, _ = env
    ops_runner.economic(now=NOW, now_utc=NOW_UTC, steps={}, probe_fn=lambda *a: {"running": 0, "near": 0, "jobs_due": 0})
    assert {"check_backups", "offsite_copy"} <= set(ran)
    assert "backup-hourly" in ran and "backup-daily" in ran and "purge" in ran


def test_weekly_and_monthly_helpers():
    sun = datetime(2026, 11, 8, 5, 5)
    assert ops_state.due_weekly({}, "x", sun, 6, 5) is True                    # nunca corrió y es domingo 5 a. m.
    assert ops_state.due_weekly({}, "x", datetime(2026, 11, 10, 10, 5), 6, 5) is False
    assert ops_state.due_monthly({}, "m", datetime(2026, 11, 2, 6, 5), 2, 6) is True
    assert ops_state.due_monthly({}, "m", datetime(2026, 11, 1, 6, 5), 2, 6) is False


def test_min_interval_default_is_safe_and_configurable(monkeypatch):
    monkeypatch.delenv("OPS_MIN_INTERVAL_MINUTES", raising=False)
    assert ops_state.min_interval_minutes() == 50
    monkeypatch.setenv("OPS_MIN_INTERVAL_MINUTES", "110")
    assert ops_state.min_interval_minutes() == 110
    monkeypatch.setenv("OPS_MIN_INTERVAL_MINUTES", "basura")
    assert ops_state.min_interval_minutes() == 50


def test_main_hourly_exits_fast_when_called_again_too_soon(monkeypatch, capsys):
    monkeypatch.setattr(ops_state, "load_steps", lambda: {"full_run": ops_runner.utcnow().replace(microsecond=0).isoformat()})
    monkeypatch.setattr(ops_runner, "economic", lambda **k: (_ for _ in ()).throw(AssertionError("no debía correr")))
    assert ops_runner.main("hourly") == 0
    assert "OPS_MIN_INTERVAL_MINUTES" in capsys.readouterr().out


def test_main_hourly_reports_skip_when_nothing_is_due(monkeypatch, capsys):
    monkeypatch.setattr(ops_state, "load_steps", lambda: {})
    monkeypatch.setattr(ops_runner, "economic", lambda **k: {})
    assert ops_runner.main("hourly") == 0
    assert "skipped" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# ---- pruebas de texto: el código fuente respeta las reglas de costo
def test_probe_is_a_single_statement_and_hot_paths_do_not_touch_the_database():
    sql = ops_runner.PROBE_SQL
    assert sql.count("SELECT count(*)") == 3 and "en_proceso" in sql and "jobs" in sql
    ops_src = (ROOT / "app/routers/ops.py").read_text(encoding="utf-8")
    m = re.search(r'@router.get\("/health"\)\n@router.get\("/healthz"\)\nasync def healthz\(\) -> dict:\n    return \{"status": "ok"\}', ops_src)
    assert m, "/health debe seguir sin tocar la base"


def test_scheduler_schedule_is_overridable_and_default_stays_hourly():
    sh = (ROOT / "deploy/gcp/scheduler.sh").read_text(encoding="utf-8")
    assert 'SCHEDULE="${OPS_SCHEDULE:-5 * * * *}"' in sh and "OPS_SCHEDULE_MAX_AGE_H" in sh


def test_tv_screen_slows_down_when_nothing_changes():
    js = (ROOT / "static/js/queue-tv.js").read_text(encoding="utf-8")
    assert "setInterval" not in js and "30 * 60000" in js and "document.hidden" in js
