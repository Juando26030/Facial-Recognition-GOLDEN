"""Tamaño del logo de Golden (6-nov-2026, pedido de Juan David): un solo valor para todo el sistema, que cambia el super administrador en Configuración → Apariencia y se ve en el encabezado de
todas las pantallas que muestran el logo de Golden (las de un evento con logo propio usan el tamaño de ESE evento). Vive en `app_settings` (clave `golden_logo_height`, sin migración)."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.timeutil import utcnow
from app.ttlcache import TTLCache

SETTING_KEY = "golden_logo_height"
MIN_H, MAX_H, DEFAULT_H = 30, 80, 50          # el encabezado mide 80 px: no cabe un logo más alto
_cache = TTLCache(ttl=30)


def clamp(value) -> int:
    try:
        return max(MIN_H, min(MAX_H, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_H


def get(db: Optional[Session] = None) -> int:
    """Alto en px del logo de Golden. Con caché de 30 s: se lee en CADA página, no puede costar una consulta cada vez."""
    hit = _cache.get("h")
    if hit is not None:
        return hit
    from app.database import SessionLocal
    own = db is None
    session = db or SessionLocal()
    try:
        row = session.get(AppSetting, SETTING_KEY)
        value = clamp(row.value) if row is not None and row.value else DEFAULT_H
    except Exception:       # noqa: BLE001 — sin base o sin tabla: el tamaño de siempre, nunca una página rota
        value = DEFAULT_H
    finally:
        if own:
            session.close()
    _cache.set("h", value)
    return value


def set_height(db: Session, value) -> int:
    h = clamp(value)
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        db.add(row)
    row.value, row.updated_at = str(h), utcnow()
    db.commit()
    _cache.set("h", h)
    return h
