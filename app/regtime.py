"""Fase 1A, PR1: medición del tiempo por registro (`access_logs.took_ms` / `ui_flow`, migración 0079).

El quiosco mide cuántos milisegundos pasan desde la primera tecla en el buscador (o la apertura del formulario de alta) hasta que manda el registro y lo envía junto con la petición
(`took_ms`, `ui_flow`). El servidor NO se fía: acota el valor (0..600000 ms) y, si no es válido o no viene (clientes viejos con el JS en caché), lo ignora y registra igual. Nada de esto lleva
cédula ni nombre de asistentes: son solo duraciones. El reporte (`GET /api/events/{id}/timing-report`) agrega p50/p90 por flujo y por digitador. Módulo aparte de `app/timing.py` (ese es el diagnóstico de esperas del servidor).
"""
import math
import re
from typing import Any, Optional

TOOK_MS_MAX = 600_000                      # 10 min: más que esto es una pestaña olvidada, no un registro
UI_FLOW_RE = re.compile(r"^[a-z0-9_]{1,12}$")
MIN_SAMPLE = 5                             # con menos registros medidos por grupo el reporte lo marca como «muestra pequeña»


def clean_took_ms(value: Any) -> Optional[int]:
    """Entero 0..600000 o None. Acepta int/float/texto numérico («1234», «1234.6»); rechaza booleanos, NaN, infinitos, negativos, vacíos y todo lo demás."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or len(value) > 16:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    ms = int(round(value))
    return ms if 0 <= ms <= TOOK_MS_MAX else None


def clean_ui_flow(value: Any) -> Optional[str]:
    """Etiqueta corta de la pantalla («v0», «1a», …): minúsculas, números y guion bajo, hasta 12; otra cosa se ignora."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if UI_FLOW_RE.match(v) else None


def measured(value_took: Any, value_flow: Any) -> dict:
    """Los dos campos ya limpios, listos para `AccessLog(**measured(...))`. Si no hay tiempo válido tampoco se guarda la etiqueta (una etiqueta sola no mide nada)."""
    ms = clean_took_ms(value_took)
    return {"took_ms": ms, "ui_flow": clean_ui_flow(value_flow) if ms is not None else None}


def percentile(sorted_values: list, p: float) -> Optional[int]:
    """Percentil `p` (0..100) por interpolación lineal sobre una lista YA ordenada; None si está vacía."""
    n = len(sorted_values)
    if not n:
        return None
    if n == 1:
        return int(sorted_values[0])
    k = (n - 1) * p / 100.0
    lo = int(math.floor(k))
    hi = min(lo + 1, n - 1)
    return int(round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)))


def summarize(values: list) -> dict:
    """{n, p50_ms, p90_ms, small_sample}. `values` sin ordenar."""
    vs = sorted(int(v) for v in values)
    return {"n": len(vs), "p50_ms": percentile(vs, 50), "p90_ms": percentile(vs, 90), "small_sample": len(vs) < MIN_SAMPLE}


def build_report(rows: list, staff_names: dict) -> dict:
    """`rows`: [(registered_by_staff_id, ui_flow, took_ms, record_type)] de UN evento. `staff_names`: {staff_id: nombre para mostrar}. Devuelve solo agregados (sin cédulas ni nombres de asistentes)."""
    regs = [r for r in rows if r[3] != "Actualizado"]
    timed = [r for r in regs if r[2] is not None]
    by_flow, by_staff, totals_by_staff = {}, {}, {}
    for staff_id, flow, ms, _kind in timed:
        by_flow.setdefault(flow or "sin_etiqueta", []).append(ms)
        by_staff.setdefault(staff_id, []).append(ms)
    for staff_id, _flow, _ms, _kind in regs:
        totals_by_staff[staff_id] = totals_by_staff.get(staff_id, 0) + 1
    staff_rows = [
        {"staff_id": sid, "name": staff_names.get(sid) or (f"Digitador {sid}" if sid is not None else "Sin digitador"), "registrations": totals_by_staff.get(sid, 0), **summarize(v)}
        for sid, v in by_staff.items()
    ]
    return {
        "registrations": len(regs),
        "measured": len(timed),
        "coverage_pct": round(100 * len(timed) / len(regs), 1) if regs else None,
        "overall": summarize([r[2] for r in timed]),
        "by_flow": [{"ui_flow": f, **summarize(v)} for f, v in sorted(by_flow.items())],
        "by_staff": sorted(staff_rows, key=lambda x: (-x["n"], x["staff_id"] or 0)),
        "note": "p50/p90 = mediana y percentil 90 del tiempo desde la primera tecla hasta enviar el registro (sin contar la respuesta del servidor). Solo registros medidos; los anteriores a esta medición y los de clientes viejos no cuentan.",
    }
