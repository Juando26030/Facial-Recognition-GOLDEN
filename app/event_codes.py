"""Código sugerido para un evento nuevo (16-nov-2026): el número siguiente al más alto de los códigos solo numéricos de hasta 6 dígitos que ya existen (p. ej. 23775 → 23776).
Los de 7 o más dígitos (p. ej. «2369801» = código + sufijo de un evento aparte) no cuentan: desplazarían toda la serie."""
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from app.models import Event


def next_code(db: Session) -> str:
    top = db.query(func.max(cast(Event.event_code, Integer))).filter(Event.event_code.op("~")(r"^[0-9]{1,6}$")).scalar()
    return str((top or 0) + 1)
