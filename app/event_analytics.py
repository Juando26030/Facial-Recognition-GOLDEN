"""Análisis de eventos para gerencia (Fase 9, pieza D): satisfacción de los clientes y tiempos de cierre/facturación. Módulo PURO: no toca la base ni la hora del sistema; recibe filas ya leídas
(diccionarios) y devuelve números. La parte que lee la base y arma el JSON está en app/routers/gastos_eventos.py. Fórmulas documentadas en docs/FASE_9_PLATAFORMA.md (sección D).

Convenciones:
  * Calidad: puntaje 1-3 (Malo=1, Bueno=2, Excelente=3). Recomendación: 0-10. NPS = %promotores (9-10) − %detractores (0-6), de −100 a 100 (se redondea a entero).
  * Duraciones en DÍAS (decimales), nunca negativas: una fecha faltante o un orden raro (p. ej. facturado antes de finalizar por datos viejos) no cuenta en el promedio, no lo rompe.
  * Sin datos personales: solo eventos, clientes y cuentas del personal."""
from datetime import datetime
from typing import Iterable, Optional

LOW_SCORE_DEFAULT = 1.8          # promedio de calidad (1-3) igual o menor = «baja satisfacción»
NPS_DETRACTOR_MAX = 6
OVERDUE_DAYS_DEFAULT = 30        # días desde Finalizado sin pasar a Facturado
SURVEY_WAIT_DAYS_DEFAULT = 7     # días desde Facturado sin que el cliente conteste la encuesta
DECLINE_MIN = 0.3                # caída del promedio entre las dos últimas encuestas de un cliente

QUESTION_LABELS = {
    "q1_experience": "Experiencia con el servicio de registro",
    "q2_staff": "Presentación y atención del personal del registro",
    "q3_coordinator": "Atención del Coordinador",
    "q4_commercial": "Atención del Comercial",
    "q5_speed": "Agilidad y tiempos de espera",
    "q6_badges": "Calidad de las escarapelas",
    "q7_nps": "Probabilidad de recomendar (0-10)",
    "q8_next_event": "¿Tiene un próximo evento?",
}


# ------------------------------------------------------------------ estadística básica
def mean(values: Iterable) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def percentile(values: Iterable, p: float) -> Optional[float]:
    """Percentil por interpolación lineal (p de 0 a 100). Vacío -> None."""
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * max(0.0, min(100.0, p)) / 100.0
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def median(values: Iterable) -> Optional[float]:
    return percentile(values, 50)


