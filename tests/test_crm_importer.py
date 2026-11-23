"""Importador C1c-1 con base de datos y archivos SINTÉTICOS (SIN EJECUTAR hasta que Juan David las corra)."""
import json
import subprocess
import sys

from app.crm.importer import runner
from app.models import CrmAccount, CrmContact, CrmImportRun
from app.storage import get_storage
from tests.crm_helpers import crm_on, staff_client  # noqa: F401


def _files(tmp_path, n=30):
    subprocess.check_call([sys.executable, "scripts/crm_make_synthetic_suitecrm.py", str(tmp_path), str(n)])
    return {"accounts": (tmp_path / "cuentas.csv").read_bytes(), "contacts": (tmp_path / "contactos.csv").read_bytes()}


def _post(client, mode, files, **form):
    up = {"accounts": ("c.csv", files["accounts"]), "contacts": ("k.csv", files["contacts"])}
    return client.post("/api/crm/import/runs", data={"mode": mode, **form}, files=up)


def _drain():
    from app import jobs
    jobs.drain()


def test_sample_and_dry_run_save_nothing_and_delete_the_files(client, factory, crm_on, db, tmp_path):
    staff_client(client, factory, "admin", "adm_imp")
    files = _files(tmp_path)
    r = _post(client, "sample", files)
    assert r.status_code == 200, r.text
    _drain()
    db.expire_all()
    run = db.get(CrmImportRun, r.json()["id"])
    assert run.status == "done" and json.loads(run.counts_json)["accounts"]["counts"]["read"] == 20
    assert db.query(CrmAccount).count() == 0 and db.query(CrmContact).count() == 0
    assert get_storage().list(runner.prefix(run.id)) == []


def test_apply_is_blocked_without_the_flag_the_word_and_a_matching_dry_run(client, factory, crm_on, db, tmp_path, monkeypatch):
    staff_client(client, factory, "admin", "adm_imp2")
    files = _files(tmp_path)
    monkeypatch.delenv("CRM_IMPORT_APPLY", raising=False)
    assert _post(client, "apply", files, confirm="CARGAR").status_code == 403
    monkeypatch.setenv("CRM_IMPORT_APPLY", "1")
    assert _post(client, "apply", files, confirm="cargar?").status_code == 400
    assert _post(client, "apply", files, confirm="CARGAR").status_code == 400          # sin corrida de prueba
    dry = _post(client, "dry_run", files).json()
    _drain()
    other = dict(files, accounts=files["accounts"] + b"x;extra\n")
    assert _post(client, "apply", other, confirm="CARGAR", dry_run_id=dry["id"]).status_code == 400          # otros archivos


def test_apply_loads_accounts_and_contacts_once_and_raises_the_counter(client, factory, crm_on, db, tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_IMPORT_APPLY", "1")
    staff_client(client, factory, "admin", "adm_imp3")
    files = _files(tmp_path, 30)
    dry = _post(client, "dry_run", files).json()
    _drain()
    ok = _post(client, "apply", files, confirm="CARGAR", dry_run_id=dry["id"])
    assert ok.status_code == 200, ok.text
    _drain()
    assert db.query(CrmAccount).count() == 30 and db.query(CrmContact).count() == 30
    from app.crm.codes import next_code
    assert next_code(db, "account") > 5030          # el contador quedó por encima del mayor número de SuiteCRM
    again = _post(client, "apply", files, confirm="CARGAR", dry_run_id=dry["id"])
    _drain()
    assert again.status_code == 200 and db.query(CrmAccount).count() == 30          # idempotente: lo ya cargado se salta


def test_a_bad_row_is_rejected_without_values_and_the_rest_continues(client, factory, crm_on, db, tmp_path):
    staff_client(client, factory, "admin", "adm_imp4")
    raw = "Nombre;Número de cuenta\nBuena SAS;7001\n;7002\n" + "X" * 300 + ";7003\n"
    r = _post(client, "dry_run", {"accounts": raw.encode(), "contacts": b"Nombre\nAna\n"})
    _drain()
    counts = json.loads(db.get(CrmImportRun, r.json()["id"]).counts_json)["accounts"]
    assert counts["counts"]["created"] == 1 and counts["counts"]["rejected"] == 2
    assert "Buena" not in json.dumps(counts) and "XXX" not in json.dumps(counts)


def test_only_admins_can_use_the_importer(client, factory, crm_on, tmp_path):
    staff_client(client, factory, "comercial", "com_imp")
    assert client.get("/api/crm/import/runs").status_code == 403
