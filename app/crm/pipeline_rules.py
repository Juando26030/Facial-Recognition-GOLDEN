"""Reglas PURAS de embudos, oportunidades, leads y actividades del CRM (etapa C2). Sin SQLAlchemy ni base de datos: se prueban sin conexión (tests/test_crm_c2_texto.py).

Aquí vive todo lo que se puede decidir mirando solo los datos que llegan: validación con topes en español, probabilidad efectiva, monto ponderado, qué cambia al mover una oportunidad de
etapa, qué se exige para convertir un lead y cuál es la próxima actividad. Los servicios (pipeline.py, opportunities.py, leads.py, activities.py) hablan con la base y usan estas funciones.
Los topes de texto son EXACTAMENTE los de las columnas de app/models.py (hay una prueba que lo comprueba): un texto más largo es un 400 en español, nunca un 500.
"""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.crm.errors import CrmError

PIPELINE_LIMITS = {"name": 120}
STAGE_LIMITS = {"name": 80}
OPPORTUNITY_LIMITS = {"name": 200, "opp_type": 60, "source": 60, "next_step": 200, "description": 20000, "city": 120, "lost_reason": 200}
LEAD_LIMITS = {"first_name": 120, "last_name": 120, "company_name": 200, "job_title": 120, "email": 200, "phone": 60, "source": 60, "description": 20000}
ACTIVITY_LIMITS = {"subject": 200, "description": 20000}

STAGE_KINDS = ("open", "won", "lost")
OUTCOMES = ("open", "won", "lost")
CURRENCIES = ("COP", "USD")
LEAD_STATUSES = ("nuevo", "contactado", "calificado", "convertido", "descartado")
LEAD_OPEN_STATUSES = ("nuevo", "contactado", "calificado")
ACTIVITY_KINDS = {"call": "Llamada", "task": "Tarea", "meeting": "Reunión", "note": "Nota"}
ACTIVITY_STATUSES = ("planned", "done", "cancelled")
# Resultado de una actividad: lista cerrada y corta (llave guardada → texto en pantalla). Para cambiarla basta editar este diccionario: no hay restricción en la base.
RESULTS = {"portfolio_sent": "Portafolio enviado", "quote_sent": "Cotización enviada", "po_pending": "Orden de compra pendiente", "no_answer": "Sin respuesta",
           "meeting_held": "Reunión realizada", "other": "Otro"}

MAX_AMOUNT = Decimal("999999999999.99")          # Numeric(14, 2): doce cifras enteras
BOARD_PAGE = 50                                    # tarjetas por columna del tablero antes de «ver más»
BOARD_MAX_OFFSET = 100_000
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ campos sueltos
def text_field(data: dict, key: str, limit: int, out: dict, label: Optional[str] = None) -> None:
    """Copia a `out` el texto limpio de `data[key]` (si viene). Vacío → None. Más largo que `limit` → 400 en español."""
    if key not in data:
        return
    v = data[key]
    v = (str(v).strip() if v is not None else "") or None
    if v is not None and len(v) > limit:
        raise CrmError(f"El campo «{label or key}» es demasiado largo (máximo {limit} caracteres).")
    out[key] = v


