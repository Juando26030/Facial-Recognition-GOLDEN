"""Modo tranquilo del Job de operaciones (7-nov-2026, pedido de Juan David): que Neon pueda dormir cuando no hay actividad.

La app anota «hubo actividad» en un archivito del almacenamiento (`ops/active.json`, SIN consultar la base) cuando entra el primer ingreso/envío tras un rato inactivo o cambia el estado de un evento
o formulario (app/warmup.py::kick). El Job horario lo LEE al arrancar (tampoco toca la base): si la última actividad tiene menos de OPS_ACTIVE_WINDOW_H (3) horas, corre completo cada hora; si no,
corre completo solo en las horas OPS_IDLE_HOURS (3,4,5,11,19: respaldo diario, purga biométrica, paso semanal y un respaldo cada 8 h) y en las demás sale sin tocar la base.
Si el archivo no se puede leer, se asume que hay actividad (nunca se omite un respaldo por un fallo de lectura)."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from app.timeutil import utcnow

log = logging.getLogger("golden.ops")
KEY = "ops/active.json"
_last_write = 0.0
_lock = threading.Lock()


def mark_active() -> None:
    """Anota actividad ahora. Máximo una escritura cada 10 min por proceso; nunca rompe a quien la llama."""
    global _last_write
    now = time.monotonic()
    with _lock:
        if _last_write and now - _last_write < 600:
            return
        _last_write = now
    try:
        from app.storage import get_storage
        get_storage().put(KEY, json.dumps({"at": utcnow().isoformat()}).encode("utf-8"))
    except Exception:  # noqa: BLE001
        log.warning("no se pudo anotar la actividad para el modo tranquilo", exc_info=True)


def last_activity() -> Optional[datetime]:
    """None si nunca se anotó; lanza si no se puede leer."""
    from app.storage import get_storage
    st = get_storage()
    if not st.exists(KEY):
        return None
    return datetime.fromisoformat(json.loads(st.get(KEY).decode("utf-8"))["at"])


def idle_skip(now_local: datetime, now_utc: Optional[datetime] = None) -> Optional[str]:
    """Motivo (texto) para NO correr la tarea horaria completa ahora, o None si debe correr."""
    hours = {int(h) for h in os.getenv("OPS_IDLE_HOURS", "3,4,5,11,19").split(",") if h.strip().isdigit()}
    if now_local.hour in hours:
        return None
    try:
        last = last_activity()
    except Exception:  # noqa: BLE001 — sin poder leer, se asume actividad
        log.warning("no se pudo leer la actividad: se corre completo", exc_info=True)
        return None
    window = timedelta(hours=float(os.getenv("OPS_ACTIVE_WINDOW_H", "3")))
    if last is not None and (now_utc or utcnow()) - last < window:
        return None
    return f"sin actividad en las últimas {window.total_seconds() / 3600:g} h: la base descansa (corre en las horas {sorted(hours)})"
