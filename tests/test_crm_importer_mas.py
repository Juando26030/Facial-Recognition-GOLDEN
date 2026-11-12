"""Importador C1c-2 con base de datos y archivos SINTÉTICOS (SIN EJECUTAR hasta que Juan David las corra)."""
import json
import subprocess
import sys

from app.crm.codes import next_code
from app.models import CrmActivity, CrmImportRun, CrmOpportunity, CrmProduct, CrmProforma, CrmQuote, CrmQuoteLine, Event
from tests.crm_helpers import crm_on, staff_client  # noqa: F401

NAMES = {"accounts": "cuentas.csv", "contacts": "contactos.csv", "products": "productos.csv", "opportunities": "oportunidades.csv", "activities": "actividades.csv",
         "quotes": "cotizaciones.csv", "quote_lines": "lineas_cotizacion.csv", "proformas": "proformas.csv"}


def _files(tmp_path, n=30):
    subprocess.check_call([sys.executable, "scripts/crm_make_synthetic_suitecrm.py", str(tmp_path), str(n)])
    return {k: (tmp_path / v).read_bytes() for k, v in NAMES.items()}


def _post(client, mode, files, **form):
    return client.post("/api/crm/import/runs", data={"mode": mode, **form}, files={k: (k + ".csv", v) for k, v in files.items()})


def _drain():
    from app import jobs
    jobs.drain()


def _counts(db, run_id):
    db.expire_all()
    return json.loads(db.get(CrmImportRun, run_id).counts_json)


def test_dry_run_resolves_references_between_files_and_saves_nothing(client, factory, crm_on, db, tmp_path):
    staff_client(client, factory, "admin", "adm_m1")
    files = _files(tmp_path, 30)
    r = _post(client, "dry_run", files)
    assert r.status_code == 200, r.text
    _drain()
    c = _counts(db, r.json()["id"])
    assert c["contacts"]["counts"]["created"] == 30 and c["contacts"]["counts"]["without_account"] == 0          # las cuentas vienen en el mismo juego de archivos
    assert c["opportunities"]["counts"]["created"] == 30 and c["quotes"]["counts"]["created"] == 30 and c["activities"]["counts"]["unlinked"] == 0
    assert c["quotes"]["counts"]["total_only"] > 0 and c["quotes"]["counts"]["lines"] > 0
    for model in (CrmProduct, CrmOpportunity, CrmActivity, CrmQuote, CrmQuoteLine, CrmProforma):
        assert db.query(model).count() == 0


def test_apply_loads_everything_once_without_creating_events(client, factory, crm_on, db, tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_IMPORT_APPLY", "1")
    staff_client(client, factory, "admin", "adm_m2")
    files = _files(tmp_path, 30)
    events_before = db.query(Event).count()
    dry = _post(client, "dry_run", files).json()
    _drain()
    assert _post(client, "apply", files, confirm="CARGAR", dry_run_id=dry["id"]).status_code == 200
    _drain()
    db.expire_all()
    assert db.query(CrmProduct).count() == 10 and db.query(CrmOpportunity).count() == 30 and db.query(CrmQuote).count() == 30 and db.query(CrmProforma).count() == 15
    assert db.query(CrmOpportunity).filter(CrmOpportunity.outcome == "won").count() > 0
    assert db.query(CrmOpportunity).filter(CrmOpportunity.event_id.isnot(None)).count() == 0 and db.query(Event).count() == events_before          # lo ganado importado NO crea eventos
    assert next_code(db, "quote") > 7030 and next_code(db, "proforma") > 3015 and next_code(db, "event") > 9030
    again = _post(client, "apply", files, confirm="CARGAR", dry_run_id=dry["id"])
    _drain()
    assert again.status_code == 200 and db.query(CrmOpportunity).count() == 30 and db.query(CrmQuote).count() == 30 and db.query(CrmQuoteLine).count() == db.query(CrmQuoteLine).count()


def test_quote_totals_are_computed_by_the_server_from_the_lines(client, factory, crm_on, db, tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_IMPORT_APPLY", "1")
    staff_client(client, factory, "admin", "adm_m3")
    files = _files(tmp_path, 10)
    dry = _post(client, "dry_run", files).json()
    _drain()
    _post(client, "apply", files, confirm="CARGAR", dry_run_id=dry["id"])
    _drain()
    db.expire_all()
    q = db.query(CrmQuote).filter(CrmQuote.legacy_sugar_id == "sint-qte-0001").one()
    # dos unidades a 500.000 con 10 % de descuento + 1 a 250.000, IVA 19 %: neto 900.000 + 250.000 = 1.150.000; impuesto 218.500
    assert str(q.subtotal) == "1150000.00" and str(q.discount_total) == "100000.00" and str(q.tax_total) == "218500.00" and str(q.total) == "1368500.00"
    solo = db.query(CrmQuote).filter(CrmQuote.legacy_sugar_id == "sint-qte-0005").one()          # sin líneas pero con total: una línea «Total importado», sin impuesto
    assert str(solo.total) == "1190000.00" and db.query(CrmQuoteLine).filter(CrmQuoteLine.quote_id == solo.id).count() == 1


def test_bad_rows_are_rejected_with_row_number_and_no_values(client, factory, crm_on, db, tmp_path):
    staff_client(client, factory, "admin", "adm_m4")
    files = _files(tmp_path, 5)
    files["opportunities"] += "x9;9999;Evento sin cuenta secreta;Cuenta Que No Existe SAS;Prospecting;1000;COP;01/12/2026;;Bogotá\n".encode()
    r = _post(client, "dry_run", files)
    _drain()
    c = _counts(db, r.json()["id"])
    assert c["opportunities"]["counts"]["rejected"] == 1 and c["opportunities"]["counts"]["without_account"] == 1
    blob = json.dumps(c, ensure_ascii=False)
    assert "secreta" not in blob and "Cuenta Que No Existe" not in blob and c["opportunities"]["rejected"][0]["row"] == 7


def test_quote_lines_without_quotes_file_is_explained_not_failed(client, factory, crm_on, db, tmp_path):
    staff_client(client, factory, "admin", "adm_m5")
    files = _files(tmp_path, 5)
    r = _post(client, "dry_run", {"accounts": files["accounts"], "quote_lines": files["quote_lines"]})
    assert r.status_code == 200
    _drain()
    assert "note" in _counts(db, r.json()["id"])["quote_lines"]


def test_missing_required_column_is_refused_at_upload(client, factory, crm_on, db):
    staff_client(client, factory, "admin", "adm_m6")
    r = client.post("/api/crm/import/runs", data={"mode": "sample"}, files={"opportunities": ("o.csv", b"Importe\n10\n")})
    assert r.status_code == 400 and "obligatoria" in r.json()["detail"]
    assert db.query(CrmImportRun).count() == 0
