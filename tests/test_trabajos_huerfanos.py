"""Hallazgo 4 (producción, 21-oct-2026): el Job horario reclamaba trabajos cuyo manejador no había cargado (la constancia de autorización), gastaba sus
intentos y los dejaba «failed» sin avisar a nadie. Aquí: el Job carga todos los manejadores no faciales, nunca gasta intentos en un tipo sin manejador,
avisa de los fallos NUEVOS (correo + salida 1) y «/sistema» cuenta las constancias y el envío de enlaces como correos."""
import os
import pathlib
import re
import subprocess
import sys
from datetime import timedelta

import pytest

from app import jobs, ops, ops_runner
from app.models import Job
from app.timeutil import utcnow


def _declared_kinds() -> set:
    kinds = set()
    for f in pathlib.Path("app").rglob("*.py"):
        kinds |= set(re.findall(r'@jobs\.handler\("([^"]+)"\)', f.read_text(encoding="utf-8")))
    return kinds


def test_the_hourly_job_loads_every_non_face_handler_and_not_the_face_model():
    out = subprocess.run([sys.executable, "-c", "from app import ops_runner, jobs; ops_runner._load_handlers(); print(','.join(sorted(jobs._handlers)))"],
                         capture_output=True, text=True, env=dict(os.environ), timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    loaded = set(out.stdout.strip().splitlines()[-1].split(","))
    expected = _declared_kinds() - set(jobs.FACE_KINDS)
    assert expected and expected <= loaded, f"faltan manejadores en el Job horario: {sorted(expected - loaded)}"
    assert {"consent_receipt", "accept_mail", "form_feed", "payments_reconcile"} <= loaded
    assert not (set(jobs.FACE_KINDS) & loaded)                                                   # enroll (modelo facial) NO se carga en el Job


def test_a_job_whose_handler_is_not_loaded_here_stays_queued_with_its_attempts(db, monkeypatch):
    monkeypatch.delitem(jobs._handlers, "consent_receipt")                                      # como en el Job horario de producción antes del arreglo
    jobs.enqueue(db, "consent_receipt", {"entry_id": "x", "tenant_id": "t", "event_id": 1, "user_id": "1", "channel": "door"}, dedupe_key="receipt:x", max_attempts=4)
    db.commit()
    assert jobs.drain(exclude=jobs.FACE_KINDS) == 0
    db.expire_all()
    job = db.query(Job).one()
    assert job.status == "queued" and job.attempts == 0 and job.last_error is None and job.locked_until is None
    assert jobs.unhandled_due(db) == [(job.id, "consent_receipt")]


def _boom(monkeypatch):
    def fail(payload):
        raise RuntimeError("falló a propósito")
    monkeypatch.setitem(jobs._handlers, "boom", fail)


def test_the_sweep_fails_with_kind_and_id_when_a_job_fails_in_that_run_and_only_once(db, monkeypatch):
    _boom(monkeypatch)
    jobs.enqueue(db, "boom", {"cedula": "1001", "nombre": "Ana"}, max_attempts=1)
    db.commit()
    job_id = db.query(Job.id).scalar()
    with pytest.raises(RuntimeError) as exc:
        ops_runner.sweep()
    msg = str(exc.value)
    assert f"boom#{job_id}" in msg and "1 trabajo(s) fallaron en este barrido" in msg
    assert "1001" not in msg.replace(f"#{job_id}", "") and "Ana" not in msg                    # ningún dato de la persona
    assert ops_runner.sweep().startswith("0 trabajo(s)")                                         # el fallo ya avisado no se repite en el barrido siguiente


def test_the_sweep_warns_once_about_a_new_job_without_handler_and_keeps_it_queued(db):
    jobs.enqueue(db, "tipo-desconocido", {})
    db.commit()
    job = db.query(Job).one()
    with pytest.raises(RuntimeError, match=rf"sin manejador en el Job .*tipo-desconocido#{job.id}"):
        ops_runner.sweep()
    db.expire_all()
    job = db.query(Job).one()
    assert job.status == "queued" and job.attempts == 0
    job.created_at = utcnow() - ops_runner.UNHANDLED_ALERT_WINDOW - timedelta(minutes=1)        # ya se avisó en un barrido anterior
    db.commit()
    ops_runner.sweep()                                                                           # no vuelve a fallar cada hora


def test_main_sends_the_alert_and_exits_1_when_the_sweep_fails(db, monkeypatch):
    _boom(monkeypatch)
    sent = []
    monkeypatch.setattr(ops_runner, "_alert", lambda key, subject, body: sent.append((key, subject, body)))
    jobs.enqueue(db, "boom", {}, max_attempts=1)
    db.commit()
    assert ops_runner.main("sweep") == 1
    assert sent and sent[0][0] == "ops-sweep" and "boom#" in sent[0][2]


def test_system_status_counts_consent_receipts_and_link_mailings_as_emails(db):
    jobs.enqueue(db, "consent_receipt", {"x": 1}, dedupe_key="receipt:a")
    jobs.enqueue(db, "accept_mail", {"x": 2})
    db.commit()
    failed = db.query(Job).filter(Job.kind == "accept_mail").one()
    failed.status = "failed"
    db.commit()
    card = ops.check_emails(db)
    assert card["data"]["pending"] == 1 and card["data"]["failed"] == 1 and card["level"] == "yellow" and "1 pendientes · 1 fallidos" in card["value"]
