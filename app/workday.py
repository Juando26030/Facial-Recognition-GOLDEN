"""Jornada del evento (Fase 5, decisión de Juan David del 8-nov-2026): campo INFORMATIVO calculado de la hora de inicio y la hora de fin del evento.

Función pura (sin base de datos ni FastAPI): `compute_workday(start, end)`. Espejo en el navegador: static/js/workday.js (mismas constantes y mismos límites; lo fija tests/js/workday_check.js).

Qué se mide: la duración del DÍA DE TRABAJO = hora fin - hora inicio. Las fechas no cuentan: un evento de varios días tiene la misma jornada cada día. Si la hora de fin es menor que la
de inicio, el día cruza la medianoche (ej. 22:00 -> 04:00 = 6 h). Si falta alguna hora, o son iguales (no se puede saber si son 0 h o 24 h), no hay jornada: se muestra «—».

Límites (SUPERIOR INCLUSIVO; el inferior de cada tramo es el superior del anterior, exclusivo):
    0   <  h <=  6    ->  'media'       Media jornada
    6   <  h <=  9    ->  'intermedia'  Jornada intermedia (entre media y completa)
    9   <  h <= 12    ->  'completa'    Jornada completa
    12  <  h          ->  'extendida'   Jornada extendida
Así 6 h exactas son media jornada, 9 h exactas intermedia y 12 h exactas completa; 6 h 01 min ya es intermedia."""
import re
from datetime import time

MEDIA_MAX_H = 6
INTERMEDIA_MAX_H = 9
COMPLETA_MAX_H = 12

# (clave estable, tope superior inclusivo en horas o None = sin tope, etiqueta). El orden importa.
TIERS = (
    ("media", MEDIA_MAX_H, "Media jornada"),
    ("intermedia", INTERMEDIA_MAX_H, "Jornada intermedia (entre media y completa)"),
    ("completa", COMPLETA_MAX_H, "Jornada completa"),
    ("extendida", None, "Jornada extendida"),
)
KEYS = tuple(t[0] for t in TIERS)
LABELS = {k: lab for k, _, lab in TIERS}
NO_VALUE = "—"

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")


def parse_minutes(value):
    """'HH:MM' (también 'H:MM' o 'HH:MM:SS') o `datetime.time` -> minutos desde las 00:00; None si no es una hora válida (vacío, 24:00, 12:60, texto)."""
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if not isinstance(value, str):
        return None
    m = _TIME_RE.match(value)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def classify(hours: float) -> str:
    """Clave de la jornada para una duración en horas (> 0)."""
    for key, top, _ in TIERS:
        if top is None or hours <= top:
            return key
    return TIERS[-1][0]          # inalcanzable: el último tramo no tiene tope


def compute_workday(start, end):
    """Jornada de un evento a partir de sus horas. Devuelve None si no se puede calcular (falta una hora, hora inválida o inicio == fin); si no,
    {"key": 'media'|'intermedia'|'completa'|'extendida', "label": str, "hours": float (decimal, 2 cifras), "hours_text": '10 h' | '8,5 h'}."""
    a, b = parse_minutes(start), parse_minutes(end)
    if a is None or b is None or a == b:
        return None
    minutes = (b - a) % (24 * 60)          # fin menor que inicio = cruza la medianoche
    hours = minutes / 60
    return {"key": classify(hours), "label": LABELS[classify(hours)], "hours": round(hours, 2), "hours_text": hours_text(hours)}


def hours_text(hours: float) -> str:
    """Horas decimales con coma y sin ceros de sobra: '10 h', '8,5 h', '8,25 h'."""
    r = round(hours, 2)
    s = str(int(r)) if r == int(r) else f"{r:.2f}".rstrip("0").replace(".", ",")
    return s + " h"


def event_workday(event):
    """Jornada de un `Event` (o cualquier objeto con event_time_start / event_time_end)."""
    return compute_workday(getattr(event, "event_time_start", None), getattr(event, "event_time_end", None))


def serialize(event) -> dict:
    """Los campos planos que viajan en la respuesta del evento: workday_key / workday_label / workday_hours (None si no hay jornada)."""
    w = event_workday(event)
    return {"workday_key": w["key"] if w else None, "workday_label": w["label"] if w else None, "workday_hours": w["hours"] if w else None}
