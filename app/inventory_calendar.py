"""Calendario de inventario, «dónde está cada equipo» (Fase 10, 10-nov-2026): LÓGICA PURA, sin base de datos (se prueba sola).

Un evento ocupa su material desde el montaje (si lo hay y es anterior) hasta su fecha de fin; con una sola fecha ocupa ese día. Un evento sin fecha de inicio no se pinta en el calendario.
Solo cuenta lo ASIGNADO (lo que el evento pide); lo que ya salió y no ha vuelto de un evento finalizado se marca aparte como «pendiente de regresar».
"""
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

MAX_RANGE_DAYS = 100


class RangeError(ValueError):
    pass


def parse_day(raw) -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        raise RangeError("Las fechas deben venir como AAAA-MM-DD")


def clean_range(start, end) -> Tuple[date, date]:
    a, b = parse_day(start), parse_day(end)
    if b < a:
        raise RangeError("La fecha final es anterior a la inicial")
    if (b - a).days + 1 > MAX_RANGE_DAYS:
        raise RangeError(f"El rango es demasiado largo (máximo {MAX_RANGE_DAYS} días)")
    return a, b


def event_span(start: Optional[date], end: Optional[date], setup: Optional[date] = None) -> Optional[Tuple[date, date]]:
    """(primer día, último día) que el evento ocupa material, o None si no tiene fecha de inicio."""
    if start is None:
        return None
    first = min(start, setup) if setup else start
    last = max(end or start, start)
    return first, last


def overlaps(span: Optional[Tuple[date, date]], a: date, b: date) -> bool:
    return span is not None and span[0] <= b and span[1] >= a


def covers(span: Optional[Tuple[date, date]], day: date) -> bool:
    return span is not None and span[0] <= day <= span[1]


def days_between(a: date, b: date) -> List[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def usage_on(day: date, events: Iterable[dict]) -> Dict[int, int]:
    """Unidades asignadas por producto ese día. `events` = [{span, lines: {product_id: assigned}}]."""
    used: Dict[int, int] = {}
    for ev in events:
        if covers(ev.get("span"), day):
            for pid, qty in (ev.get("lines") or {}).items():
                if qty:
                    used[pid] = used.get(pid, 0) + int(qty)
    return used


def available(stock: Optional[int], used: int) -> Optional[int]:
    """Disponible = existencias - usado (puede ser negativo: falta material). None si no se controlan existencias."""
    return None if stock is None else int(stock) - int(used)


def pending_return(out: int, returned: int, consumed: int) -> int:
    return max(int(out or 0) - int(returned or 0) - int(consumed or 0), 0)
