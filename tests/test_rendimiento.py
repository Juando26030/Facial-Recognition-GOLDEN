"""Rendimiento de la carga masiva y del reporte Excel (orden del 23-oct-2026): mismo resultado que antes, muchísimas menos consultas, reporte en segundo plano con progreso y acceso restringido.
La referencia de la carga (tests/golden/golden_load.json) se generó con el código ANTERIOR (main b225a2d) sobre los mismos datos (tests/_golden_load.py)."""
import io
import json
import os
import time
import zipfile

import pytest
from openpyxl import load_workbook
from sqlalchemy import event as sa_event

from app import report_jobs
from app.database import engine
from app.models import AccessLog, BulkJob, EventAttendee, User
from app.storage import get_storage
from tests import _golden_load as G
from tests.conftest import login

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "golden_load.json")


class SqlCount:
    def __enter__(self):
        self.n = 0
        self._f = lambda *a, **k: setattr(self, "n", self.n + 1)
        sa_event.listen(engine, "before_cursor_execute", self._f)
        return self

    def __exit__(self, *exc):
        sa_event.remove(engine, "before_cursor_execute", self._f)


def _rows(n, base=9900000000):
    return [[str(base + i + 1), f"Nombre{i}", f"Apellido{i}", "Asistente", f"Empresa {i % 40}", f"300{1000000 + i}", f"p{i}@example.com", "Invitado", ["General", "Zona A", ""][i % 3], "", "", "10/03/1990"] for i in range(n)]


# ---------------------------------------------------------------------------------------------------- CARGA: resultado idéntico al anterior
def test_the_batch_load_gives_exactly_the_same_result_as_the_previous_code(client, factory, db):
    ev, resp = G.golden_run(client, factory, db)
    got = G.dump(db, ev, resp)
    r2 = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(), "application/octet-stream")})
    assert r2.status_code == 200, r2.text
    got["retry"] = G.dump(db, ev, r2.json())
    want = json.load(open(GOLDEN, encoding="utf-8"))
    assert json.loads(json.dumps(got, sort_keys=True)) == want                  # mismos registros, mismos errores por fila, mismo mensaje, misma segunda carga


def test_a_load_makes_a_handful_of_queries_not_nine_per_person_and_a_retry_does_not_duplicate(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    data = G.xlsx_bytes(_rows(1200))
    with SqlCount() as q:
        r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["count"] == 1200 and r.json()["errors"] == []
    assert q.n < 80, q.n                                                                       # antes: 9 por persona (10.800 para 1.200)
    with SqlCount() as q2:
        r2 = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})
    assert r2.status_code == 200 and r2.json()["count"] == 1200
    assert q2.n < 80, q2.n
    db.expire_all()
    assert db.query(User).filter_by(tenant_id=ev.tenant_id).count() == 1200 and db.query(EventAttendee).filter_by(event_id=ev.id).count() == 1200      # cero duplicados, cero filas perdidas


def test_a_batch_the_database_rejects_is_retried_row_by_row_and_only_the_bad_row_is_reported(client, factory, db, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    import app.routers.api as api
    monkeypatch.setattr(api, "_BULK_CHUNK", 4)
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    real_flush = Session.flush

    def flush(self, *a, **k):
        if any(isinstance(o, User) and o.id == "9900000003" for o in self.new):         # la base rechaza a esa persona, donde sea que viaje
            raise IntegrityError("INSERT users", {}, Exception("violación simulada"))
        return real_flush(self, *a, **k)
    monkeypatch.setattr(Session, "flush", flush)
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(10)), "application/octet-stream")})
    assert r.status_code == 200, r.text
    bad = [e for e in r.json()["errors"] if e.startswith("❌")]
    assert len(bad) == 1 and "violación simulada" in bad[0] and r.json()["count"] == 9           # las otras 9 quedan guardadas
    monkeypatch.setattr(Session, "flush", real_flush)
    db.expire_all()
    ids = sorted(u.id for u in db.query(User).filter_by(tenant_id=ev.tenant_id))
    assert "9900000003" not in ids and len(ids) == 9
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 9


def test_a_file_with_more_rows_than_the_limit_is_refused_with_a_clear_message_and_nothing_is_saved(client, factory, db, monkeypatch):
    import app.routers.api as api
    monkeypatch.setattr(api, "ROSTER_MAX_ROWS", 50)
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(51)), "application/octet-stream")})
    assert r.status_code == 400 and "máximo" in r.json()["detail"] and "50" in r.json()["detail"] and "51" in r.json()["detail"]
    assert db.query(User).filter_by(tenant_id=ev.tenant_id).count() == 0


