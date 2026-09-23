"""Carga masiva de la base: modo síncrono de siempre y modo en segundo plano con progreso (Sprint 5)."""
import io
import time
import zipfile

from PIL import Image

from tests.conftest import login

CSV = "id,nombres,apellidos,entidad\n1001,Ana,Uno,ACME\n1002,Beto,Dos,ACME\n1003,Carla,Tres,ACME\n"


def _photo_zip(ids):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in ids:
            img = io.BytesIO()
            Image.new("RGB", (40, 40), (200, 100, 50)).save(img, "JPEG")
            z.writestr(f"{i}.jpg", img.getvalue())
    return buf.getvalue()


def _post(client, ev, csv=CSV, zip_bytes=None, background=True, **extra):
    files = {"roster_file": ("base.csv", csv.encode(), "text/csv")}
    if zip_bytes:
        files["zip_file"] = ("fotos.zip", zip_bytes, "application/zip")
    data = {"event_id": str(ev.id), **extra}
    if background:
        data["background"] = "true"
    return client.post("/api/bulk_register", data=data, files=files)


def _wait(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/bulk_jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("la carga no terminó a tiempo")


def _admin(client, factory, status="creado"):
    factory.staff("admin", "root")
    ev = factory.event(status)
    login(client, "root")
    return ev


def _fake_faces(monkeypatch):
    from app.biometrics import BiometricEngine
    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(lambda *a, **k: [0.1] * 128))


def test_synchronous_mode_is_unchanged(client, factory):
    ev = _admin(client, factory)
    r = _post(client, ev, background=False)
    assert r.status_code == 200 and r.json()["count"] == 3


def test_background_mode_returns_a_job_and_finishes_with_the_same_result(client, factory, db):
    from app.models import EventAttendee

    ev = _admin(client, factory)
    r = _post(client, ev)
    assert r.status_code == 200 and r.json()["background"] is True
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["count"] == 3 and "Carga completa" in job["result"]["message"]
    assert job["done"] == job["total"] > 0
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 3


def test_progress_is_weighted_so_photos_dominate(client, factory, monkeypatch):
    _fake_faces(monkeypatch)
    ev = _admin(client, factory)
    job = _wait(client, _post(client, ev, zip_bytes=_photo_zip(["1001", "1002", "1003"])).json()["job_id"])
    assert job["status"] == "done"
    from app import bulk_jobs
    assert job["total"] == 3 * bulk_jobs.PHOTO_WEIGHT + 3 * bulk_jobs.ROW_WEIGHT
    assert job["result"]["count"] == 3


def test_errors_reach_the_browser_as_before(client, factory):
    ev = _admin(client, factory, status="finalizado")
    job = _wait(client, _post(client, ev).json()["job_id"])
    assert job["status"] == "error" and job["error"]["status"] == 400 and "finalizado" in job["error"]["detail"]


def test_needs_labels_comes_back_as_the_job_result(client, factory):
    ev = _admin(client, factory)
    csv = "id,nombres,apellidos,opcional_1\n1001,Ana,Uno,M\n"
    job = _wait(client, _post(client, ev, csv=csv).json()["job_id"])
    assert job["status"] == "done" and job["result"]["result"] == "NEEDS_LABELS" and job["result"]["fields"] == ["opcional_1"]


def test_bad_format_is_reported(client, factory):
    ev = _admin(client, factory)
    job = _wait(client, _post(client, ev, csv="a,b\n1,2\n").json()["job_id"])
    assert job["status"] == "error" and job["error"]["status"] == 400


def test_only_one_active_job_per_event(client, factory, db):
    from app.models import BulkJob

    ev = _admin(client, factory)
    db.add(BulkJob(id="x" * 32, event_id=ev.id, status="running", stage="Procesando"))
    db.commit()
    assert _post(client, ev).status_code == 409


def test_job_without_heartbeat_is_marked_interrupted(client, factory, db):
    from datetime import datetime, timedelta
    from app.models import BulkJob

    ev = _admin(client, factory)
    db.add(BulkJob(id="y" * 32, event_id=ev.id, status="running", stage="Procesando", updated_at=datetime.utcnow() - timedelta(minutes=30)))
    db.commit()
    job = client.get(f"/api/bulk_jobs/{'y' * 32}").json()
    assert job["status"] == "error" and "interrumpió" in job["error"]["detail"]
    assert _post(client, ev).status_code == 200      # una tarea muerta no bloquea nuevas cargas


def test_job_status_needs_access_to_that_event(client, factory, db):
    from app.models import BulkJob

    ev = _admin(client, factory)
    other = factory.event("creado", tenant_id="otro")
    db.add(BulkJob(id="z" * 32, event_id=other.id, status="done", stage="Listo", result_json="{}"))
    db.commit()
    client.post("/logout")
    dig = factory.staff("digitador", "9990001")
    login(client, "9990001")
    assert client.get(f"/api/bulk_jobs/{'z' * 32}").status_code == 403       # un digitador no consulta cargas
    assert client.get("/api/bulk_jobs/no-existe").status_code in (403, 404)
