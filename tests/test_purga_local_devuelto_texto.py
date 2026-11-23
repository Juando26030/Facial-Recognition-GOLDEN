"""Purga local de un evento devuelto a internet (revisión 2ª pasada, Fase 6 punto 4). Pruebas de TEXTO: no necesitan base de datos ni FastAPI."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent


def _fn(path: str, name: str) -> str:
    text = (SRC / path).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node)
    raise AssertionError(f"no existe {name} en {path}")


def test_release_event_purga_despues_de_liberar_en_la_nube():
    src = _fn("app/node_sync.py", "release_event")
    assert src.index('"/release"') if '"/release"' in src else src.index("/release")
    assert src.index("/release") < src.index("event.cloud_event_id = None") < src.index("purge_returned(db, event)")


def test_purge_returned_nunca_deshace_la_devolucion_y_deja_marca():
    src = _fn("app/node_sync.py", "purge_returned")
    assert "privacy.purge_returned_event" in src and "RETURNED_PURGE_PENDING" in src and "db.rollback()" in src
    assert "exc_info" not in src                                  # nada de datos personales en logs
    assert "retry_pending_purges(db)" in (SRC / "app/node_sync.py").read_text(encoding="utf-8")


def test_purge_returned_event_reglas():
    src = _fn("app/privacy.py", "purge_returned_event")
    assert "_erase(user)" in src                                  # foto por app/storage.py (enroll.delete_photos), vector y consentimiento
    assert "cloud_event_id.isnot(None)" in src                    # no se borra a quien sigue en otro evento bajado de la nube
    assert "exc_info" not in src                                  # la ruta de la foto lleva la cédula
    assert "audit_consent_logs" in src and "biometrics_purged_at" in src
    assert "utcnow()" in src and "open(" not in src
    assert "RETURNED_PURGE_PENDING" in (SRC / "app/privacy.py").read_text(encoding="utf-8")