def test_the_background_load_reports_progress_and_finishes_with_the_same_result(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true"}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(1500)), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["background"] is True
    job_id = r.json()["job_id"]
    seen = []
    for _ in range(120):
        st = client.get(f"/api/bulk_jobs/{job_id}").json()
        seen.append((st["status"], st.get("stage")))
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert st["status"] == "done", st
    assert st["result"]["count"] == 1500
    assert any("Guardando personas" in (s or "") for _, s in seen) or st["status"] == "done"


# ---------------------------------------------------------------------------------------------------- REPORTE
@pytest.fixture()
def loaded(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(300)), "application/octet-stream")})
    assert r.status_code == 200
    ids = [a.user_id for a in db.query(EventAttendee).filter_by(event_id=ev.id)]
    for i, uid in enumerate(ids[:250]):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional" if i % 2 else "qr"))
    db.commit()
    return ev


def _cells(content):
    ws = load_workbook(io.BytesIO(content)).active
    return [[c.value for c in row] for row in ws.iter_rows()]


def _start(client, ev):
    r = client.post("/api/report/start", json={"event_id": ev.id})
    assert r.status_code == 200, r.text
    st = r.json()
    for _ in range(80):
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.25)
        st = client.get(f"/api/report/status/{st['job_id']}").json()
    return st


def test_the_background_report_is_the_same_excel_as_the_direct_one_and_downloads_ready_made(client, loaded):
    ev = loaded
    direct = client.get(f"/api/report?event_id={ev.id}")
    assert direct.status_code == 200
    st = _start(client, ev)
    assert st["status"] == "done" and st["ready"] is True and st["percent"] == 100 and st["expires_at"]
    dl = client.get(f"/api/report/download/{st['job_id']}")
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "Golden_Reporte_Eventos.xlsx" in dl.headers["content-disposition"] and dl.headers["cache-control"] == "no-store"
    a, b = _cells(direct.content), _cells(dl.content)
    assert len(a) == len(b) == 300 + 5 and a[:5] == b[:5]                            # título + encabezado + 300 filas, mismas columnas
    by_id = lambda row: str(row[0])                                                  # noqa: E731 — el orden de las filas lo decide la base (colación): se compara por cédula, en Python
    assert sorted(a[5:], key=by_id) == sorted(b[5:], key=by_id)                      # mismos datos, fila por fila
    assert a[4][0] == "Cédula" and sum(1 for row in a[5:] if row[-3] != "No registrado") == 250


def test_the_report_progress_goes_through_named_stages(client, loaded, monkeypatch):
    stages = []
    real = report_jobs.ReportManager.generate_excel_report

    def spy(db, event_id, tenant_id, path, progress=None):
        def p(stage, done, total, force=False):
            stages.append((stage, done))
            return progress(stage, done, total, force=force)
        return real(db, event_id, tenant_id, path, progress=p)
    monkeypatch.setattr(report_jobs.ReportManager, "generate_excel_report", staticmethod(spy))
    assert _start(client, loaded)["status"] == "done"
    names = [s for s, _ in stages]
    assert names[0].startswith("Leyendo") and "Armando el Excel" in names and names[-1] == "Excel listo"
    assert [d for _, d in stages] == sorted(d for _, d in stages)                    # el avance nunca retrocede


def test_a_report_that_fails_halfway_ends_in_a_clear_error_and_can_be_retried(client, loaded, monkeypatch):
    real = report_jobs.ReportManager.generate_excel_report
    monkeypatch.setattr(report_jobs.ReportManager, "generate_excel_report", staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla simulada"))))
    st = _start(client, loaded)
    assert st["status"] == "error" and "falla simulada" in st["error"] and st["ready"] is False
    assert client.get(f"/api/report/download/{st['job_id']}").status_code == 409            # no hay nada que descargar
    monkeypatch.setattr(report_jobs.ReportManager, "generate_excel_report", staticmethod(real))
    assert _start(client, loaded)["status"] == "done"                                        # reintentar funciona


def test_only_who_asked_can_see_or_download_the_report_and_clients_cannot_start_it(client, factory, db, loaded):
    ev = loaded
    st = _start(client, ev)
    factory.staff("coordinador", "otro")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).filter_by(username="otro").one())
    client.cookies.clear()
    login(client, "otro")
    assert client.get(f"/api/report/status/{st['job_id']}").status_code == 404
    assert client.get(f"/api/report/download/{st['job_id']}").status_code == 404
    factory.staff("digitador", "dig")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).filter_by(username="dig").one())
    factory.staff("cliente", "cli")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).filter_by(username="cli").one())
    for user in ("dig", "cli"):
        client.cookies.clear()
        login(client, user)
        assert client.post("/api/report/start", json={"event_id": ev.id}).status_code == 403, user
        assert client.get(f"/api/report/download/{st['job_id']}").status_code == 403, user
    client.cookies.clear()
    assert client.get(f"/api/report/download/{st['job_id']}").status_code in (401, 403)       # sin sesión


