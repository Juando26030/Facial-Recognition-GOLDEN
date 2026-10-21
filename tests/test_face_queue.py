"""Cola APARTE de los cálculos faciales: otra cola de Cloud Tasks, otro servicio (biometría), mismo token OIDC y mismo invoker; la general no los ejecuta y la facial solo ejecuta los suyos."""
from datetime import datetime, timezone

import pytest
from google.auth import exceptions as google_exceptions

from app import jobs
from app.models import Job

REAL_KICK = jobs.kick
FQ = "projects/p/locations/us-east4/queues/golden-faces"
FURL = "https://biometria.example.run.app/internal/faces/run"
GQ = "projects/p/locations/us-east4/queues/golden-jobs"
GURL = "https://web.example.run.app/internal/jobs/run"
INVOKER = "jobs@p.iam.gserviceaccount.com"


class FakeTasks:
    def __init__(self):
        self.created = []

    def create_task(self, parent, task):
        self.created.append((parent, task))


@pytest.fixture()
def cloud(monkeypatch):
    monkeypatch.setenv("JOBS_BACKEND", "cloudtasks")
    monkeypatch.setenv("CLOUD_TASKS_QUEUE", GQ)
    monkeypatch.setenv("CLOUD_TASKS_URL", GURL)
    monkeypatch.setenv("CLOUD_TASKS_FACES_QUEUE", FQ)
    monkeypatch.setenv("CLOUD_TASKS_FACES_URL", FURL)
    monkeypatch.setenv("JOBS_INVOKER_SA", INVOKER)
    fake = FakeTasks()
    monkeypatch.setattr(jobs, "_tasks_client", fake)
    return fake


def test_face_kicks_go_to_the_faces_queue_with_its_own_audience_and_the_rest_to_the_general_one(cloud):
    at = datetime(2026, 10, 6, 20, 0, 5, tzinfo=timezone.utc)
    REAL_KICK(at, "faces")
    REAL_KICK(at)
    (fq, ft), (gq, gt) = cloud.created
    assert fq == FQ and ft["http_request"]["url"] == FURL and ft["http_request"]["oidc_token"] == {"service_account_email": INVOKER, "audience": FURL}
    assert gq == GQ and gt["http_request"]["url"] == GURL


def test_without_the_faces_queue_everything_keeps_working_through_the_general_one(cloud, monkeypatch):
    monkeypatch.delenv("CLOUD_TASKS_FACES_QUEUE")
    REAL_KICK(datetime(2026, 10, 6, 20, 0, 5, tzinfo=timezone.utc), "faces")
    assert cloud.created[0][0] == GQ and jobs.general_excludes() is None            # sin cola facial, la general ejecuta también los cálculos faciales


def test_the_general_queue_skips_face_jobs_and_the_face_queue_runs_only_them(cloud, db, monkeypatch):
    ran = []
    monkeypatch.setitem(jobs._handlers, "face_enroll", lambda payload: ran.append(("faces", payload["n"])))      # sin reemplazar el manejador real para las demás pruebas
    jobs.handler("prueba_general")(lambda payload: ran.append(("general", payload["n"])))
    jobs.enqueue(db, "face_enroll", {"n": 1})
    jobs.enqueue(db, "prueba_general", {"n": 2})
    db.commit()
    assert jobs.general_excludes() == jobs.FACE_KINDS
    jobs.drain(exclude=jobs.general_excludes())
    assert ran == [("general", 2)]
    jobs.drain(kinds=jobs.FACE_KINDS, pool="faces")
    assert ran == [("general", 2), ("faces", 1)]


