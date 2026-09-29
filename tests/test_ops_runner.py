"""Job de operaciones (app/ops_runner.py) y precalentamiento (app/warmup.py): respaldos, revisión, orden de los pasos, plan y aplicación."""
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import ops, ops_runner, warmup
from app.models import SystemEvent, WebForm
from tests.conftest import login
from tests.test_forms import _create, _status


# ------------------------------------------------------------------ precalentamiento
def test_plan_is_cold_when_nothing_is_happening(db):
    p = warmup.plan(db)
    assert (p["web"], p["publico"], p["biometria"]) == (0, 0, 0)
    assert p["neon"] == {"suspend_timeout_seconds": 0, "autoscaling_limit_min_cu": 0.25}


def test_plan_warms_for_events_in_progress_and_form_openings(db, factory):
    factory.event("en_proceso", facial_enabled=True)
    ev = factory.event("creado")
    soon = datetime.now().replace(microsecond=0) + timedelta(minutes=30)
    form = WebForm(event_id=ev.id, name="F", slug="f", manual_status="cerrado", use_schedule=True, design_json="{}", settings_json="{}", test_key="k",
                   schedule_json=json.dumps([{"from": soon.isoformat(timespec="minutes"), "status": "activo"}]))
    db.add(form)
    db.commit()
    p = warmup.plan(db, now_local=soon - timedelta(minutes=30))
    assert (p["web"], p["publico"], p["biometria"]) == (2, 2, 1)
    assert p["neon"] == {"suspend_timeout_seconds": -1, "autoscaling_limit_min_cu": 0.5}
    assert warmup.plan(db, now_local=soon + timedelta(hours=3))["publico"] == 0                # la apertura ya pasó hace rato


def test_opening_a_form_by_hand_warms_now_and_leaves_a_trace(client, factory, db, monkeypatch):
    kicks = []
    monkeypatch.setattr(warmup, "kick", lambda: kicks.append(1))
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    f = _create(client, ev)
    assert _status(client, ev, f, manual_status="activo").status_code == 200
    assert kicks == [1] and db.query(SystemEvent).filter_by(kind="form_opened", ref=str(f["id"])).count() == 1
    assert warmup.plan(db)["publico"] == 2
    assert client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso"}).status_code == 200
    assert kicks == [1, 1]                                                                  # evento a «en proceso»: también


