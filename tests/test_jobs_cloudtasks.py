"""Cola con JOBS_BACKEND=cloudtasks: la tabla sigue siendo la fuente de verdad; Cloud Tasks solo despierta a /internal/jobs/run."""
from datetime import datetime, timedelta, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app import jobs
from app.models import Job

REAL_KICK = jobs.kick          # conftest reemplaza jobs.kick por drain() en cada prueba; aquí se prueba el de verdad
QUEUE = "projects/p/locations/us-east1/queues/golden-jobs"
URL = "https://web.example.run.app/internal/jobs/run"


class FakeTasks:
    def __init__(self, fail=False):
        self.tasks, self.fail = {}, fail

    def create_task(self, parent, task):
        if self.fail:
            raise RuntimeError("Cloud Tasks no responde")
        if task["name"] in self.tasks:
            raise AlreadyExists("ya existe")
        self.tasks[task["name"]] = task


@pytest.fixture()
def cloud(monkeypatch):
    monkeypatch.setenv("JOBS_BACKEND", "cloudtasks")
    monkeypatch.setenv("CLOUD_TASKS_QUEUE", QUEUE)
    monkeypatch.setenv("CLOUD_TASKS_URL", URL)
    monkeypatch.setenv("JOBS_INVOKER_SA", "jobs@p.iam.gserviceaccount.com")
    fake = FakeTasks()
    monkeypatch.setattr(jobs, "_tasks_client", fake)
    return fake


def test_many_kicks_in_the_same_second_create_one_task_for_the_next_second(cloud):
    at = datetime(2026, 9, 27, 20, 0, 5, 300000)
    for _ in range(50):
        REAL_KICK(at)
    REAL_KICK(at + timedelta(seconds=1))
    assert len(cloud.tasks) == 2
    task = cloud.tasks[f"{QUEUE}/tasks/kick-{int(datetime(2026, 9, 27, 20, 0, 6, tzinfo=timezone.utc).timestamp())}"]
    assert task["schedule_time"] == datetime(2026, 9, 27, 20, 0, 6, tzinfo=timezone.utc)          # después de todo lo confirmado en el segundo 5
    assert task["http_request"]["url"] == URL
    assert task["http_request"]["oidc_token"] == {"service_account_email": "jobs@p.iam.gserviceaccount.com", "audience": URL}


def test_a_failing_cloud_tasks_never_breaks_the_request(monkeypatch, cloud):
    monkeypatch.setattr(jobs, "_tasks_client", FakeTasks(fail=True))
    REAL_KICK()                                                             # no lanza: el trabajo ya está a salvo en la tabla


def test_a_failed_job_schedules_its_own_retry(monkeypatch, cloud, db):
    calls = []
    jobs.handler("prueba_falla")(lambda payload: (_ for _ in ()).throw(RuntimeError("smtp caído")))
    monkeypatch.setattr(jobs, "kick", lambda at=None: calls.append(at))
    jobs.enqueue(db, "prueba_falla", {})
    db.commit()
    assert jobs.run_once() == 1
    job = db.query(Job).filter_by(kind="prueba_falla").one()
    db.refresh(job)
    assert job.status == "queued" and calls == [job.run_at] and job.run_at > datetime.utcnow()


def test_internal_endpoint_needs_the_invoker_token_and_runs_the_queue(monkeypatch, client, db):
    done = []
    jobs.handler("prueba_ok")(lambda payload: done.append(payload["n"]))
    jobs.enqueue(db, "prueba_ok", {"n": 1})
    db.commit()
    assert client.post("/internal/jobs/run").status_code == 403
    monkeypatch.setenv("JOBS_INVOKER_SA", "jobs@p.iam.gserviceaccount.com")
    monkeypatch.setenv("CLOUD_TASKS_URL", URL)
    seen = {}

    def verify(token, request, audience):
        seen["audience"] = audience
        if token != "bueno":
            raise ValueError("firma inválida")
        return {"email": "jobs@p.iam.gserviceaccount.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", verify)
    assert client.post("/internal/jobs/run", headers={"Authorization": "Bearer malo"}).status_code == 403
    r = client.post("/internal/jobs/run", headers={"Authorization": "Bearer bueno"})
    assert r.status_code == 200 and r.json() == {"ran": 1} and done == [1] and seen["audience"] == URL
    monkeypatch.setenv("OPS_TOKEN", "t0k3n")
    assert client.post("/internal/jobs/run", headers={"X-Ops-Token": "t0k3n"}).json() == {"ran": 0}
