"""Tiempo de permanencia en las zonas (Fase 10, pedido del 10-nov-2026): LÓGICA PURA, sin base de datos (se prueba sola).

Cada entrada («in») y salida («out») de una persona a una zona se empareja y los tiempos se SUMAN: 10 min + 5 min = 15 min. Reglas:
- Una entrada sin salida sigue «abierta»: cuenta hasta el límite que se le pase (el fin del evento o ahora, lo que ocurra primero) y se marca para que el coordinador la vea.
- Una entrada repetida (sin haber salido) o una salida sin entrada no suman nada.
- Si la persona tiene tramos que se cruzan (olvidó escanear la salida de una zona y entró a otra) el tiempo común se cuenta UNA sola vez.
- La referencia (el 100 %) la define el coordinador en minutos; si no la puso, se usa la duración del evento (fecha y hora de inicio a fin) cuando se puede calcular.
Las horas llegan en UTC (naive), como se guardan.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_THRESHOLD_PCT = 80
MAX_REFERENCE_MINUTES = 60 * 24 * 60      # 60 días: tope razonable para evitar un número escrito por error
PCT_STEPS = (50, 60, 70, 80, 90, 100)


class DwellError(ValueError):
    """Dato inválido de la configuración (el mensaje se muestra tal cual)."""


@dataclass(frozen=True)
class Move:
    user_id: str
    area_id: int
    direction: str          # 'in' | 'out'
    at: datetime            # UTC naive


@dataclass
class Dwell:
    seconds: int = 0
    entries: int = 0
    open: bool = False      # tiene una entrada sin salida
    first_in: Optional[datetime] = None
    last_out: Optional[datetime] = None


def clean_reference_minutes(raw) -> Optional[int]:
    """Minutos de referencia (el 100 %). Vacío/None = sin definir. Debe ser un entero de 1 en adelante."""
    if raw in (None, ""):
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise DwellError("El tiempo de referencia debe ser un número de minutos")
    if n < 1:
        raise DwellError("El tiempo de referencia debe ser de 1 minuto o más")
    if n > MAX_REFERENCE_MINUTES:
        raise DwellError("El tiempo de referencia es demasiado largo (máximo 60 días)")
    return n


def clean_threshold_pct(raw) -> int:
    """Porcentaje mínimo para cumplir (1 a 100). Vacío = 80."""
    if raw in (None, ""):
        return DEFAULT_THRESHOLD_PCT
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        raise DwellError("El porcentaje debe ser un número entre 1 y 100")
    if n < 1 or n > 100:
        raise DwellError("El porcentaje debe estar entre 1 y 100")
    return n


def _parse_hhmm(text) -> Optional[Tuple[int, int]]:
    try:
        h, m = str(text).strip().split(":")[:2]
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def event_window_local(start: Optional[date], end: Optional[date], t_start, t_end) -> Optional[Tuple[datetime, datetime]]:
    """Inicio y fin del evento en hora LOCAL (naive), o None si faltan datos. Sin horas: de las 00:00 del primer día a las 23:59 del último."""
    if start is None:
        return None
    last = end or start
    s = _parse_hhmm(t_start) or (0, 0)
    e = _parse_hhmm(t_end) or (23, 59)
    a = datetime(start.year, start.month, start.day, s[0], s[1])
    b = datetime(last.year, last.month, last.day, e[0], e[1])
    return (a, b) if b > a else None


def window_minutes(window: Optional[Tuple[datetime, datetime]]) -> Optional[int]:
    if not window:
        return None
    return max(int((window[1] - window[0]).total_seconds() // 60), 1)


def reference_for(configured: Optional[int], window: Optional[Tuple[datetime, datetime]]) -> Optional[int]:
    """Lo que definió el coordinador; si no, la duración del evento; si tampoco se puede, None."""
    return configured if configured else window_minutes(window)


def _merge(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    out: List[Tuple[datetime, datetime]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def compute(moves: Iterable[Move], cap: Optional[datetime]) -> Dict[str, Dwell]:
    """Tiempo acumulado por persona. `cap` = hasta cuándo cuenta una entrada abierta (None = esa entrada no suma, solo queda marcada)."""
    by_pair: Dict[Tuple[str, int], List[Move]] = {}
    for m in moves:
        by_pair.setdefault((m.user_id, m.area_id), []).append(m)
    spans: Dict[str, List[Tuple[datetime, datetime]]] = {}
    info: Dict[str, Dwell] = {}
    for (uid, _area), seq in by_pair.items():
        d = info.setdefault(uid, Dwell())
        opened: Optional[datetime] = None
        for m in sorted(seq, key=lambda x: x.at):
            if m.direction == "in":
                if opened is None:
                    opened = m.at
                    d.entries += 1
                    if d.first_in is None or m.at < d.first_in:
                        d.first_in = m.at
            elif m.direction == "out" and opened is not None:
                if m.at > opened:
                    spans.setdefault(uid, []).append((opened, m.at))
                if d.last_out is None or m.at > d.last_out:
                    d.last_out = m.at
                opened = None
        if opened is not None:
            d.open = True
            if cap is not None and cap > opened:
                spans.setdefault(uid, []).append((opened, cap))
    for uid, d in info.items():
        d.seconds = int(sum((b - a).total_seconds() for a, b in _merge(spans.get(uid, []))))
    return info


def percent(seconds: int, reference_minutes: Optional[int]) -> Optional[float]:
    """Porcentaje de la referencia (1 decimal; sin tope: quien se quedó más que la referencia pasa del 100). None si no hay referencia."""
    if not reference_minutes:
        return None
    return round(seconds * 100.0 / (reference_minutes * 60), 1)


def meets(seconds: int, reference_minutes: Optional[int], threshold_pct: int) -> bool:
    """Comparación exacta en segundos (sin el redondeo del porcentaje mostrado)."""
    if not reference_minutes:
        return False
    return seconds * 100 >= threshold_pct * reference_minutes * 60


def format_minutes(seconds: int) -> str:
    """«2 h 05 min» / «45 min» / «0 min»."""
    mins = int(seconds // 60)
    h, m = divmod(mins, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def summarize(rows: List[dict], reference_minutes: Optional[int], threshold_pct: int) -> dict:
    """Resumen para el panel. `rows` = [{seconds, ...}] (sin la persona de prueba). Cuántas personas llegan a cada porcentaje y cuántas cumplen el pedido."""
    total = len(rows)
    steps = {str(p): sum(1 for r in rows if meets(r["seconds"], reference_minutes, p)) for p in PCT_STEPS}
    return {
        "people": total,
        "reference_minutes": reference_minutes,
        "threshold_pct": threshold_pct,
        "qualifying": sum(1 for r in rows if meets(r["seconds"], reference_minutes, threshold_pct)),
        "with_open_entry": sum(1 for r in rows if r.get("open")),
        "steps": steps,
    }


def cap_for(window_end_utc: Optional[datetime], now: datetime) -> datetime:
    """Hasta cuándo cuenta una entrada abierta: el fin del evento si ya pasó; si no, ahora."""
    if window_end_utc is not None and window_end_utc < now:
        return window_end_utc
    return now

