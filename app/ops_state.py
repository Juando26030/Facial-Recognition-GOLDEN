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


# ------------------------------------------------------------------ Job económico (10-nov-2026): cada paso decide por tiempo desde su última ejecución
STEPS_KEY = "ops/steps.json"      # {"paso": "ISO UTC de la última vez que salió bien", ...}; en el almacenamiento, SIN consultar la base


def min_interval_minutes() -> int:
    """OPS_MIN_INTERVAL_MINUTES: si el Job completo corrió hace menos que esto, el siguiente aviso del Scheduler sale sin hacer nada (ni leer la base). Por defecto 50: compatible con el Scheduler cada hora
    (los avisos llegan ~60 min separados). Con el Scheduler cada 2 h se puede subir a 110. Inválido o negativo → 50."""
    try:
        return max(0, min(1440, int(os.getenv("OPS_MIN_INTERVAL_MINUTES", "50"))))
    except ValueError:
        return 50


def load_steps() -> dict:
    """Última ejecución buena de cada paso. Si no se puede leer devuelve {} (= todo vence: jamás se omite un respaldo o una purga por un fallo de lectura)."""
    try:
        from app.storage import get_storage
        st = get_storage()
        if not st.exists(STEPS_KEY):
            return {}
        data = json.loads(st.get(STEPS_KEY).decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        log.warning("no se pudo leer el estado de los pasos del Job: se asume que todo vence", exc_info=True)
        return {}


def save_steps(steps: dict) -> None:
    try:
        from app.storage import get_storage
        get_storage().put(STEPS_KEY, json.dumps(steps, sort_keys=True).encode("utf-8"))
    except Exception:  # noqa: BLE001 — sin poder anotar, el próximo aviso repite pasos (más costo, nunca menos seguridad)
        log.warning("no se pudo guardar el estado de los pasos del Job", exc_info=True)


def _parse(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def stamp(now_utc: Optional[datetime] = None) -> str:
    return (now_utc or utcnow()).replace(microsecond=0).isoformat()


def due_every(steps: dict, name: str, hours: float, now_utc: Optional[datetime] = None) -> bool:
    """¿Pasaron `hours` horas desde la última ejecución buena de `name` (o nunca corrió)?"""
    last = _parse(steps.get(name))
    return last is None or (now_utc or utcnow()) - last >= timedelta(hours=hours)


def due_daily(steps: dict, name: str, now_local: datetime, hour: int) -> bool:
    """Una vez por día local, a partir de `hour` (si el Job no cae justo en esa hora, corre en el primer aviso posterior ese mismo día)."""
    if now_local.hour < hour:
        return False
    last = _parse(steps.get(name))
    if last is None:
        return True
    from app.timeutil import to_local
    return to_local(last).date() < now_local.date()


def due_weekly(steps: dict, name: str, now_local: datetime, weekday: int, hour: int, now_utc: Optional[datetime] = None) -> bool:
    """Una vez por semana: pasaron al menos 6,5 días desde la última vez y ya es la hora del día fijada. Si nunca corrió, solo el día de la semana fijado."""
    if now_local.hour < hour:
        return False
    last = _parse(steps.get(name))
    if last is None:
        return now_local.weekday() == weekday
    return (now_utc or utcnow()) - last >= timedelta(days=6.5)


def due_monthly(steps: dict, name: str, now_local: datetime, day: int, hour: int) -> bool:
    """Una vez por mes calendario, desde el día `day` a la hora `hour`."""
    if (now_local.day, now_local.hour) < (day, hour):
        return False
    last = _parse(steps.get(name))
    if last is None:
        return True
    from app.timeutil import to_local
    ll = to_local(last)
    return (ll.year, ll.month) != (now_local.year, now_local.month)


def recently_active(now_utc: Optional[datetime] = None) -> bool:
    """¿Hubo actividad anotada en las últimas OPS_ACTIVE_WINDOW_H (3) horas? Sin poder leerla → True (no se omite nada)."""
    try:
        last = last_activity()
    except Exception:  # noqa: BLE001
        return True
    window = timedelta(hours=float(os.getenv("OPS_ACTIVE_WINDOW_H", "3")))
    return last is not None and (now_utc or utcnow()) - last < window