def test_the_report_file_expires_and_is_deleted_and_the_download_says_so(client, loaded, db, monkeypatch):
    st = _start(client, loaded)
    key = json.loads(db.get(BulkJob, st["job_id"]).result_json)["key"]
    assert get_storage().exists(key)
    assert key.endswith(f"{st['job_id']}.xlsx") and "Nombre" not in key and "9900" not in key           # el nombre del archivo no lleva datos personales
    job = db.get(BulkJob, st["job_id"])
    from datetime import timedelta
    job.finished_at = job.finished_at - timedelta(minutes=61)
    db.commit()
    assert client.get(f"/api/report/download/{st['job_id']}").status_code == 410
    assert report_jobs.purge_expired(db) == 1
    assert not get_storage().exists(key)
    assert client.get(f"/api/report/status/{st['job_id']}").json()["expired"] is True
    assert client.get(f"/api/report/download/{st['job_id']}").status_code == 410
    from app import ops_runner
    assert "0 reporte(s)" in ops_runner.purge_reports()


def test_a_second_click_returns_the_same_running_report_and_another_user_waits(client, loaded, db):
    ev = loaded
    from app.models import StaffUser
    me = db.query(StaffUser).filter_by(username="coord1").one()
    running = BulkJob(id="r" * 32, event_id=ev.id, staff_user_id=me.id, status="running", stage="Armando", done=30, total=100, spec_json=report_jobs.KIND)
    db.add(running)
    db.commit()
    again = client.post("/api/report/start", json={"event_id": ev.id}).json()
    assert again["job_id"] == "r" * 32 and again["status"] == "running" and again["percent"] == 30
    running.staff_user_id = None
    db.commit()
    assert client.post("/api/report/start", json={"event_id": ev.id}).status_code == 409


def test_signatures_cost_one_listing_not_one_storage_call_per_person(client, factory, db, monkeypatch):
    """La causa probable de los 83 s: con un campo de firma, el reporte preguntaba al almacenamiento por CADA persona."""
    from app.models import EventFieldConfig
    from app.reports import ReportManager
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    ev.set_optional_labels({"opcional_1": "Firma"})
    db.add(EventFieldConfig(event_id=ev.id, field_key="opcional_1", label="Firma", field_type="signature"))
    db.commit()
    assert client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(400)), "application/octet-stream")}).status_code == 200
    st = get_storage()
    calls = {"exists": 0, "list": 0}
    real_exists, real_list = type(st).exists, type(st).list
    monkeypatch.setattr(type(st), "exists", lambda self, k: (calls.__setitem__("exists", calls["exists"] + 1), real_exists(self, k))[1])
    monkeypatch.setattr(type(st), "list", lambda self, p: (calls.__setitem__("list", calls["list"] + 1), real_list(self, p))[1])
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, os.path.join(os.environ.get("TEMP", "."), "firmas_prueba.xlsx"))
    assert calls["exists"] == 0 and calls["list"] == 1, calls


def test_every_http_request_of_the_report_and_the_load_stays_far_below_the_proxy_limit_with_3000_people(client, factory, db):
    """Ninguna petición individual (cargar, iniciar, estado, descargar) pasa de ~10 s con 3.000 personas (el límite de Firebase Hosting es 60 s). Con 8.000: ver la guía de medición."""
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    slow = []

    def timed(fn, label):
        t = time.perf_counter()
        r = fn()
        slow.append((label, time.perf_counter() - t))
        return r
    r = timed(lambda: client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", G.xlsx_bytes(_rows(3000)), "application/octet-stream")}), "cargar")
    assert r.status_code == 200 and r.json()["count"] == 3000
    st = timed(lambda: client.post("/api/report/start", json={"event_id": ev.id}).json(), "iniciar")
    while st["status"] in ("queued", "running"):
        st = timed(lambda: client.get(f"/api/report/status/{st['job_id']}").json(), "estado")
        time.sleep(0.2)
    assert st["status"] == "done"
    dl = timed(lambda: client.get(f"/api/report/download/{st['job_id']}"), "descargar")
    assert dl.status_code == 200 and len(_cells(dl.content)) == 3000 + 5
    assert max(t for _, t in slow) < 10, slow


def test_the_old_direct_report_still_works_for_a_small_event(client, loaded):
    assert client.get(f"/api/report?event_id={loaded.id}").status_code == 200


def test_the_zip_of_a_report_is_a_valid_excel_file(client, loaded):
    st = _start(client, loaded)
    content = client.get(f"/api/report/download/{st['job_id']}").content
    assert zipfile.is_zipfile(io.BytesIO(content)) and "xl/worksheets/sheet1.xml" in zipfile.ZipFile(io.BytesIO(content)).namelist()