def test_apply_only_changes_what_differs(monkeypatch):
    current = {"svc/web": 0, "svc/publico": 2, "svc/bio": 0}
    calls = []
    monkeypatch.setattr(warmup.cloudrun, "min_instances", lambda s: current[s])
    monkeypatch.setattr(warmup.cloudrun, "set_min_instances", lambda s, n: calls.append((s, n)))
    for k, v in {"WARM_SERVICE_WEB": "svc/web", "WARM_SERVICE_PUBLICO": "svc/publico", "WARM_SERVICE_BIOMETRIA": "svc/bio",
                 "NEON_API_KEY": "k", "NEON_PROJECT_ID": "p", "NEON_ENDPOINT_ID": "e"}.items():
        monkeypatch.setenv(k, v)
    neon = []
    monkeypatch.setattr(warmup, "_neon", lambda m, path, **kw: {"endpoint": {"suspend_timeout_seconds": 0, "autoscaling_limit_min_cu": 0.25,
                                                                             "autoscaling_limit_max_cu": 4}} if m == "GET" else neon.append(kw["json"]))
    plan = {"web": 2, "publico": 2, "biometria": 0, "neon": {"suspend_timeout_seconds": -1, "autoscaling_limit_min_cu": 0.5}}
    changes = warmup.apply(plan)
    assert calls == [("svc/web", 2)] and len(changes) == 2
    assert neon == [{"endpoint": {"suspend_timeout_seconds": -1, "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 4}}]


# ------------------------------------------------------------------ respaldos
class FakeBlob(SimpleNamespace):
    def upload_from_filename(self, path, **kw):
        self.data, self.kw = open(path, "rb").read(), kw


class FakeBucket:
    name = "golden-backups"

    def __init__(self, blobs=()):
        self.blobs, self.client = {}, SimpleNamespace(list_blobs=lambda bucket, prefix: [b for b in blobs if b.name.startswith(prefix)])

    def blob(self, name):
        return self.blobs.setdefault(name, FakeBlob(name=name))


def _fake_pg_dump(tmp_path, monkeypatch, body):
    script = tmp_path / "pg_dump_falso.py"
    script.write_text(f"import sys\nsys.stdout.buffer.write({body!r})\n")
    monkeypatch.setenv("PG_DUMP", f'"{sys.executable}" "{script}"')
    monkeypatch.setenv("DIRECT_DATABASE_URL", "postgresql://dueno:clave@db.example/golden_db?sslmode=require")


def test_backup_is_compressed_verified_and_named_by_kind(tmp_path, monkeypatch):
    _fake_pg_dump(tmp_path, monkeypatch, b"CREATE TABLE t (x int);\n-- PostgreSQL database dump complete\n")
    bucket = FakeBucket()
    out = ops_runner.backup_db("daily", bucket=bucket, now=datetime(2026, 10, 5, 3, 5))
    blob = bucket.blobs["db/daily/2026/10/golden_db_20261005_0305.sql.gz"]
    assert out.startswith(blob.name) and gzip.decompress(blob.data).startswith(b"CREATE TABLE") and blob.kw["checksum"] == "md5"


def test_a_cut_dump_is_never_uploaded(tmp_path, monkeypatch):
    _fake_pg_dump(tmp_path, monkeypatch, b"CREATE TABLE t (x int);\n")
    bucket = FakeBucket()
    with pytest.raises(RuntimeError, match="no terminó"):
        ops_runner.backup_db("hourly", bucket=bucket)
    assert bucket.blobs == {}


def test_backup_problems_detects_missing_old_and_small(monkeypatch):
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    hourly = [SimpleNamespace(name=f"db/hourly/x{i}.sql.gz", updated=now - timedelta(hours=10 - i), size=1000) for i in range(6)]
    hourly.append(SimpleNamespace(name="db/hourly/ultimo.sql.gz", updated=now - timedelta(hours=3), size=100))
    found = ops_runner.backup_problems(FakeBucket(hourly), now=now)
    assert set(found) == {"hourly-old", "hourly-small"}          # entorno con <26 h: el diario aún no llega (aviso, no problema)


def test_missing_first_daily_warns_in_new_env_but_fails_when_overdue():
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    fresh = [SimpleNamespace(name="db/hourly/a.sql.gz", updated=now - timedelta(minutes=30), size=1000)]
    assert ops_runner.backup_problems(FakeBucket(fresh), now=now) == {}
    assert "daily" in ops_runner.check_backups(FakeBucket(fresh), now=now)               # avisa, no lanza
    old = [SimpleNamespace(name="db/hourly/a.sql.gz", updated=now - timedelta(hours=30), size=1000),
           SimpleNamespace(name="db/hourly/b.sql.gz", updated=now - timedelta(minutes=30), size=1000)]
    assert set(ops_runner.backup_problems(FakeBucket(old), now=now)) == {"daily-none"}   # pasó el plazo: alarma real
    assert set(ops_runner.backup_problems(FakeBucket([]), now=now)) == {"hourly-none", "daily-none"}
    with pytest.raises(RuntimeError):
        ops_runner.check_backups(FakeBucket(old), now=now)


def test_failed_step_logs_reason_in_message(monkeypatch, caplog):
    monkeypatch.setattr(ops_runner, "check_backups", lambda: (_ for _ in ()).throw(RuntimeError("no hay respaldos")))
    monkeypatch.setattr(ops_runner, "backup_db", lambda kind, now=None: "ok")
    monkeypatch.setattr(ops_runner, "sweep", lambda: "ok")
    monkeypatch.setattr(ops_runner, "warmup", lambda: "ok")
    with caplog.at_level("ERROR", logger="golden.ops"):
        ops_runner.hourly(now=datetime(2026, 10, 5, 9, 5))
    assert any("check-backups falló: RuntimeError: no hay respaldos" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ orden de la tarea horaria
def test_hourly_runs_daily_and_purge_at_their_hour_and_isolates_failures(monkeypatch):
    ran = []
    monkeypatch.setattr(ops_runner, "backup_db", lambda kind, now=None: ran.append(kind) or kind)
    monkeypatch.setattr(ops_runner, "purge", lambda: ran.append("purge") or "ok")
    monkeypatch.setattr(ops_runner, "check_backups", lambda: (_ for _ in ()).throw(RuntimeError("viejo")))
    monkeypatch.setattr(ops_runner, "sweep", lambda: ran.append("sweep") or "ok")
    monkeypatch.setattr(ops_runner, "warmup", lambda: ran.append("warmup") or "ok")
    r = ops_runner.hourly(now=datetime(2026, 10, 5, 3, 5))
    assert ran == ["hourly", "daily", "sweep", "warmup"] and r["check-backups"]["ok"] is False    # el fallo no detuvo lo demás
    ran.clear()
    ops_runner.hourly(now=datetime(2026, 10, 5, 4, 5))
    assert ran == ["hourly", "purge", "sweep", "warmup"]


def test_failed_job_emails_at_most_every_six_hours(monkeypatch, db):
    sent = []
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr("app.mailer.send_mail", lambda to, subject, body, **kw: sent.append(subject) or {"sent": True})
    monkeypatch.setattr(ops_runner, "TASKS", {"sweep": lambda: (_ for _ in ()).throw(RuntimeError("base caída"))})
    assert ops_runner.main("sweep") == 1 and ops_runner.main("sweep") == 1
    assert len(sent) == 1 and "sweep" in sent[0]


def test_status_screen_reads_the_latest_backup_from_the_bucket():
    now = datetime.now(timezone.utc)
    client = SimpleNamespace(list_blobs=lambda bucket, prefix: [SimpleNamespace(name="db/hourly/a.sql.gz", updated=now - timedelta(hours=30)),
                                                                SimpleNamespace(name="db/daily/b.sql.gz", updated=now - timedelta(hours=1))])
    item = ops._check_backup_bucket("golden-backups", 26, client=client)
    assert item["level"] == "green" and item["data"]["name"] == "db/daily/b.sql.gz"