def rnd(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def stats(values: Iterable) -> dict:
    """Resumen de una lista de duraciones/números: n, promedio, mediana y percentil 90."""
    vals = [float(v) for v in values if v is not None]
    return {"n": len(vals), "mean": rnd(mean(vals)), "median": rnd(median(vals)), "p90": rnd(percentile(vals, 90))}


def days_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    """Días entre dos momentos (UTC sin zona). None si falta alguno o si `end` es anterior a `start`."""
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() / 86400.0
    return delta if delta >= 0 else None


def month_key(moment: Optional[datetime]) -> Optional[str]:
    return moment.strftime("%Y-%m") if moment is not None else None


# ------------------------------------------------------------------ satisfacción
def nps(scores: Iterable) -> dict:
    """NPS de una lista de puntajes 0-10. `value` es None si no hay respuestas."""
    vals = [int(s) for s in scores if s is not None and 0 <= int(s) <= 10]
    total = len(vals)
    promoters = sum(1 for s in vals if s >= 9)
    detractors = sum(1 for s in vals if s <= NPS_DETRACTOR_MAX)
    passives = total - promoters - detractors
    value = round((promoters - detractors) * 100.0 / total) if total else None
    return {"total": total, "promoters": promoters, "passives": passives, "detractors": detractors, "value": value}


def question_averages(answers: Iterable) -> list:
    """Promedio por pregunta de calidad (1-3) y distribución Malo/Bueno/Excelente. `answers`: dicts con question_id y score."""
    by_q: dict = {}
    for a in answers:
        qid = a.get("question_id")
        score = a.get("score")
        if qid is None or score is None or qid in ("q7_nps", "q8_next_event"):
            continue
        by_q.setdefault(qid, []).append(int(score))
    out = []
    for qid in sorted(by_q):
        vals = by_q[qid]
        out.append({"question_id": qid, "label": QUESTION_LABELS.get(qid, qid), "n": len(vals), "avg": rnd(mean(vals), 2),
                    "bad": sum(1 for v in vals if v == 1), "good": sum(1 for v in vals if v == 2), "excellent": sum(1 for v in vals if v == 3)})
    return out


def nps_distribution(scores: Iterable) -> list:
    """Cuántas respuestas hubo en cada puntaje 0..10 (siempre 11 posiciones)."""
    counts = [0] * 11
    for s in scores:
        if s is not None and 0 <= int(s) <= 10:
            counts[int(s)] += 1
    return counts


def next_event_interest(answers: Iterable) -> dict:
    """Respuestas a «¿próximo evento?»: cuántos dijeron Sí / No y el porcentaje de Sí sobre quienes contestaron."""
    yes = no = 0
    for a in answers:
        if a.get("question_id") != "q8_next_event":
            continue
        text = (a.get("choice_text") or "").strip().lower()
        if text in ("sí", "si"):
            yes += 1
        elif text == "no":
            no += 1
    total = yes + no
    return {"yes": yes, "no": no, "answered": total, "pct_yes": rnd(yes * 100.0 / total) if total else None}


def survey_row_summary(survey: dict) -> dict:
    return {"avg_score": survey.get("avg_score"), "nps_score": survey.get("nps_score")}


def group_satisfaction(events: list, key: str, name_key: Optional[str] = None) -> list:
    """Satisfacción agrupada por `key` (p. ej. 'commercial_id', 'tenant_id', 'city'). Cada evento trae avg_score y nps_score de su encuesta (o None). Ordena de mejor a peor promedio."""
    groups: dict = {}
    for e in events:
        if e.get("survey") is None:
            continue
        k = e.get(key)
        g = groups.setdefault(k, {"key": k, "name": e.get(name_key) if name_key else k, "avgs": [], "nps": []})
        if e["survey"].get("avg_score") is not None:
            g["avgs"].append(e["survey"]["avg_score"])
        if e["survey"].get("nps_score") is not None:
            g["nps"].append(e["survey"]["nps_score"])
    out = []
    for g in groups.values():
        out.append({"key": g["key"], "name": g["name"] or "(sin asignar)", "events": max(len(g["avgs"]), len(g["nps"])), "avg": rnd(mean(g["avgs"]), 2), "nps": nps(g["nps"])["value"]})
    out.sort(key=lambda r: (r["avg"] is None, -(r["avg"] or 0), r["name"] or ""))
    return out


def monthly_satisfaction(events: list) -> list:
    """Evolución por mes de la encuesta (mes = cuando se contestó): promedio de calidad, NPS y cuántas respuestas."""
    months: dict = {}
    for e in events:
        s = e.get("survey")
        if not s or not s.get("submitted_at"):
            continue
        m = months.setdefault(month_key(s["submitted_at"]), {"avgs": [], "nps": []})
        if s.get("avg_score") is not None:
            m["avgs"].append(s["avg_score"])
        if s.get("nps_score") is not None:
            m["nps"].append(s["nps_score"])
    return [{"month": k, "responses": max(len(v["avgs"]), len(v["nps"])), "avg": rnd(mean(v["avgs"]), 2), "nps": nps(v["nps"])["value"]} for k, v in sorted(months.items())]


def ranking(events: list, best: bool = True, limit: int = 5) -> list:
    """Eventos mejor o peor evaluados por promedio de calidad (desempata por recomendación)."""
    rated = [e for e in events if e.get("survey") and e["survey"].get("avg_score") is not None]
    rated.sort(key=lambda e: (e["survey"]["avg_score"], e["survey"].get("nps_score") if e["survey"].get("nps_score") is not None else -1), reverse=best)
    return [{"event_id": e["id"], "name": e["name"], "client": e.get("tenant_name"), "avg": rnd(e["survey"]["avg_score"], 2), "nps_score": e["survey"].get("nps_score")} for e in rated[:limit]]


# ------------------------------------------------------------------ tiempos
def event_times(e: dict) -> dict:
    """Duraciones (días) de UN evento. Claves de entrada: end_at (fin del evento), finalized_at, final_db_at, billed_at, created_at."""
    return {
        "close_days": days_between(e.get("end_at"), e.get("finalized_at")),            # fin del evento -> Finalizado
        "base_days": days_between(e.get("end_at"), e.get("final_db_at")),              # fin del evento -> base final subida
        "bill_after_final_days": days_between(e.get("finalized_at"), e.get("billed_at")),      # Finalizado -> Facturado
        "bill_after_end_days": days_between(e.get("end_at"), e.get("billed_at")),      # fin del evento -> Facturado
    }


def time_summary(events: list) -> dict:
    keys = ("close_days", "base_days", "bill_after_final_days", "bill_after_end_days")
    times = [event_times(e) for e in events]
    return {k: stats(t[k] for t in times) for k in keys}


def monthly_times(events: list) -> list:
    """Por mes (del fin del evento): promedio de días para cerrar y para facturar."""
    months: dict = {}
    for e in events:
        key = month_key(e.get("end_at"))
        if key is None:
            continue
        t = event_times(e)
        m = months.setdefault(key, {"close": [], "bill": [], "events": 0})
        m["events"] += 1
        if t["close_days"] is not None:
            m["close"].append(t["close_days"])
        if t["bill_after_end_days"] is not None:
            m["bill"].append(t["bill_after_end_days"])
    return [{"month": k, "events": v["events"], "close": stats(v["close"]), "bill": stats(v["bill"])} for k, v in sorted(months.items())]


def group_times(events: list, key: str, name_key: Optional[str] = None) -> list:
    groups: dict = {}
    for e in events:
        g = groups.setdefault(e.get(key), {"name": e.get(name_key) if name_key else e.get(key), "rows": []})
        g["rows"].append(e)
    out = []
    for k, g in groups.items():
        ts = time_summary(g["rows"])
        out.append({"key": k, "name": g["name"] or "(sin asignar)", "events": len(g["rows"]), "close": ts["close_days"], "bill": ts["bill_after_end_days"]})
    out.sort(key=lambda r: (r["bill"]["median"] is None, -(r["bill"]["median"] or 0)))
    return out


# ------------------------------------------------------------------ alertas y atrasos
def overdue_events(events: list, now: datetime, days: int = OVERDUE_DAYS_DEFAULT) -> list:
    """Eventos finalizados que siguen sin facturar después de `days` días desde que pasaron a Finalizado. Los más atrasados primero."""
    out = []
    for e in events:
        fin = e.get("finalized_at")
        if fin is None or e.get("billed_at") is not None:
            continue
        waited = days_between(fin, now)
        if waited is not None and waited > days:
            out.append({"event_id": e["id"], "name": e["name"], "client": e.get("tenant_name"), "commercial": e.get("commercial_name"), "days_waiting": round(waited),
                        "final_db": bool(e.get("final_db_at"))})
    out.sort(key=lambda r: -r["days_waiting"])
    return out


def pending_surveys(events: list, now: datetime, wait_days: int = SURVEY_WAIT_DAYS_DEFAULT) -> list:
    """Eventos Facturados hace más de `wait_days` días cuyo cliente aún no contestó la encuesta."""
    out = []
    for e in events:
        billed = e.get("billed_at")
        if billed is None or e.get("survey") is not None:
            continue
        waited = days_between(billed, now)
        if waited is not None and waited > wait_days:
            out.append({"event_id": e["id"], "name": e["name"], "client": e.get("tenant_name"), "commercial": e.get("commercial_name"), "days_waiting": round(waited),
                        "link_opened": bool(e.get("delivery_opened"))})
    out.sort(key=lambda r: -r["days_waiting"])
    return out


def low_satisfaction(events: list, threshold: float = LOW_SCORE_DEFAULT) -> list:
    """Eventos con promedio de calidad igual o menor al umbral, o con recomendación de detractor (0-6)."""
    out = []
    for e in events:
        s = e.get("survey")
        if not s:
            continue
        low_avg = s.get("avg_score") is not None and s["avg_score"] <= threshold
        detractor = s.get("nps_score") is not None and s["nps_score"] <= NPS_DETRACTOR_MAX
        if low_avg or detractor:
            out.append({"event_id": e["id"], "name": e["name"], "client": e.get("tenant_name"), "avg": rnd(s.get("avg_score"), 2), "nps_score": s.get("nps_score"),
                        "reason": "calidad baja" if low_avg else "no recomendaría"})
    out.sort(key=lambda r: (r["avg"] is None, r["avg"] or 0))
    return out


def declining_clients(events: list, min_drop: float = DECLINE_MIN) -> list:
    """Clientes cuya última encuesta quedó por debajo de la anterior al menos `min_drop` puntos (necesita 2 o más encuestas con promedio)."""
    by_client: dict = {}
    for e in events:
        s = e.get("survey")
        if s and s.get("avg_score") is not None and s.get("submitted_at"):
            by_client.setdefault(e.get("tenant_id"), {"name": e.get("tenant_name"), "rows": []})["rows"].append((s["submitted_at"], s["avg_score"], e["name"]))
    out = []
    for tid, g in by_client.items():
        rows = sorted(g["rows"])
        if len(rows) < 2:
            continue
        prev, last = rows[-2], rows[-1]
        drop = prev[1] - last[1]
        if drop >= min_drop:
            out.append({"tenant_id": tid, "client": g["name"], "previous_avg": rnd(prev[1], 2), "last_avg": rnd(last[1], 2), "drop": rnd(drop, 2), "last_event": last[2]})
    out.sort(key=lambda r: -r["drop"])
    return out


def converted_next_event(surveys_yes: list, event_creations: dict) -> dict:
    """De quienes dijeron «Sí, tengo próximo evento», cuántos YA tienen un evento nuevo. `surveys_yes`: [{tenant_id, submitted_at}]; `event_creations`: {tenant_id: [created_at, ...]}.
    Un «Sí» cuenta como convertido si el mismo cliente creó un evento después de contestar."""
    converted = 0
    for s in surveys_yes:
        if any(c > s["submitted_at"] for c in event_creations.get(s["tenant_id"], [])):
            converted += 1
    total = len(surveys_yes)
    return {"interested": total, "converted": converted, "pct": rnd(converted * 100.0 / total) if total else None}


# ------------------------------------------------------------------ resumen en lenguaje claro
def plain_summary(*, month_label: str, nps_value: Optional[int], billed_count: int, bill_days_mean: Optional[float], responses: int) -> str:
    parts = []
    parts.append(f"NPS {nps_value:+d}" if nps_value is not None else "sin NPS todavía")
    parts.append(f"{responses} encuesta{'s' if responses != 1 else ''} respondida{'s' if responses != 1 else ''}")
    parts.append(f"{billed_count} evento{'s' if billed_count != 1 else ''} facturado{'s' if billed_count != 1 else ''}")
    if bill_days_mean is not None:
        parts.append(f"tiempo promedio de facturación {bill_days_mean:g} días")
    return f"{month_label}: " + ", ".join(parts) + "."