def test_a_failed_face_job_retries_through_the_faces_queue(cloud, db, monkeypatch):
    monkeypatch.setitem(jobs._handlers, "face_enroll", lambda payload: (_ for _ in ()).throw(RuntimeError("dlib ocupado")))
    jobs.enqueue(db, "face_enroll", {"n": 1})
    db.commit()
    kicks = []
    monkeypatch.setattr(jobs, "kick", lambda at=None, pool="general": kicks.append((at, pool)))
    jobs.drain(kinds=jobs.FACE_KINDS, pool="faces", max_rounds=1)
    assert db.query(Job).filter_by(kind="face_enroll").one().status == "queued"
    assert any(at is not None and pool == "faces" for at, pool in kicks)            # el reintento (espera creciente) se programa en la cola facial


def test_faces_endpoint_needs_the_invoker_token_for_its_own_audience(client, monkeypatch):
    seen = {}

    def verify(token, request, audience):
        seen["audience"] = audience
        if audience != FURL:
            raise ValueError("audiencia equivocada")
        if token == "red":
            raise google_exceptions.TransportError("sin certificados")
        return {"email": INVOKER, "email_verified": True} if token == "bueno" else (_ for _ in ()).throw(ValueError("no válido"))
    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    monkeypatch.setenv("JOBS_INVOKER_SA", INVOKER)
    monkeypatch.setenv("CLOUD_TASKS_URL", GURL)
    monkeypatch.setenv("CLOUD_TASKS_FACES_URL", FURL)
    assert client.post("/internal/faces/run").status_code == 401
    assert client.post("/internal/faces/run", headers={"Authorization": "Bearer falso"}).status_code == 401
    assert client.post("/internal/faces/run", headers={"Authorization": "Bearer red"}).status_code == 503
    ok = client.post("/internal/faces/run", headers={"Authorization": "Bearer bueno"})
    assert ok.status_code == 200 and seen["audience"] == FURL
    monkeypatch.delenv("CLOUD_TASKS_FACES_URL")
    assert client.post("/internal/faces/run", headers={"Authorization": "Bearer bueno"}).status_code == 403       # sin configurar no se abre


def test_the_faces_endpoint_is_served_by_the_biometric_service_only():
    from app import appmode
    assert appmode.route_allowed("/internal/faces/run", mode="biometria") and not appmode.route_allowed("/internal/faces/run", mode="web")


def test_the_hourly_sweep_never_runs_face_jobs_itself_but_wakes_their_queue(db, monkeypatch):
    from app import ops_runner
    ran, kicks = [], []
    monkeypatch.setitem(jobs._handlers, "face_enroll", lambda payload: ran.append("faces"))
    monkeypatch.setitem(jobs._handlers, "prueba_barrido", lambda payload: ran.append("general"))
    monkeypatch.setattr(jobs, "kick", lambda at=None, pool="general": kicks.append(pool))
    jobs.enqueue(db, "face_enroll", {"n": 1})
    jobs.enqueue(db, "prueba_barrido", {"n": 2})
    db.commit()
    detail = ops_runner.sweep()
    assert ran == ["general"] and kicks == ["faces"] and "1 cálculo(s) facial(es)" in detail
    assert db.query(Job).filter_by(kind="face_enroll").one().status == "queued"            # sigue en cola, sin gastar intentos


def test_retry_face_jobs_requeues_the_exhausted_ones_and_wakes_the_faces_queue(db, monkeypatch):
    from app import ops_runner
    kicks = []
    monkeypatch.setattr(jobs, "kick", lambda at=None, pool="general": kicks.append(pool))
    jobs.enqueue(db, "face_enroll", {"n": 1})
    jobs.enqueue(db, "face_enroll", {"n": 2})
    db.commit()
    first = db.query(Job).order_by(Job.id).first()
    first.status, first.attempts, first.last_error = "failed", 3, "dlib ocupado"
    db.commit()
    assert "1 cálculo(s) facial(es) devueltos" in ops_runner.retry_face_jobs() and kicks == ["faces"]
    db.expire_all()
    j = db.query(Job).order_by(Job.id).first()
    assert (j.status, j.attempts, j.last_error) == ("queued", 0, None)
