"""Fase 3, oleada documentos y legalizaciones (7-nov-2026): archivar = ocultar y restaurar (admin+); borrado definitivo solo super_admin, de lo ya archivado, y borra
también el archivo del almacenamiento; el archivo se conserva mientras esté archivado; todo deja rastro en audit_actions."""
import inspect
import io
import zipfile

from PIL import Image

from app.models import AuditAction, EventDocument, EventExpense
from app.storage import get_storage
from tests.conftest import login


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


def _setup(client, factory, role="admin"):
    ev = factory.event()
    factory.staff(role, "actor")
    login(client, "actor")
    return ev


def _doc(client, ev, name="Contrato"):
    r = client.post(f"/api/events/{ev.id}/documents", data={"name": name}, files={"file": ("contrato.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _exp(client, ev, amount="100", evidence=True):
    files = {"evidence": ("f.png", _png(), "image/png")} if evidence else None
    r = client.post(f"/api/events/{ev.id}/expenses", data={"category": "Transporte", "responsible": "Ana", "amount": amount}, files=files)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ids(r):
    return {x["id"] for x in r.json()}


def test_sources_guard_roles():
    from app.routers import event_docs as ed
    for fn in (ed.archive_document, ed.restore_document, ed.archive_expense, ed.restore_expense):
        assert "ARCHIVE_ROLE" in inspect.getsource(fn)
    for fn in (ed.delete_document, ed.delete_expense):
        assert "HARD_DELETE_ROLE" in inspect.getsource(fn)
    assert 'require_role("admin")' in inspect.getsource(ed).split("ARCHIVE_ROLE =")[1].splitlines()[0]
    assert 'require_role("super_admin")' in inspect.getsource(ed).split("HARD_DELETE_ROLE =")[1].splitlines()[0]


def test_document_archive_hides_from_list_and_zip_keeps_file_and_restores(client, factory, db):
    ev = _setup(client, factory)
    d1, d2 = _doc(client, ev, "Uno"), _doc(client, ev, "Dos")
    stored = db.query(EventDocument).filter_by(id=d1).one().stored_path
    assert client.post(f"/api/events/{ev.id}/documents/{d1}/archive").status_code == 200
    assert client.post(f"/api/events/{ev.id}/documents/{d1}/archive").status_code == 400
    assert _ids(client.get(f"/api/events/{ev.id}/documents")) == {d2}
    assert _ids(client.get(f"/api/events/{ev.id}/documents", params={"include_archived": "true"})) == {d1, d2}
    names = zipfile.ZipFile(io.BytesIO(client.get(f"/api/events/{ev.id}/documents/zip").content)).namelist()
    assert len(names) == 1 and names[0].startswith("Dos")
    assert get_storage().exists(stored)                                                   # el archivo se conserva
    assert client.get(f"/api/events/{ev.id}/documents/{d1}/download").status_code == 200  # admin+ aún lo puede bajar
    assert client.post(f"/api/events/{ev.id}/documents/{d1}/restore").status_code == 200
    assert client.post(f"/api/events/{ev.id}/documents/{d1}/restore").status_code == 400
    assert _ids(client.get(f"/api/events/{ev.id}/documents")) == {d1, d2}
    acts = [(a.action, a.entity) for a in db.query(AuditAction).order_by(AuditAction.id)]
    assert acts == [("archive", "event_document"), ("restore", "event_document")]


def test_coordinator_cannot_archive_restore_delete_or_see_archived(client, factory):
    ev = _setup(client, factory, "coordinador")
    d, e = _doc(client, ev), _exp(client, ev)
    for url in (f"documents/{d}/archive", f"documents/{d}/restore", f"expenses/{e}/archive", f"expenses/{e}/restore"):
        assert client.post(f"/api/events/{ev.id}/{url}").status_code == 403
    assert client.delete(f"/api/events/{ev.id}/documents/{d}").status_code == 403
    assert client.delete(f"/api/events/{ev.id}/expenses/{e}").status_code == 403
    assert client.get(f"/api/events/{ev.id}/documents", params={"include_archived": "true"}).status_code == 403
    assert client.get(f"/api/events/{ev.id}/expenses", params={"include_archived": "true"}).status_code == 403


def test_admin_cannot_hard_delete_and_super_admin_needs_it_archived(client, factory):
    ev = _setup(client, factory, "admin")
    d, e = _doc(client, ev), _exp(client, ev)
    client.post(f"/api/events/{ev.id}/documents/{d}/archive")
    client.post(f"/api/events/{ev.id}/expenses/{e}/archive")
    assert client.delete(f"/api/events/{ev.id}/documents/{d}").status_code == 403
    assert client.delete(f"/api/events/{ev.id}/expenses/{e}").status_code == 403
    client.post("/logout")
    factory.staff("super_admin", "sup")
    login(client, "sup")
    d2, e2 = _doc(client, ev, "Activo"), _exp(client, ev)
    assert client.delete(f"/api/events/{ev.id}/documents/{d2}").status_code == 400         # activo: primero archivar
    assert client.delete(f"/api/events/{ev.id}/expenses/{e2}").status_code == 400


def test_hard_delete_removes_row_and_storage_file_and_is_logged(client, factory, db):
    ev = _setup(client, factory, "super_admin")
    d, e = _doc(client, ev), _exp(client, ev)
    spath = db.query(EventDocument).filter_by(id=d).one().stored_path
    epath = db.query(EventExpense).filter_by(id=e).one().evidence_path
    assert get_storage().exists(spath) and get_storage().exists(epath)
    client.post(f"/api/events/{ev.id}/documents/{d}/archive")
    client.post(f"/api/events/{ev.id}/expenses/{e}/archive")
    assert client.delete(f"/api/events/{ev.id}/documents/{d}").status_code == 200
    assert client.delete(f"/api/events/{ev.id}/expenses/{e}").status_code == 200
    db.expire_all()
    assert db.query(EventDocument).count() == 0 and db.query(EventExpense).count() == 0
    assert not get_storage().exists(spath) and not get_storage().exists(epath)
    assert {(a.action, a.entity) for a in db.query(AuditAction)} >= {("delete", "event_document"), ("delete", "event_expense")}
    assert all(a.actor_role == "super_admin" for a in db.query(AuditAction))


def test_expense_archive_leaves_total_list_and_report_but_keeps_evidence(client, factory, db):
    ev = _setup(client, factory)
    e1, e2 = _exp(client, ev, "100"), _exp(client, ev, "50")
    epath = db.query(EventExpense).filter_by(id=e1).one().evidence_path
    assert client.get(f"/api/events/{ev.id}/expenses").json()["total"] == 150
    assert client.post(f"/api/events/{ev.id}/expenses/{e1}/archive").status_code == 200
    assert client.post(f"/api/events/{ev.id}/expenses/{e1}/archive").status_code == 400
    data = client.get(f"/api/events/{ev.id}/expenses").json()
    assert {x["id"] for x in data["expenses"]} == {e2}
    assert data["total"] == 50
    with_arch = client.get(f"/api/events/{ev.id}/expenses", params={"include_archived": "true"}).json()
    assert {x["id"] for x in with_arch["expenses"]} == {e1, e2} and with_arch["total"] == 50      # el archivado no suma
    rep = client.get(f"/api/events/{ev.id}/expenses/report")
    assert rep.status_code == 200
    import pandas as pd
    df = pd.read_excel(io.BytesIO(rep.content), header=4)
    assert len(df[df["Categoría"] == "Transporte"]) == 1
    assert get_storage().exists(epath) and client.get(f"/api/events/{ev.id}/expenses/{e1}/evidence").status_code == 200
    assert client.post(f"/api/events/{ev.id}/expenses/{e1}/restore").status_code == 200
    assert client.get(f"/api/events/{ev.id}/expenses").json()["total"] == 150


def test_archived_items_hidden_from_coordinator_evidence_and_download(client, factory):
    ev = _setup(client, factory, "admin")
    d, e = _doc(client, ev), _exp(client, ev)
    client.post(f"/api/events/{ev.id}/documents/{d}/archive")
    client.post(f"/api/events/{ev.id}/expenses/{e}/archive")
    client.post("/logout")
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get(f"/api/events/{ev.id}/documents/{d}/download").status_code == 404
    assert client.get(f"/api/events/{ev.id}/expenses/{e}/evidence").status_code == 404
    assert client.get(f"/api/events/{ev.id}/documents").json() == []


def test_no_edit_endpoints_exist_for_documents_or_expenses():
    """Hoy no hay edición de documentos ni gastos (solo crear / leer / archivar); si se agrega, debe rechazar los archivados."""
    from app.routers import event_docs as ed
    methods = {m for r in ed.router.routes for m in r.methods}
    assert not methods & {"PUT", "PATCH"}


def test_archive_unknown_ids_404(client, factory):
    ev = _setup(client, factory)
    assert client.post(f"/api/events/{ev.id}/documents/999/archive").status_code == 404
    assert client.post(f"/api/events/{ev.id}/expenses/999/archive").status_code == 404
