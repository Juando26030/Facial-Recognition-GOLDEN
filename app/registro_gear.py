"""Plan 7 (Registro limpio): quién ve el engranaje de «Configuración del registro».

Coordinador, admin y super_admin SIEMPRE lo usan. Desde el 21-nov-2026 el digitador también VE el engranaje siempre; si en Parámetros del evento está apagada «Mostrar la
configuración del registro a los digitadores» (apagada por defecto), el engranaje queda BLOQUEADO: al tocarlo pide la contraseña de desbloqueo del evento (app/config_lock.py).
Es solo de pantalla: lo ya configurado (autoregistro, autoimpresión, impresora) no se toca y los permisos de la API no cambian.
Se guarda en `app_settings` (una fila por evento), sin migración.
"""
from typing import Iterable

from app.models import AppSetting
from app.timeutil import utcnow

PRIVILEGED = {"coordinador", "admin", "super_admin"}


def setting_key(event_id: int) -> str:
    return f"registro_gear_dig:{int(event_id)}"


def digitadores_enabled(db, event_id: int) -> bool:
    row = db.get(AppSetting, setting_key(event_id))
    return bool(row and (row.value or "").strip() == "1")


def set_digitadores_enabled(db, event_id: int, enabled: bool) -> None:
    row = db.get(AppSetting, setting_key(event_id))
    if row is None:
        row = AppSetting(key=setting_key(event_id))
        db.add(row)
    row.value = "1" if enabled else "0"
    row.updated_at = utcnow()


def can_see_gear(db, event_id: int, roles: Iterable[str]) -> bool:
    """`roles`: los roles efectivos de la persona (con doble rol, cualquiera de ellos). El digitador lo ve siempre (bloqueado o no: app/config_lock.py)."""
    roles = set(roles)
    return bool(roles & PRIVILEGED) or "digitador" in roles
