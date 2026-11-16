"""Código sugerido para un evento nuevo (16-nov-2026): el número siguiente al más alto de los códigos solo numéricos que ya existen (p. ej. 2787 → 2788)."""
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from app.models import Event


def next_code(db: Session) -> str:
    top = db.query(func.max(cast(Event.event_code, Integer))).filter(Event.event_code.op("~")(r"^[0-9]{1,9}$")).scalar()
    return str((top or 0) + 1)
