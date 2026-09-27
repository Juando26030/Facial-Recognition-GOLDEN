"""Piezas de plataforma de la Fase 0 pensadas para Cloud Run: cola de trabajos, almacenamiento de archivos, modos de arranque, reportes con tope,
conciliación de pagos e idempotencia de migraciones/pool."""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest

from app import appmode, heavy, jobs, storage
from app.models import FormPayment, Job
from tests.conftest import login


# ------------------------------- cola de trabajos -------------------------------
@pytest.fixture()
def handlers(monkeypatch):
    calls = []
    monkeypatch.setitem(jobs._handlers, "eco", lambda payload: calls.append(payload))
    return calls


def test_enqueue_belongs_to_the_callers_transaction(db, handlers):
    jobs.enqueue(db, "eco", {"n": 1})
    db.rollback()                                                          # la operación que lo pidió se deshizo: el trabajo también
    assert jobs.run_once() == 0 and db.query(Job).count() == 0
    jobs.enqueue(db, "eco", {"n": 2})
    db.commit()
    assert jobs.run_once() == 1 and handlers == [{"n": 2}]
    db.expire_all()
    assert db.query(Job).one().status == "done"


def test_dedupe_key_ignores_a_second_identical_job(db, handlers):
    jobs.enqueue(db, "eco", {"n": 1}, dedupe_key="x")
    db.commit()
    jobs.enqueue(db, "eco", {"n": 1}, dedupe_key="x")
    db.commit()
    assert db.query(Job).count() == 1


def test_failed_jobs_back_off_then_end_as_failed_and_can_be_seen(db, monkeypatch):
    def boom(payload):
        raise RuntimeError("no se pudo")

    monkeypatch.setitem(jobs._handlers, "roto", boom)
    jobs.enqueue(db, "roto", {}, max_attempts=2)
    db.commit()
    assert jobs.run_once() == 1
    db.expire_all()
    job = db.query(Job).one()
    assert job.status == "queued" and job.attempts == 1 and job.run_at > datetime.utcnow()             # espera antes de reintentar
    assert jobs.run_once() == 0                                                                        # todavía no le toca
    job.run_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert jobs.run_once() == 1
    db.expire_all()
    job = db.query(Job).one()
    assert job.status == "failed" and "no se pudo" in job.last_error and job.finished_at
    stats = jobs.stats(db)
    assert stats["failed"] == 1 and stats["pending"] == 0


def test_unknown_kind_is_recorded_as_an_error_not_a_crash(db):
    jobs.enqueue(db, "no-existe", {})
    db.commit()
    assert jobs.run_once() == 1
    db.expire_all()
    assert "no hay manejador" in db.query(Job).one().last_error


def test_a_job_whose_process_died_is_reclaimed_after_the_lease(db, handlers):
    jobs.enqueue(db, "eco", {"n": 3})
    db.commit()
    job = db.query(Job).one()
    job.status, job.locked_until, job.attempts = "running", datetime.utcnow() - timedelta(seconds=5), 1     # quedó «en curso» y el proceso murió
    db.commit()
    assert jobs.run_once() == 1 and handlers == [{"n": 3}]


def test_worker_thread_picks_up_jobs_and_stops_gracefully(db, handlers, monkeypatch):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.05)
    worker = jobs.Worker()
    worker.start()
    jobs.enqueue(db, "eco", {"n": 4})
    db.commit()
    jobs._wake.set()
    for _ in range(100):
        if handlers:
            break
        time.sleep(0.05)
    worker.stop()
    assert handlers == [{"n": 4}] and not worker.is_alive()


# ------------------------------- almacenamiento -------------------------------
def test_local_storage_roundtrip_and_old_data_prefix_is_accepted(tmp_path):
    store = storage.LocalStorage(str(tmp_path))
    assert store.put("acme/known_people/1.jpg", b"abc") == "acme/known_people/1.jpg"
    assert store.get("data/acme/known_people/1.jpg") == b"abc"                      # valores viejos guardados en la base como «data/…»
    assert store.exists("acme/known_people/1.jpg") and not store.exists("acme/otra.jpg")
    store.put("acme/known_people/2.jpg", b"x")
    assert store.list("acme") == ["acme/known_people/1.jpg", "acme/known_people/2.jpg"]
    store.move("acme/known_people/1.jpg", "acme/known_people/9.jpg")
    assert not store.exists("acme/known_people/1.jpg") and store.get("acme/known_people/9.jpg") == b"abc"
    store.delete("acme/known_people/9.jpg")
    store.delete("acme/known_people/9.jpg")                                        # borrar dos veces no falla
    store.delete_prefix("acme")
    assert store.list("") == []
    store.ping()


@pytest.mark.parametrize("bad", ["../secreto", "acme/../../x", "C:/Windows/x"])
def test_storage_rejects_paths_that_escape_the_root(tmp_path, bad):
    store = storage.LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        store.put(bad, b"x")
    assert store.exists(bad) is False


