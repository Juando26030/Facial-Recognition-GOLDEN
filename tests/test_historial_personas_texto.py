"""Fase 10 (E): comprobaciones «de texto» del historial por persona (corren sin base de datos): cada punto de edición lo alimenta, la migración, la privacidad y la tabla."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def src(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_every_person_edit_point_feeds_the_history():
    api, forms = src("app/routers/api.py"), src("app/formsvc.py")
    assert 'person_history.record(db, user, history_before, event_id=event.id, staff_id=staff.id, source="edit")' in api            # PATCH /users/{id}
    assert 'source="outbox"' in api and 'source="bulk"' in api                                                                        # bandeja sin conexión (y sync del nodo) y carga masiva
    assert 'source="form"' in forms and "person_history.snapshot(user)" in forms                                                       # formularios web que actualizan la base
    assert "record_id_change" in api and "PersonChangeLog.user_id == old_id" in api                                                    # corrección de cédula


def test_history_never_stores_biometrics_or_logs_values():
    s = src("app/person_history.py")
    assert "face_encoding" not in s.split('"""', 2)[2] and "log." not in s and "logging" not in s
    m = src("app/models.py").split("class PersonChangeLog")[1].split("class ")[0]
    assert "face" not in m and "photo" not in m


def test_deleted_with_person_event_and_suppression():
    assert "DELETE FROM person_change_log" in src("app/privacy.py")
    assert "person_history.delete_for_person" in src("app/routers/api.py")
    assert "person_history.delete_for_event" in src("app/routers/events.py")
    assert '"person_change_log"' in src("app/event_transfer.py")


def test_migration_is_0127_and_chained():
    t = ast.parse(src("alembic/versions/0127_person_change_log.py"))
    vals = {n.targets[0].id: ast.literal_eval(n.value) for n in t.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("revision", "down_revision")}
    assert vals["revision"] == "0127_person_change_log" and len(vals["revision"]) <= 32 and vals["down_revision"]


def test_excel_sheet_and_ficha_panel_exist():
    assert "Historial de cambios" in src("app/reports.py")
    js = src("static/js/directory.js")
    assert "editModalHistory" in js and "/change-history" in js and "onclick" not in js.split("editModalHistory")[1][:1500]
