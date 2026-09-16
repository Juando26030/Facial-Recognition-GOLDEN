"""Módulo de Estadísticas (Sprint 2.2 Fase D, 2026-09-16) — pedido explícito: elegir variables
de un checklist y sacar un gráfico por cada una, detectando automáticamente si conviene un
gráfico categórico (barras/pie) o numérico (histograma). Alcance de esta entrega: UNA variable a
la vez (confirmado con Juan David) — cruces de 2+ variables (ej. pirámide edad×género) quedan
para una fase futura, ver CLAUDE.md.
"""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role_or_client
from app.database import get_db
from app.models import AccessLog, EventAttendee, StaffUser, User

router = APIRouter()

# Variables fijas ofrecidas siempre (además de los opcional_N configurados del evento). Se
# excluyen a propósito id/first_name/last_name/phone/email: son identificadores, prácticamente
# únicos por persona — un gráfico de barras con 500 barras distintas no aporta nada.
_FIXED_VARIABLES = [
    ("company", "Empresa"),
    ("role", "Cargo"),
    ("opt_1", "Tipo de Asistente"),
    ("status", "Estado de registro"),
]

_MAX_CATEGORIES = 15  # más allá de esto, se agrupa en "Otros" para que el gráfico siga siendo legible
_NUMERIC_BINS = 8


def _event_directory_users(db: Session, event_id: int, tenant_id: str):
    """Mismo universo que el Directorio (GET /api/users): EventAttendee ∪ AccessLog de este
    evento, no todo el tenant."""
    attendee_ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == event_id)}
    log_ids = {l.user_id for l in db.query(AccessLog).filter(AccessLog.event_id == event_id)}
    all_ids = attendee_ids | log_ids
    if not all_ids:
        return []
    return db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(all_ids)).all()


def _status_of(db: Session, event_id: int, user_id: str) -> str:
    logs = db.query(AccessLog).filter(AccessLog.event_id == event_id, AccessLog.user_id == user_id).all()
    if not logs:
        return "No registrado"
    return "Nuevo" if any(l.record_type == "Nuevo" for l in logs) else "Registrado"


def _value_of(db: Session, event_id: int, user: User, variable: str):
    if variable == "status":
        return _status_of(db, event_id, user.id)
    if variable.startswith("opcional_"):
        return user.get_extras().get(variable)
    return getattr(user, variable, None)


@router.get("/events/{event_id}/stats/variables")
async def list_stats_variables(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_or_client("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    variables = list(_FIXED_VARIABLES)
    optional_labels = event.get_optional_labels()
    for key, label in sorted(optional_labels.items(), key=lambda kv: int(kv[0].split("_")[1])):
        variables.append((key, label))
    return [{"key": k, "label": label} for k, label in variables]


@router.get("/events/{event_id}/stats/data")
async def get_stats_data(
    event_id: int, variable: str, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_or_client("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    valid_keys = {k for k, _ in _FIXED_VARIABLES} | set(event.get_optional_labels().keys())
    if variable not in valid_keys:
        raise HTTPException(status_code=400, detail="Variable no válida para este evento")

    users = _event_directory_users(db, event_id, event.tenant_id)
    raw_values = [_value_of(db, event_id, u, variable) for u in users]
    non_empty = [str(v).strip() for v in raw_values if v is not None and str(v).strip() != ""]

    if not non_empty:
        return {"type": "categorical", "buckets": []}

    numeric_values = []
    for v in non_empty:
        try:
            numeric_values.append(float(v.replace(",", ".")))
        except ValueError:
            pass

    # Numérica si al menos el 90% de los valores no vacíos parsean como número — el resto
    # (nombres, categorías de texto, etc.) se trata como categórica.
    is_numeric = len(numeric_values) >= 0.9 * len(non_empty) and len(numeric_values) > 0

    if is_numeric:
        lo, hi = min(numeric_values), max(numeric_values)
        if lo == hi:
            return {"type": "numeric", "buckets": [{"label": f"{lo:g}", "count": len(numeric_values)}]}
        width = (hi - lo) / _NUMERIC_BINS
        bins = [0] * _NUMERIC_BINS
        for v in numeric_values:
            idx = min(int((v - lo) / width), _NUMERIC_BINS - 1)
            bins[idx] += 1
        buckets = []
        for i, count in enumerate(bins):
            start = lo + i * width
            end = lo + (i + 1) * width
            buckets.append({"label": f"{start:.1f}–{end:.1f}", "count": count})
        return {"type": "numeric", "buckets": buckets}

    counts = Counter(non_empty)
    ordered = counts.most_common()
    top = ordered[:_MAX_CATEGORIES]
    rest_count = sum(c for _, c in ordered[_MAX_CATEGORIES:])
    buckets = [{"label": label, "count": count} for label, count in top]
    if rest_count:
        buckets.append({"label": "Otros", "count": rest_count})
    return {"type": "categorical", "buckets": buckets}
