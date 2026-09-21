"""Hora local para reportes nuevos (reunión 2026-09-21). La base guarda todo en UTC (`datetime.utcnow`);
un reporte con "hora exacta" tiene que mostrarla en la hora de quien lo lee. Zona configurable con
APP_TIMEZONE (por defecto America/Bogota, UTC-5 sin horario de verano)."""
import os
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Bogota"))
except Exception:  # sin base de zonas horarias (ej. Windows sin el paquete tzdata): UTC-5 fijo
    _TZ = timezone(timedelta(hours=-5))


def to_local(dt: datetime) -> datetime:
    """`dt` naive en UTC -> datetime en la zona local configurada."""
    return dt.replace(tzinfo=timezone.utc).astimezone(_TZ)
