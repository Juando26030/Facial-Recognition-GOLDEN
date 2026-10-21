"""deploy/gcp/scheduler.sh con un `gcloud` de mentira (sin nube): `check` detecta tarea ausente, horario/zona/destino/cuenta distintos, pausa, falta de ejecuciones, falta de respaldos y respaldos
anteriores al último despliegue; `ensure` crea la tarea en pausa (o la reanuda con --resume) y, si ya existe, la corrige sin recrearla."""
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="sin bash")

FAKE = r'''#!/usr/bin/env bash
printf 'CALL %s\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "config get-value") case "$3" in project) echo goldenweb-staging;; run/region) echo us-east4;; esac ;;
  "projects describe") echo 298291650070 ;;
  "scheduler jobs")
    case "$3" in
      describe) if [ -f "$FAKE_DIR/job.json" ]; then if printf '%s ' "$@" | grep -q 'value(state)'; then python_state; else cat "$FAKE_DIR/job.json"; fi; else exit 1; fi ;;
      create) echo created > "$FAKE_DIR/created" ;;
    esac ;;
  "storage ls") [ -f "$FAKE_DIR/backups.txt" ] && cat "$FAKE_DIR/backups.txt" ;;
  "run revisions") [ -f "$FAKE_DIR/deployed.txt" ] && cat "$FAKE_DIR/deployed.txt" ;;
  "beta monitoring") echo "projects/p/notificationChannels/1" ;;
  "monitoring policies")
    if [ "$3" = list ]; then [ -f "$FAKE_DIR/policy.txt" ] && cat "$FAKE_DIR/policy.txt";
    elif [ "$3" = create ]; then for ((i = 1; i <= $#; i++)); do [ "${!i}" = "--policy-from-file" ] && { j=$((i+1)); cp "${!j}" "$FAKE_DIR/policy.json"; }; done; fi ;;
esac
exit 0
'''
def iso(hours_ago):
    """Hora «hace N horas» respecto de AHORA (no de la importación del módulo: en la suite completa pasan minutos entre pruebas y los 2,5 h se volvían 2,6)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def good_job(**over):
    job = {"name": "projects/goldenweb-staging/locations/us-east4/jobs/golden-ops-hourly-staging", "schedule": "5 * * * *", "timeZone": "America/Bogota", "state": "ENABLED",
           "lastAttemptTime": iso(0.3), "status": {},
           "httpTarget": {"uri": "https://run.googleapis.com/v2/projects/goldenweb-staging/locations/us-east4/jobs/golden-ops-staging:run",
                          "oauthToken": {"serviceAccountEmail": "golden-invoker-staging@goldenweb-staging.iam.gserviceaccount.com"}}}
    job.update(over)
    return job


def run(tmp_path, *args, job=None, backups_hours=None, deployed_hours=None, env="staging"):
    d = tmp_path / "d"
    d.mkdir(exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    g = bindir / "gcloud"
    # python_state: imprime el estado del JSON (lo que haría --format 'value(state)')
    g.write_text(FAKE.replace("python_state", f"{shlex_py()} -c \"import json;print(json.load(open('$FAKE_DIR/job.json'))['state'])\""), encoding="utf8", newline="\n")
    g.chmod(g.stat().st_mode | stat.S_IEXEC)
    for f in d.iterdir():
        f.unlink()
    if job is not None:
        (d / "job.json").write_text(json.dumps(job), encoding="utf8")
    if backups_hours is not None:
        (d / "backups.txt").write_text("".join(f"  123456  {iso(h)}  gs://b/db/hourly/2026/10/golden_db_{i}.sql.gz\n" for i, h in enumerate(backups_hours)), encoding="utf8")
    if deployed_hours is not None:
        (d / "deployed.txt").write_text(iso(deployed_hours) + "\n", encoding="utf8")
    log = tmp_path / "log.txt"
    log.write_text("", encoding="utf8")
    e = {k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP", "SystemDrive", "USERPROFILE") if k in os.environ}
    e.update({"PATH": os.pathsep.join([str(bindir), os.environ["PATH"]]), "FAKE_DIR": str(d), "FAKE_LOG": str(log), "PYTHON": sys.executable})
    r = subprocess.run([BASH, "deploy/gcp/scheduler.sh", env, *args], cwd=ROOT, env=e, capture_output=True, text=True, encoding="utf8", errors="replace")
    return r, log.read_text(encoding="utf8"), d


def shlex_py():
    return '"' + sys.executable.replace("\\", "/") + '"'


def test_check_passes_with_everything_in_order(tmp_path):
    r, _, _ = run(tmp_path, "check", job=good_job(), backups_hours=[0.5, 1.5], deployed_hours=3)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "último respaldo horario hace" in r.stdout and "posterior al último despliegue" in r.stdout


def test_check_fails_when_the_job_does_not_exist(tmp_path):
    r, _, _ = run(tmp_path, "check", job=None)
    assert r.returncode == 1 and "FALTA la tarea golden-ops-hourly-staging en us-east4" in r.stdout and "ensure --resume" in r.stdout


@pytest.mark.parametrize("over,needle", [
    ({"schedule": "0 * * * *"}, "horario"),
    ({"timeZone": "UTC"}, "zona horaria"),
    ({"httpTarget": {"uri": "https://run.googleapis.com/v2/projects/x/locations/us-east1/jobs/golden-ops-staging:run", "oauthToken": {"serviceAccountEmail": "golden-invoker-staging@goldenweb-staging.iam.gserviceaccount.com"}}}, "destino"),
    ({"state": "PAUSED"}, "la tarea no corre"),
    ({"lastAttemptTime": iso(6)}, "no corrió en la última hora y media"),
    ({"status": {"code": 13, "message": "boom"}}, "falló"),
])
def test_check_flags_every_misconfiguration(tmp_path, over, needle):
    r, _, _ = run(tmp_path, "check", job=good_job(**over), backups_hours=[0.5], deployed_hours=3)
    assert r.returncode == 1 and needle in r.stdout, r.stdout


def test_paused_is_fine_before_the_cutover_with_paused_ok(tmp_path):
    r, _, _ = run(tmp_path, "check", "--paused-ok", job=good_job(state="PAUSED"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_hourly_backups_is_a_failure_and_the_alarm_threshold_is_not_loosened(tmp_path):
    r, _, _ = run(tmp_path, "check", job=good_job(), backups_hours=None, deployed_hours=3)
    assert r.returncode == 1 and "no hay respaldos horarios" in r.stdout
    r, _, _ = run(tmp_path, "check", job=good_job(), backups_hours=[2.5], deployed_hours=5)       # 2,5 h > 2 h (el mismo umbral que check-backups)
    assert r.returncode == 1 and "tiene 2.5 h" in r.stdout


def test_a_backup_older_than_the_last_deploy_fails_but_only_after_the_first_tick_could_have_run(tmp_path):
    r, _, _ = run(tmp_path, "check", job=good_job(), backups_hours=[1.8], deployed_hours=1.6)       # el respaldo es de ANTES del despliegue, pero pasaron >1,25 h
    assert "es anterior" in r.stdout and r.returncode == 1
    r, _, _ = run(tmp_path, "check", job=good_job(), backups_hours=[0.9], deployed_hours=0.5)       # despliegue reciente: aviso, no fallo
    assert r.returncode == 0 and "AVISO" in r.stdout and "backup" in r.stdout


def test_ensure_creates_paused_then_resumes_and_is_idempotent(tmp_path):
    r, log, d = run(tmp_path, "ensure", job=None)
    assert r.returncode == 0, r.stderr
    assert "scheduler jobs create http golden-ops-hourly-staging --location us-east4 --schedule 5 * * * * --time-zone America/Bogota" in log
    assert "scheduler jobs pause golden-ops-hourly-staging" in log and "resume" not in log
    r, log, _ = run(tmp_path, "ensure", "--resume", job=good_job(state="PAUSED"))                       # ya existe: se corrige (update), no se recrea, y se reanuda
    assert "scheduler jobs update http golden-ops-hourly-staging" in log and "scheduler jobs create" not in log and "scheduler jobs resume golden-ops-hourly-staging" in log


def test_alert_creates_the_absence_policy_once(tmp_path):
    r, log, d = run(tmp_path, "alert", job=None)
    assert r.returncode == 0 and "creada" in r.stdout, r.stdout + r.stderr
    pol = json.loads((d / "policy.json").read_text(encoding="utf8"))
    cond = pol["conditions"][0]["conditionAbsent"]
    assert "golden-ops-staging" in cond["filter"] and cond["duration"] == "7200s" and "job/completed_execution_count" in cond["filter"]
    assert "--notification-channels projects/p/notificationChannels/1" in log
    # idempotente: si ya existe una con ese nombre, no crea otra
    d2 = tmp_path / "d"
    (d2 / "policy.txt").write_text("projects/p/alertPolicies/9", encoding="utf8")
    log_file = tmp_path / "log.txt"
    before = log_file.read_text(encoding="utf8").count("policies create")
    e = {k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP", "SystemDrive", "USERPROFILE") if k in os.environ}
    e.update({"PATH": os.pathsep.join([str(tmp_path / "bin"), os.environ["PATH"]]), "FAKE_DIR": str(d2), "FAKE_LOG": str(log_file), "PYTHON": sys.executable})
    r = subprocess.run([BASH, "deploy/gcp/scheduler.sh", "staging", "alert"], cwd=ROOT, env=e, capture_output=True, text=True, encoding="utf8", errors="replace")
    assert "ya existe" in r.stdout and log_file.read_text(encoding="utf8").count("policies create") == before
