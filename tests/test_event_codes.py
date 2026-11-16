"""Código sugerido para un evento nuevo (16-nov-2026). DATOS SINTÉTICOS."""
from app import event_codes
from tests.test_event_transfer import _build


def test_next_code_continues_after_highest_numeric(db, factory):
    ev = _build(db, factory)
    ev.event_code = "2787"
    factory.event("creado").event_code = "FERIA-9999"              # alfanumérico: no cuenta
    factory.event("creado").event_code = "2369801"                 # 7 dígitos: no cuenta (desplazaría la serie)
    db.commit()
    assert event_codes.next_code(db) == "2788"
