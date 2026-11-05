"""Persona de prueba de cada evento (pedido de Juan David, 5-nov-2026).

Todo evento que se crea trae una persona de prueba (cédula «PRUEBA», todos los campos dicen «prueba») para ensayar la impresión de la escarapela y el flujo del registro sin tocar datos reales.
Reglas:
- Se ve en el Directorio (con la marca `test`), se puede acreditar e imprimir AUN con el evento en modo «creado» (para eso existe).
- NUNCA entra en lo que se mide: ni el reporte (Excel), ni las estadísticas, ni la ruleta, ni los contadores del Directorio, ni el «¿tiene gente cargada?» del evento.
- Es la única excepción a «solo se registra/imprime con el evento en proceso».
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Event, EventAttendee, User

TEST_ID = "PRUEBA"
TEST_ORIGIN = "prueba"
TEST_FIELDS = {
    "first_name": "Prueba", "last_name": "Prueba", "role": "Cargo prueba", "entity": "Entidad prueba", "phone": "Teléfono prueba",
    "email": "prueba@prueba.com", "opt_1": "Tipo de asistente prueba",
}


def is_test(user_id) -> bool:
    return str(user_id or "").strip().upper() == TEST_ID


def drop_test(ids):
    """Los mismos ids sin la persona de prueba (conserva el tipo: set o lista)."""
    kept = [i for i in ids if not is_test(i)]
    return set(kept) if isinstance(ids, (set, frozenset)) else kept


def ensure_for_event(db: Session, event: Event) -> Optional[str]:
    """Deja la persona de prueba en este evento (idempotente). Hace flush, no commit: el que llama confirma."""
    user = db.query(User).filter(User.id == TEST_ID, User.tenant_id == event.tenant_id).first()
    if user is None:
        db.add(User(id=TEST_ID, tenant_id=event.tenant_id, is_biometric_enabled=False, **TEST_FIELDS))      # sin rostro: la prueba es de cédula y de impresión
        db.flush()
    if db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id == TEST_ID).first() is None:
        db.add(EventAttendee(event_id=event.id, user_id=TEST_ID, tenant_id=event.tenant_id, origin=TEST_ORIGIN))
        db.flush()
    return TEST_ID