def test_storage_response_serves_the_file_or_404(tmp_path):
    from fastapi import HTTPException
    store = storage.LocalStorage(str(tmp_path))
    store.put("a/b.png", b"png")
    assert store.response("a/b.png").path.endswith("b.png")
    with pytest.raises(HTTPException) as exc:
        store.response("a/no.png")
    assert exc.value.status_code == 404


def test_cloud_storage_backend_needs_a_bucket_and_unknown_backends_fail(monkeypatch):
    storage.reset_storage()
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="GCS_BUCKET"):
        storage.get_storage()
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    with pytest.raises(RuntimeError, match="no existe"):
        storage.get_storage()
    monkeypatch.delenv("STORAGE_BACKEND")
    storage.reset_storage()


@pytest.mark.skipif(not os.getenv("STORAGE_EMULATOR_HOST"), reason="necesita el emulador de Cloud Storage (docker run fsouza/fake-gcs-server; ver docs/15)")
def test_gcs_storage_behaves_like_local_storage():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage as gcs

    client = gcs.Client(project="test", credentials=AnonymousCredentials())
    name = f"golden-test-{os.urandom(4).hex()}"
    client.create_bucket(name)
    store = storage.GcsStorage(name, "app", client=client)
    assert store.put("acme/known_people/1.jpg", b"abc") == "acme/known_people/1.jpg"
    assert client.bucket(name).blob("app/acme/known_people/1.jpg").exists()          # el prefijo es una carpeta dentro del bucket
    assert store.get("data/acme/known_people/1.jpg") == b"abc"
    assert store.exists("acme/known_people/1.jpg") and not store.exists("acme/otra.jpg")
    with pytest.raises(FileNotFoundError):
        store.get("acme/otra.jpg")
    store.put("acme/known_people/2.jpg", b"x")
    store.put("acme2/f.pdf", b"pdf")
    assert store.list("acme") == ["acme/known_people/1.jpg", "acme/known_people/2.jpg"]
    store.move("acme/known_people/1.jpg", "acme/known_people/9.jpg")
    assert not store.exists("acme/known_people/1.jpg") and store.get("acme/known_people/9.jpg") == b"abc"
    store.delete("acme/known_people/9.jpg")
    store.delete("acme/known_people/9.jpg")
    store.delete_prefix("acme")
    assert store.list("") == ["acme2/f.pdf"]                                            # acme2 no se toca al borrar acme
    with pytest.raises(ValueError):
        store.put("../secreto", b"x")
    store.ping()

    app = FastAPI()
    app.get("/f/{key:path}")(lambda key: store.response(key, filename="informe final.pdf", headers={"cache-control": "private, no-store"}))
    with TestClient(app) as c:
        r = c.get("/f/acme2/f.pdf")
        assert r.status_code == 200 and r.content == b"pdf" and r.headers["cache-control"] == "private, no-store"
        assert r.headers["content-disposition"] == "attachment; filename*=utf-8''informe%20final.pdf"
        assert c.get("/f/acme2/no.pdf").status_code == 404
    with pytest.raises(HTTPException):
        store.response("acme2/no.pdf")


# ------------------------------- modos de arranque -------------------------------
@pytest.mark.parametrize("mode", ["publico", "web", "biometria"])
def test_split_entrypoints_never_import_dlib(mode):
    code = (f"import sys, os; os.environ['DATABASE_URL']='postgresql://x:y@localhost/z'; import app.entrypoints.{mode} as e; "
            "assert 'dlib' not in sys.modules and 'face_recognition' not in sys.modules, 'se importó dlib'; print('ok')")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-500:]


def test_route_allowed_splits_the_three_services():
    assert appmode.route_allowed("/f/{event_id}/{slug}/submit", mode="publico") and not appmode.route_allowed("/login", mode="publico")
    assert appmode.route_allowed("/api/recognize", mode="biometria") and not appmode.route_allowed("/api/users", mode="biometria")
    assert appmode.route_allowed("/api/users", mode="web") and not appmode.route_allowed("/api/recognize", mode="web") and not appmode.route_allowed("/b/{token}", mode="web")
    for mode in ("publico", "web", "biometria"):
        assert appmode.route_allowed("/healthz", mode=mode) and appmode.route_allowed("/readyz", mode=mode)
    assert appmode.route_allowed("/api/recognize", mode="all") and appmode.route_allowed("/login", mode="all")


