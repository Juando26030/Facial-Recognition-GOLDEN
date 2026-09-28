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


INVOKER = "golden-invoker-staging@p.iam.gserviceaccount.com"


@pytest.fixture()
def oidc(monkeypatch):
    """Doble de la verificación de Google: cada «token» de prueba representa un caso."""
    from google.auth import exceptions as google_exceptions
    monkeypatch.setenv("JOBS_INVOKER_SA", INVOKER)
    monkeypatch.setenv("CLOUD_TASKS_URL", URL)
    seen = {}

    def verify(token, request, audience):
        seen["audience"] = audience
        if audience != URL:
            raise ValueError("audiencia equivocada")
        if token == "red":
            raise google_exceptions.TransportError("no se pudieron bajar los certificados")
        claims = {"bueno": {"email": INVOKER, "email_verified": True},
                  "otra-cuenta": {"email": "golden-invoker@p.iam.gserviceaccount.com", "email_verified": True},
                  "sin-verificar": {"email": INVOKER, "email_verified": False}}.get(token)
        if claims is None:
            raise ValueError("firma, emisor o vencimiento no válidos")
        return claims

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", verify)
    return seen


def _run(client, token=None, **headers):
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/internal/jobs/run", headers=headers)


def test_internal_endpoint_only_accepts_the_invoker_oidc_token(oidc, monkeypatch, client, db):
    done = []
    jobs.handler("prueba_ok")(lambda payload: done.append(payload["n"]))
    jobs.enqueue(db, "prueba_ok", {"n": 1})
    db.commit()
    assert _run(client).status_code == 401                                   # sin token
    assert _run(client, "").status_code == 401
    assert _run(client, "falsificado").status_code == 401                     # firma/emisor/vencimiento
    assert _run(client, "otra-cuenta").status_code == 403                     # token válido, pero de otra cuenta (p. ej. la de producción)
    assert _run(client, "sin-verificar").status_code == 403
    assert _run(client, "red").status_code == 503                            # no se pudo verificar: Cloud Tasks reintenta
    monkeypatch.setenv("OPS_TOKEN", "t0k3n")
    assert _run(client, **{"X-Ops-Token": "t0k3n"}).status_code == 401      # el token de operaciones YA NO sirve aquí
    assert done == []
    r = _run(client, "bueno")
    assert r.status_code == 200 and r.json() == {"ran": 1} and done == [1] and oidc["audience"] == URL


def test_internal_endpoint_is_closed_when_not_configured(monkeypatch, client):
    monkeypatch.delenv("CLOUD_TASKS_URL", raising=False)
    monkeypatch.setenv("JOBS_INVOKER_SA", INVOKER)
    assert _run(client, "cualquiera").status_code == 403                     # sin audiencia configurada no se verifica «a medias»
    monkeypatch.setenv("CLOUD_TASKS_URL", URL)
    monkeypatch.delenv("JOBS_INVOKER_SA")
    assert _run(client, "cualquiera").status_code == 403


def test_every_internal_route_requires_the_invoker_token(client):
    """Cualquier ruta /internal/* que se agregue sin la dependencia google_invoker hace fallar esta prueba."""
    from app.main import app
    from app.routers.ops import google_invoker

    def walk(routes):                                  # FastAPI anida los routers incluidos (_IncludedRouter.original_router)
        for r in routes:
            inner = getattr(r, "original_router", None)
            yield from walk(inner.routes) if inner is not None else [r]
    internal = [r for r in walk(app.routes) if getattr(r, "path", "").startswith("/internal")]
    assert internal
    for route in internal:
        assert any(d.call is google_invoker for d in route.dependant.dependencies), route.path
        for method in route.methods:
            assert client.request(method, route.path).status_code in (401, 403), (method, route.path)


def test_internal_endpoint_runs_jobs_inside_the_request_without_background_threads(oidc, monkeypatch, client, db):
    """En Cloud Run la CPU se reduce al responder: el trabajo tiene que estar HECHO cuando llega la respuesta, en el hilo de la petición."""
    import threading
    handler_threads, drain_threads = [], []
    jobs.handler("prueba_en_peticion")(lambda payload: handler_threads.append(threading.get_ident()))
    for n in range(3):
        jobs.enqueue(db, "prueba_en_peticion", {"n": n})
    db.commit()
    real_drain = jobs.drain

    def spy_drain(*a, **kw):
        drain_threads.append(threading.get_ident())
        return real_drain(*a, **kw)
    monkeypatch.setattr(jobs, "drain", spy_drain)
    monkeypatch.setattr(jobs, "Worker", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no debe arrancar el worker de fondo")))
    r = _run(client, "bueno")
    assert r.status_code == 200 and r.json() == {"ran": 3}
    assert len(handler_threads) == 3 and set(handler_threads) == set(drain_threads)   # mismo hilo que atendió la petición
    db.expire_all()
    assert {j.status for j in db.query(Job).filter_by(kind="prueba_en_peticion")} == {"done"}


def test_drain_stops_near_the_budget_and_schedules_the_rest(monkeypatch, db):
    clock = {"t": 1000.0}
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["t"])
    kicks = []
    monkeypatch.setattr(jobs, "kick", lambda at=None: kicks.append(at))

    def slow(payload):
        clock["t"] += 10                          # cada trabajo "tarda" 10 s
    jobs.handler("prueba_lenta")(slow)
    for n in range(20):
        jobs.enqueue(db, "prueba_lenta", {"n": n})
    db.commit()
    ran = jobs.drain(max_rounds=100_000, budget_seconds=45)
    assert ran == 5                               # un lote de 5 (50 s) y ya no reclama otro: se pasó de 45 s
    assert kicks == [None]                        # queda trabajo: pide otra tarea
    db.expire_all()
    pending = db.query(Job).filter_by(kind="prueba_lenta", status="queued").count()
    assert pending == 15                          # lo no reclamado sigue en cola, no "running" huérfano
