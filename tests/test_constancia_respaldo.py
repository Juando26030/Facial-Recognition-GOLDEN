"""Constancia de la autorización por correo (aprobado por Juan David el 25-oct-2026, con condición): se intenta enviar AL INSTANTE, pero un fallo del correo
NUNCA impide que la aceptación quede registrada, y el barrido horario (ops_runner.sweep) la reintenta hasta enviarla."""
import json
import uuid
from datetime import timedelta

from app import consent_receipt, jobs, ops_runner
from app.models import AuditConsentLog, Job, User
from app.timeutil import utcnow
from tests.test_consent_flow import _op, company_env  # noqa: F401 — misma fixture de datos de empresa


def test_mail_fails_acceptance_is_kept_and_the_hourly_sweep_retries_until_it_is_sent(client, factory, db, company_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(jobs, "kick", lambda at=None, pool="general": None)                  # sin hilos ni Cloud Tasks: el trabajo queda en la cola para verlo
    ev = _op(client, factory)
    ev.controller_mode = "golden"
    factory.person(ev, "1001", "Ana", "Mora")
    db.query(User).filter_by(id="1001", tenant_id=ev.tenant_id).update({"email": "ana@ejemplo.test"})
    db.commit()

    attempts = []

    def broken(*a, **k):                                                                       # el servidor de correo está caído
        attempts.append(1)
        raise ConnectionError("SMTP caído")
    monkeypatch.setattr(consent_receipt, "send_mail", broken)

    t = client.get(f"/api/events/{ev.id}/consent-text").json()
    body = {"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "device": "tablet-1"}]}
    r = client.post(f"/api/events/{ev.id}/consents", json=body)
    assert r.status_code == 200 and r.json()["inserted"] == 1                                  # 1) la aceptación se registra (el correo no se intenta en la petición)
    db.expire_all()
    entry = db.query(AuditConsentLog).filter_by(event_id=ev.id, user_id="1001", reason="consent").one()
    assert entry.accepted_biometric

    jobs.drain(exclude=jobs.FACE_KINDS)                                                        # 2) el envío inmediato falla...
    db.expire_all()
    job = db.query(Job).filter_by(kind="consent_receipt").one()
    assert attempts == [1] and job.status == "queued" and job.attempts == 1 and "SMTP caído" in (job.last_error or "")
    assert job.run_at > utcnow()                                                               # ...y queda para reintentar (espera creciente), no se pierde
    assert db.query(AuditConsentLog).filter_by(event_id=ev.id, user_id="1001", reason="consent").count() == 1   # la aceptación sigue ahí, intacta

    sent = []
    monkeypatch.setattr(consent_receipt, "send_mail", lambda to, subject, text, **k: sent.append(to) or {"sent": True, "detail": "ok"})
    job.run_at = utcnow() - timedelta(seconds=1)                                               # 3) pasa el tiempo de espera y corre el barrido horario
    db.commit()
    ops_runner.sweep()
    db.expire_all()
    job = db.query(Job).filter_by(kind="consent_receipt").one()
    assert sent == ["ana@ejemplo.test"] and job.status == "done" and job.attempts == 2       # se envía una sola vez
    assert json.loads(job.payload_json)["entry_id"] == entry.id
