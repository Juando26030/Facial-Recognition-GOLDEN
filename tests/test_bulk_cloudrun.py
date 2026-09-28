"""Carga masiva con BULK_BACKEND=cloudrun: el servicio web solo guarda la especificación y lanza el Job; el Job (app/bulk_runner.py)
procesa con el mismo código y reporta en la misma tarea, así que la barra de progreso del navegador no cambia."""
import json

import pytest

from app import bulk_jobs, bulk_runner, uploads
from app.models import BulkJob, EventAttendee
from app.storage import get_storage
from tests.test_bulk_jobs import _admin, _fake_faces, _photo_zip, _post


@pytest.fixture()
def cloud(monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")
    launched = []
    monkeypatch.setattr(bulk_jobs, "launch_cloud_run", launched.append)
    return launched


def test_web_only_launches_and_the_job_does_the_work(client, factory, db, cloud, monkeypatch):
    _fake_faces(monkeypatch)
    ev = _admin(client, factory)
    r = _post(client, ev, zip_bytes=_photo_zip(["1001", "1002"]))
    assert r.status_code == 200 and cloud == [r.json()["job_id"]]
    job_id = cloud[0]
    job = db.get(BulkJob, job_id)
    spec = json.loads(job.spec_json)
    assert job.status == "queued" and spec["roster"] and spec["zip"] and "1001" not in job.spec_json     # tokens, nunca el contenido
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 0                               # el servicio web no procesó nada

    assert bulk_runner.main(job_id) == 0                                                                 # lo que corre el Cloud Run Job
    state = client.get(f"/api/bulk_jobs/{job_id}").json()
    assert state["status"] == "done" and state["result"]["count"] == 3 and state["done"] == state["total"]
    assert state["total"] == 2 * bulk_jobs.PHOTO_WEIGHT + 3 * bulk_jobs.ROW_WEIGHT
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 3
    assert not any(get_storage().exists(uploads.read_token(spec[k])["k"]) for k in ("roster", "zip"))       # temporales de esta carga borrados
    assert bulk_runner.main(job_id) == 1                                                                 # una tarea terminada no se repite


def test_job_errors_reach_the_browser_as_before(client, factory, cloud):
    ev = _admin(client, factory, status="finalizado")
    job_id = _post(client, ev).json()["job_id"]
    bulk_runner.main(job_id)
    state = client.get(f"/api/bulk_jobs/{job_id}").json()
    assert state["status"] == "error" and state["error"]["status"] == 400 and "finalizado" in state["error"]["detail"]


def test_photos_still_need_the_authorization_before_launching(client, factory, cloud):
    ev = _admin(client, factory)
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true"},
                    files={"roster_file": ("b.csv", b"id,nombres,apellidos\n1,A,B\n", "text/csv"), "zip_file": ("f.zip", _photo_zip(["1"]), "application/zip")})
    assert r.status_code == 400 and cloud == []


def test_if_the_job_cannot_start_the_upload_is_marked_failed(client, factory, db, monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")
    monkeypatch.setattr(bulk_jobs, "launch_cloud_run", lambda job_id: (_ for _ in ()).throw(RuntimeError("403 de la API de Cloud Run")))
    ev = _admin(client, factory)
    assert _post(client, ev).status_code == 503
    job = db.query(BulkJob).filter_by(event_id=ev.id).one()
    assert job.status == "error" and job.error_status == 503
    assert _post(client, ev).status_code == 503                                                          # una falla no deja el evento bloqueado (409)
