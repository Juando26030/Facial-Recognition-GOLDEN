"""Módulo de analítica compartido (Sprint 5): construye "tableros" (KPIs + gráficos) con el MISMO formato para cualquier
fuente de datos — hoy el Registro del evento; el paso siguiente, las respuestas de un Formulario Web. El navegador los
dibuja con un solo componente (`static/js/analytics-dashboard.js`), así una mejora sirve a las dos fuentes.

Formato de un tablero (JSON):
  {"title": str, "generated_at": iso, "kpis": [{"label", "value", "hint", "tone"}],
   "charts": [{"id", "title", "type": "line|bar|pie", "labels": [...], "datasets": [{"label", "data": [...]}],
               "stacked": bool, "horizontal": bool, "note": str}]}

Las fuentes solo entregan datos (marcas de tiempo, categorías, valores); todo el armado (cubetas de tiempo, conteos,
porcentajes, redondeos, hora local) vive aquí una sola vez.
"""
from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.timeutil import to_local

_TIME_BUCKETS_MIN = (5, 15, 30, 60, 180, 360, 1440)   # ancho de cubeta (min) que se elige según la duración total
_MAX_POINTS = 60


def kpi(label: str, value, hint: str = "", tone: str = "") -> dict:
    return {"label": label, "value": value, "hint": hint, "tone": tone}


def chart(chart_id: str, title: str, kind: str, labels: list, datasets: list, stacked=False, horizontal=False, note="") -> dict:
    return {"id": chart_id, "title": title, "type": kind, "labels": labels, "datasets": datasets, "stacked": stacked, "horizontal": horizontal, "note": note}


def dashboard(title: str, kpis: list, charts: list) -> dict:
    return {"title": title, "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "kpis": kpis, "charts": charts}


def pct(part: int, total: int) -> str:
    return f"{(100 * part / total):.0f}%" if total else "0%"


def fmt_local(dt: Optional[datetime]) -> str:
    return to_local(dt).strftime("%d/%m %H:%M") if dt else "—"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min {seconds % 60:02d} s"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def counter_chart(chart_id: str, title: str, values: Iterable, kind="bar", top: int = 10, label="Personas", other_label="Otros") -> Optional[dict]:
    """Conteo por categoría; más de `top` categorías se agrupan en «Otros» para que siga siendo legible."""
    counts = Counter(v for v in values if v not in (None, ""))
    if not counts:
        return None
    ordered = counts.most_common()
    head, tail = ordered[:top], ordered[top:]
    labels, data = [k for k, _ in head], [n for _, n in head]
    if tail:
        labels.append(other_label)
        data.append(sum(n for _, n in tail))
    return chart(chart_id, title, kind, labels, [{"label": label, "data": data}])


def time_series(chart_id: str, title: str, timestamps: list, label="Registros") -> Optional[dict]:
    """Eventos en el tiempo (hora local): conteo por cubeta y acumulado. La cubeta se elige sola según la duración."""
    times = sorted(to_local(t) for t in timestamps if t)
    if not times:
        return None
    span_min = max(1, (times[-1] - times[0]).total_seconds() / 60)
    width = next((w for w in _TIME_BUCKETS_MIN if span_min / w <= _MAX_POINTS), _TIME_BUCKETS_MIN[-1])
    start = times[0].replace(second=0, microsecond=0)
    if width >= 60:
        start = start.replace(minute=0)
    elif width > 1:
        start = start.replace(minute=(start.minute // width) * width)
    n_buckets = int((times[-1] - start).total_seconds() // (width * 60)) + 1
    counts = [0] * n_buckets
    for t in times:
        counts[int((t - start).total_seconds() // (width * 60))] += 1
    labels = []
    for i in range(n_buckets):
        at = start + timedelta(minutes=i * width)
        labels.append(at.strftime("%d/%m %H:%M") if span_min > 1440 else at.strftime("%H:%M"))
    cumulative, running = [], 0
    for c in counts:
        running += c
        cumulative.append(running)
    return chart(chart_id, title, "line", labels, [{"label": f"{label} por {_fmt_width(width)}", "data": counts}, {"label": "Acumulado", "data": cumulative}])


def _fmt_width(width: int) -> str:
    return f"{width} min" if width < 60 else (f"{width // 60} h" if width < 1440 else "día")


def hour_histogram(chart_id: str, title: str, timestamps: list, label="Registros") -> Optional[dict]:
    hours = Counter(to_local(t).hour for t in timestamps if t)
    if not hours:
        return None
    lo, hi = min(hours), max(hours)
    labels = [f"{h:02d}:00" for h in range(lo, hi + 1)]
    return chart(chart_id, title, "bar", labels, [{"label": label, "data": [hours.get(h, 0) for h in range(lo, hi + 1)]}])


def peak_hour(timestamps: list) -> Optional[str]:
    hours = Counter(to_local(t).hour for t in timestamps if t)
    if not hours:
        return None
    h, n = hours.most_common(1)[0]
    return f"{h:02d}:00–{h:02d}:59 ({n})"


def progress_by_group(chart_id: str, title: str, groups: dict, top: int = 10, horizontal=True) -> Optional[dict]:
    """`groups`: {nombre: (hechos, pendientes)} -> barras apiladas hechos/pendientes, ordenadas por tamaño."""
    if not groups:
        return None
    ordered = sorted(groups.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:top]
    return chart(chart_id, title, "bar", [k for k, _ in ordered],
                 [{"label": "Registrados", "data": [v[0] for _, v in ordered]}, {"label": "Pendientes", "data": [v[1] for _, v in ordered]}],
                 stacked=True, horizontal=horizontal)