def clean_amount(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise CrmError("El monto debe ser un número.") from exc
    if not d.is_finite() or d < 0:
        raise CrmError("El monto debe ser un número mayor o igual a cero.")
    if d > MAX_AMOUNT:
        raise CrmError("El monto es demasiado grande.")
    return d.quantize(Decimal("0.01"))


def clean_currency(value) -> str:
    v = (str(value).strip().upper() if value is not None else "")
    if v not in CURRENCIES:
        raise CrmError(f"La moneda debe ser una de: {', '.join(CURRENCIES)}.")
    return v


def clean_probability(value) -> Optional[int]:
    """None o vacío = «la de la etapa». Si viene, entero entre 0 y 100."""
    if value in (None, ""):
        return None
    try:
        n = int(Decimal(str(value).strip().replace(",", ".")))
    except (InvalidOperation, ValueError) as exc:
        raise CrmError("La probabilidad debe ser un número entero entre 0 y 100.") from exc
    if not 0 <= n <= 100:
        raise CrmError("La probabilidad debe estar entre 0 y 100.")
    return n


def clean_date(value, label: str) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise CrmError(f"La fecha «{label}» no es válida (usa año-mes-día).") from exc


def clean_datetime(value, label: str) -> Optional[datetime]:
    """Fecha y hora de entrada a UTC sin zona (la hora interna es siempre UTC). Acepta «2026-11-20T15:00:00Z», con desplazamiento, o sin zona (se toma como UTC)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CrmError(f"La fecha y hora «{label}» no es válida.") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if not 2000 <= dt.year <= 2100:
        raise CrmError(f"La fecha «{label}» está fuera de rango.")
    return dt


def clean_id(value, label: str) -> Optional[int]:
    """Id opcional: vacío = None; si viene debe ser un entero positivo que quepa en la base."""
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise CrmError(f"El valor de «{label}» no es válido.") from exc
    if not 0 < n <= 2_147_483_647:
        raise CrmError(f"El valor de «{label}» no es válido.")
    return n


# ------------------------------------------------------------------ embudos y etapas
def clean_pipeline(data: dict) -> dict:
    out: dict = {}
    text_field(data, "name", PIPELINE_LIMITS["name"], out, "nombre")
    if "name" in out and not out["name"]:
        raise CrmError("El embudo necesita un nombre.")
    return out


def clean_stage(data: dict) -> dict:
    out: dict = {}
    text_field(data, "name", STAGE_LIMITS["name"], out, "nombre")
    if "name" in out and not out["name"]:
        raise CrmError("La etapa necesita un nombre.")
    if "probability" in data:
        p = clean_probability(data["probability"])
        out["probability"] = 0 if p is None else p
    if "kind" in data:
        k = str(data["kind"] or "").strip().lower()
        if k not in STAGE_KINDS:
            raise CrmError("El tipo de etapa debe ser abierta, ganada o perdida.")
        out["kind"] = k
        if k == "won":
            out.setdefault("probability", 100)
        elif k == "lost":
            out.setdefault("probability", 0)
    return out


def check_stage_set(stages: Iterable[tuple]) -> None:
    """`stages` = [(kind, archived)] del embudo tal como QUEDARÍA. Debe haber al menos una etapa abierta, una ganada y una perdida sin archivar."""
    live = [k for k, archived in stages if not archived]
    for kind, label in (("open", "una etapa abierta"), ("won", "una etapa ganada"), ("lost", "una etapa perdida")):
        if kind not in live:
            raise CrmError(f"El embudo debe conservar al menos {label}.")


# ------------------------------------------------------------------ oportunidades
def clean_opportunity(data: dict, *, creating: bool) -> dict:
    out: dict = {}
    for key, limit in OPPORTUNITY_LIMITS.items():
        text_field(data, key, limit, out)
    if "name" in out and not out["name"]:
        raise CrmError("La oportunidad necesita un nombre.")
    if creating and not out.get("name"):
        raise CrmError("La oportunidad necesita un nombre.")
    if "amount" in data or creating:
        out["amount"] = clean_amount(data.get("amount"))
    if "currency" in data or creating:
        out["currency"] = clean_currency(data.get("currency") or "COP")
    if "probability" in data:
        out["probability"] = clean_probability(data["probability"])
    for key in ("expected_close", "event_start"):
        if key in data:
            out[key] = clean_date(data[key], key)
    for key in ("owner_staff_id", "primary_contact_id", "pipeline_id", "stage_id", "account_id"):
        if key in data:
            out[key] = clean_id(data[key], key)
    return out


def effective_probability(opp_probability: Optional[int], stage_probability: int) -> int:
    return stage_probability if opp_probability is None else opp_probability


def weighted(amount, probability: int) -> Decimal:
    """Monto × probabilidad / 100, con dos decimales."""
    return (Decimal(str(amount or 0)) * Decimal(int(probability)) / Decimal(100)).quantize(Decimal("0.01"))


def move_effects(stage_kind: str, previous_outcome: str, lost_reason: Optional[str], now: datetime) -> dict:
    """Qué campos de la oportunidad cambian al ponerla en una etapa de este tipo. Una etapa ganada o perdida cierra; una abierta (re)abre."""
    if stage_kind not in STAGE_KINDS:
        raise CrmError("Tipo de etapa desconocido.")
    if stage_kind == "open":
        return {"outcome": "open", "closed_at": None, "lost_reason": None, "stage_entered_at": now}
    reason = (lost_reason or "").strip() or None
    if reason is not None and len(reason) > OPPORTUNITY_LIMITS["lost_reason"]:
        raise CrmError(f"El motivo es demasiado largo (máximo {OPPORTUNITY_LIMITS['lost_reason']} caracteres).")
    return {"outcome": stage_kind, "closed_at": now, "lost_reason": reason if stage_kind == "lost" else None, "stage_entered_at": now}


def board_paging(offset, size=BOARD_PAGE) -> tuple:
    try:
        off = int(offset or 0)
    except (TypeError, ValueError):
        off = 0
    return max(0, min(off, BOARD_MAX_OFFSET)), max(1, min(int(size or BOARD_PAGE), 200))


# ------------------------------------------------------------------ leads
def clean_lead(data: dict, *, creating: bool) -> dict:
    out: dict = {}
    for key, limit in LEAD_LIMITS.items():
        text_field(data, key, limit, out)
    if out.get("email") and not _EMAIL.match(out["email"]):
        raise CrmError("El correo del lead no es válido.")
    if "status" in data:
        s = str(data["status"] or "").strip().lower()
        if s not in LEAD_STATUSES or s == "convertido":
            raise CrmError("El estado del lead debe ser nuevo, contactado, calificado o descartado.")
        out["status"] = s
    if "owner_staff_id" in data:
        out["owner_staff_id"] = clean_id(data["owner_staff_id"], "responsable")
    return out


def lead_has_identity(first: Optional[str], last: Optional[str], company: Optional[str], email: Optional[str]) -> bool:
    return bool((first or "").strip() or (last or "").strip() or (company or "").strip() or (email or "").strip())


def check_convertible(status: str) -> None:
    if status == "convertido":
        raise CrmError("Este lead ya fue convertido.", 409)
    if status == "descartado":
        raise CrmError("Un lead descartado no se convierte. Devuélvelo a «nuevo» primero.", 409)


# ------------------------------------------------------------------ actividades
def clean_activity(data: dict, *, creating: bool) -> dict:
    out: dict = {}
    for key, limit in ACTIVITY_LIMITS.items():
        text_field(data, key, limit, out)
    if "subject" in out and not out["subject"]:
        raise CrmError("La actividad necesita un asunto.")
    if creating and not out.get("subject"):
        raise CrmError("La actividad necesita un asunto.")
    if "kind" in data or creating:
        k = str(data.get("kind") or "").strip().lower()
        if k not in ACTIVITY_KINDS:
            raise CrmError("El tipo de actividad debe ser llamada, tarea, reunión o nota.")
        out["kind"] = k
    for key in ("due_at", "remind_at"):
        if key in data:
            out[key] = clean_datetime(data[key], key)
    if out.get("due_at") and out.get("remind_at") and out["remind_at"] > out["due_at"]:
        raise CrmError("El recordatorio debe ser antes de la fecha de la actividad.")
    for key in ("owner_staff_id", "account_id", "contact_id", "lead_id", "opportunity_id"):
        if key in data:
            out[key] = clean_id(data[key], key)
    return out


def clean_result(value) -> Optional[str]:
    if value in (None, ""):
        return None
    v = str(value).strip()
    if v not in RESULTS:
        raise CrmError("El resultado de la actividad no es válido.")
    return v


def check_attached(account_id, contact_id, lead_id, opportunity_id) -> None:
    if not any((account_id, contact_id, lead_id, opportunity_id)):
        raise CrmError("La actividad debe estar ligada a una cuenta, un contacto, un lead o una oportunidad.")


def next_due(activities: Iterable[tuple]) -> Optional[datetime]:
    """La menor fecha entre las actividades PLANIFICADAS con fecha. `activities` = [(status, due_at)]. Es lo que se copia a `crm_opportunities.next_activity_at`."""
    dues = [due for status, due in activities if status == "planned" and due is not None]
    return min(dues) if dues else None