def test_apps_built_per_mode_expose_only_their_routes():
    code = (
        "import os,sys; os.environ['APP_MODE']='{mode}'\n"
        "from fastapi.testclient import TestClient\nimport app.main as m\nc=TestClient(m.app)\n"
        "print(c.get('/healthz').status_code, c.post('/login',data={{}}).status_code, c.post('/api/recognize').status_code, c.get('/f/1/x/state').status_code)\n")
    def run(mode):
        out = subprocess.run([sys.executable, "-W", "ignore", "-c", code.format(mode=mode)], capture_output=True, text=True, timeout=120)
        return out.stdout.strip().split()[-4:], out.stderr[-1800:]
    publico, err = run("publico")
    assert publico[0] == "200" and publico[1] == "404" and publico[2] == "404", err            # sin login ni biometría; /f/… sí existe (404 = formulario inexistente en una base vacía)
    biometria, err = run("biometria")
    assert biometria[0] == "200" and biometria[1] == "404" and biometria[3] == "404" and biometria[2] in ("401", "422"), err


# ------------------------------- reportes con tope -------------------------------
def test_heavy_slot_limits_concurrency_and_answers_503_when_the_wait_is_over(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(heavy, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(heavy, "QUEUE_TIMEOUT", 0.05)
    with heavy.heavy_slot():
        with pytest.raises(HTTPException) as exc:
            with heavy.heavy_slot():
                pass
    assert exc.value.status_code == 503 and exc.value.headers["Retry-After"] == "60"
    with heavy.heavy_slot():                                                       # y se libera al terminar
        pass


def test_excel_report_is_built_in_memory_and_leaves_no_temp_files(client, factory):
    import os
    import tempfile
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    factory.person(ev)
    login(client, "coord1")
    before = set(os.listdir(tempfile.gettempdir()))
    r = client.get(f"/api/report?event_id={ev.id}")
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]
    after = set(os.listdir(tempfile.gettempdir()))
    assert not [n for n in after - before if n.endswith(".xlsx")]


# ------------------------------- conciliación de pagos -------------------------------
def test_reconcile_confirms_a_payment_whose_webhook_was_lost(client, factory, db, monkeypatch):
    from app import reconcile, wompi
    from app.models import FormSubmission, WebForm
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    form = WebForm(event_id=ev.id, name="F", slug="f", manual_status="activo", design_json="{}", test_key="k")
    db.add(form)
    db.commit()
    sub = FormSubmission(form_id=form.id, event_id=ev.id, data_json="{}", status="awaiting_payment", person_id="1")
    db.add(sub)
    db.commit()
    pay = FormPayment(form_id=form.id, event_id=ev.id, submission_id=sub.id, amount_cents=500000, reference="GW-1-1-1-abc", status="pending", is_test=True,
                      created_at=datetime.utcnow() - timedelta(minutes=10))
    fresh = FormPayment(form_id=form.id, event_id=ev.id, amount_cents=500000, reference="GW-1-1-2-def", status="pending", is_test=True)   # recién creado: aún no se concilia
    db.add_all([pay, fresh])
    db.commit()
    monkeypatch.setattr(wompi, "config", lambda is_test: {"api": "x", "private_key": "k", "test": True})
    seen = []

    def fake_fetch(cfg, ref):
        seen.append(ref)
        return {"status": "APPROVED", "id": "tx-1", "amount_in_cents": 500000, "currency": "COP", "payment_method_type": "CARD"}

    monkeypatch.setattr(wompi, "fetch_by_reference", fake_fetch)
    summary = reconcile.reconcile_pending(db)
    assert seen == ["GW-1-1-1-abc"] and summary["checked"] == 1 and summary["updated"] == 1          # solo el pendiente viejo
    db.expire_all()
    assert db.query(FormPayment).filter_by(reference="GW-1-1-1-abc").one().status == "approved"
    assert db.query(FormSubmission).one().status == "confirmed"                                        # y la inscripción quedó confirmada


def test_reconcile_ignores_amount_mismatches_and_unknown_references(db, factory, monkeypatch):
    from app import reconcile, wompi
    from app.models import WebForm
    ev = factory.event("en_proceso")
    form = WebForm(event_id=ev.id, name="F", slug="f", manual_status="activo", design_json="{}", test_key="k")
    db.add(form)
    db.commit()
    db.add(FormPayment(form_id=form.id, event_id=ev.id, amount_cents=500000, reference="GW-A", status="pending", is_test=True, created_at=datetime.utcnow() - timedelta(minutes=10)))
    db.add(FormPayment(form_id=form.id, event_id=ev.id, amount_cents=500000, reference="GW-B", status="pending", is_test=True, created_at=datetime.utcnow() - timedelta(minutes=10)))
    db.commit()
    monkeypatch.setattr(wompi, "config", lambda is_test: {"api": "x", "private_key": "k", "test": True})
    monkeypatch.setattr(wompi, "fetch_by_reference", lambda cfg, ref: {"status": "APPROVED", "id": "t", "amount_in_cents": 1, "currency": "COP"} if ref == "GW-A" else None)
    s = reconcile.reconcile_pending(db)
    assert s["mismatch"] == 1 and s["not_found"] == 1 and s["updated"] == 0
    assert {p.status for p in db.query(FormPayment)} == {"pending"}
