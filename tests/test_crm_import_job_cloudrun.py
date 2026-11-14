"""La importación de SuiteCRM en Cloud Run se entrega al Cloud Run Job (una petición de la cola se corta a los ~60 s)."""
from app import bulk_jobs
from app.crm import import_job
from app.crm.importer import runner
from app.database import SessionLocal
from app.models import CrmImportRun


def _run(db, status="queued"):
    row = CrmImportRun(kind="suitecrm", mode="sample", status=status, options_json="{}")
    db.add(row)
    db.commit()
    return row.id


def test_en_cloud_run_lanza_el_job_y_no_corre_en_la_peticion(monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")
    launched, ran = [], []
    monkeypatch.setattr(import_job, "launch_cloud_run", launched.append)
    monkeypatch.setattr(runner, "run", lambda db, rid: ran.append(rid))
    db = SessionLocal()
    rid = _run(db)
    db.close()
    import_job._crm_import_job({"run_id": rid})
    assert launched == [rid] and ran == []


def test_no_lanza_dos_veces_si_ya_no_esta_en_cola(monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")
    launched = []
    monkeypatch.setattr(import_job, "launch_cloud_run", launched.append)
    db = SessionLocal()
    rid = _run(db, status="running")
    db.close()
    import_job._crm_import_job({"run_id": rid})
    assert launched == []


def test_si_no_se_puede_lanzar_la_corrida_queda_fallida(monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")

    def boom(_rid):
        raise RuntimeError("sin permiso")
    monkeypatch.setattr(import_job, "launch_cloud_run", boom)
    db = SessionLocal()
    rid = _run(db)
    db.close()
    import_job._crm_import_job({"run_id": rid})
    db = SessionLocal()
    row = db.get(CrmImportRun, rid)
    assert row.status == "failed" and "No se pudo iniciar" in row.error
    db.close()


def test_en_modo_hilo_corre_en_el_mismo_proceso(monkeypatch):
    monkeypatch.setenv("BULK_BACKEND", "thread")
    ran = []
    monkeypatch.setattr(runner, "run", lambda db, rid: ran.append(rid))
    import_job._crm_import_job({"run_id": 7})
    assert ran == [7]
    assert bulk_jobs.uses_cloud_run() is False
