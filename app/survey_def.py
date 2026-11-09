"""Definición VERSIONADA de la encuesta de satisfacción de la entrega al cliente (Fase 5). Son DATOS, no esquema: para cambiar las preguntas se edita esta lista y se sube `SURVEY_VERSION`;
cada respuesta guarda la versión con la que se contestó, así las respuestas viejas siguen siendo interpretables (el `id` de una pregunta es estable y no se reutiliza para otra cosa).

Textos LITERALES de la hoja «Encuestra de Satisfacción GEYL» (Golden). Puntaje (documentado, estable):
  * Preguntas de calidad (tipo `rating`): Malo/Mala/Malos = 1 · Bueno/Buena/Buenos = 2 · Excelente/Excelentes = 3. La etiqueta se guarda tal cual la vio la persona (`choice_text`) y el puntaje
    aparte (`score`), para poder promediar. «No aplica» (solo `allow_na`) no tiene puntaje (NULL) y no entra en ningún promedio.
  * Pregunta de recomendación (tipo `nps`): 0 a 10; el puntaje ES el número. NPS = %promotores (9-10) - %detractores (0-6).
  * Pregunta opcional (tipo `optional`): sin puntaje; solo `choice_text` («Sí»/«No», opcional) y comentario.
Sin datos personales de quien responde: la encuesta no pide nombre, cédula ni correo."""
from typing import Optional

SURVEY_VERSION = 1

RATING_SCORES = {"bad": 1, "good": 2, "excellent": 3}
RATING_MAX = 3


def _rating(qid: str, number: int, text: str, labels: tuple, *, allow_na: bool = False) -> dict:
    return {"id": qid, "number": number, "type": "rating", "text": text, "allow_na": allow_na, "comment": True, "required": not allow_na,
            "options": [{"key": key, "label": label, "score": RATING_SCORES[key]} for key, label in zip(("bad", "good", "excellent"), labels)]}


QUESTIONS = [
    _rating("q1_experience", 1, "Su experiencia con el servicio prestado en el registro del evento fue:", ("Malo", "Bueno", "Excelente")),
    _rating("q2_staff", 2, "La presentación y atención del personal del registro fue:", ("Mala", "Buena", "Excelente")),
    _rating("q3_coordinator", 3, "La presentación y atención del Coordinador fue:", ("Mala", "Buena", "Excelente")),
    _rating("q4_commercial", 4, "La atención y servicio al cliente del Comercial fue:", ("Mala", "Buena", "Excelente")),
    _rating("q5_speed", 5, "La agilidad del registro y los tiempos de espera fueron:", ("Malos", "Buenos", "Excelentes")),
    _rating("q6_badges", 6, "La calidad de las escarapelas o credenciales y la exactitud de sus datos fue (solo al ser suministradas por Golden):", ("Mala", "Buena", "Excelente"), allow_na=True),
    {"id": "q7_nps", "number": 7, "type": "nps", "required": True, "comment": True, "min": 0, "max": 10, "low_label": "Nada probable", "high_label": "Muy probable",
     "text": "¿Qué tan probable es que recomiende nuestro servicio de registro a otra empresa? (0 = Nada probable, 10 = Muy probable)"},
    {"id": "q8_next_event", "number": 8, "type": "optional", "required": False, "comment": True, "choices": ["Sí", "No"],
     "text": "¿Tienes próximamente un evento? Prográmalo con nosotros y adquiere un 2% de descuento. (Opcional)"},
]
BY_ID = {q["id"]: q for q in QUESTIONS}
NOT_APPLICABLE = "No aplica"
COMMENT_MAX = 1000


def public_definition() -> dict:
    """Lo que la página pública necesita para pintar la encuesta (sin nada interno)."""
    return {"version": SURVEY_VERSION, "questions": QUESTIONS, "not_applicable": NOT_APPLICABLE}


class SurveyError(ValueError):
    """Respuesta inválida: el mensaje (en español) se muestra tal cual a la persona."""


def _comment(raw) -> Optional[str]:
    text = " ".join(str(raw or "").split())
    return text[:COMMENT_MAX] or None


def validate(payload: dict) -> list:
    """Valida `{"answers": {question_id: {"choice": ..., "comment": ...}}}` contra la definición vigente y devuelve las filas normalizadas
    `[{"question_id", "score", "choice_text", "comment"}]` (una por pregunta contestada). Lanza SurveyError con un mensaje claro."""
    answers = (payload or {}).get("answers")
    if not isinstance(answers, dict):
        raise SurveyError("Faltan las respuestas de la encuesta.")
    rows = []
    for q in QUESTIONS:
        raw = answers.get(q["id"])
        raw = raw if isinstance(raw, dict) else {}
        choice, comment = raw.get("choice"), _comment(raw.get("comment"))
        blank = choice is None or str(choice).strip() == ""
        if q["type"] == "rating":
            if blank:
                if q["required"]:
                    raise SurveyError(f"Falta responder la pregunta {q['number']}.")
                continue
            if q["allow_na"] and str(choice) in ("na", NOT_APPLICABLE):
                rows.append({"question_id": q["id"], "score": None, "choice_text": NOT_APPLICABLE, "comment": comment})
                continue
            opt = next((o for o in q["options"] if str(choice) in (o["key"], o["label"])), None)
            if opt is None:
                raise SurveyError(f"La respuesta de la pregunta {q['number']} no es válida.")
            rows.append({"question_id": q["id"], "score": opt["score"], "choice_text": opt["label"], "comment": comment})
        elif q["type"] == "nps":
            try:
                value = int(str(choice).strip()) if not blank else None
            except ValueError:
                value = None
            if value is None or not q["min"] <= value <= q["max"]:
                raise SurveyError(f"Falta responder la pregunta {q['number']} con un número del {q['min']} al {q['max']}.")
            rows.append({"question_id": q["id"], "score": value, "choice_text": str(value), "comment": comment})
        else:                                                                                  # optional
            label = None if blank else next((c for c in q["choices"] if str(choice).strip().lower() == c.lower()), None)
            if not blank and label is None:
                raise SurveyError(f"La respuesta de la pregunta {q['number']} no es válida.")
            if label is None and comment is None:
                continue
            rows.append({"question_id": q["id"], "score": None, "choice_text": label, "comment": comment})
    return rows


def summarize(rows: list) -> dict:
    """{nps_score, avg_score, comment_count} de una encuesta ya validada. `avg_score`: promedio (escala 1-3) de las preguntas de calidad contestadas (sin «No aplica»)."""
    scores = [r["score"] for r in rows if r["score"] is not None and BY_ID[r["question_id"]]["type"] == "rating"]
    nps = next((r["score"] for r in rows if BY_ID[r["question_id"]]["type"] == "nps"), None)
    return {"nps_score": nps, "avg_score": round(sum(scores) / len(scores), 2) if scores else None, "comment_count": sum(1 for r in rows if r["comment"])}
