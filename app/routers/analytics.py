"""Tablero de analítica del REGISTRO del evento (Sprint 5): la primera fuente del módulo compartido (`app/analytics.py`).
Visible para coordinador+ y para el cliente del evento (reemplaza el placeholder de "Estadísticas" que tenía el rol
`cliente`). Los tableros de los Formularios Web usan el mismo formato y el mismo componente del navegador."""
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import analytics as an
from app.auth import get_event_for_staff, require_role_or_client
from app.database import get_db
from app.models import AccessLog, Event, EventAttendee, StaffUser, User
from app.reports import REGISTRATION_METHOD_LABELS
from app.timeutil import to_local

router = APIRouter()


def registro_dashboard(db: Session, event: Event) -> dict:
    attendees = {a.user_id: a for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id)}
    logs = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado").order_by(AccessLog.timestamp).all()
    first = {}
    for lg in logs:
        first.setdefault(lg.user_id, lg)                       # el primer registro real de cada persona
    ids = set(attendees) | set(first)
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids))} if ids else {}
    total = len(ids)
    done = len(first)
    pending = total - done
    times = [lg.timestamp for lg in first.values()]

    kpis = [
        an.kpi("Base del evento", total, "personas cargadas o registradas"),
        an.kpi("Registrados", done, an.pct(done, total) + " de la base", "good"),
        an.kpi("Pendientes", pending, "aún no han llegado", "warn" if pending else "good"),
    ]
    if times:
        kpis.append(an.kpi("Primer registro", an.fmt_local(min(times)), "hora local"))
        kpis.append(an.kpi("Último registro", an.fmt_local(max(times)), "hora local"))
        kpis.append(an.kpi("Hora pico", an.peak_hour(times) or "—", "más registros en una hora"))
        hours = max(1 / 60, (max(times) - min(times)).total_seconds() / 3600)
        if len(times) > 1:
            kpis.append(an.kpi("Ritmo promedio", f"{len(times) / hours:.0f} / hora", "entre el primer y el último registro"))

    charts = [
        an.time_series("timeline", "Registros en el tiempo", times),
        an.hour_histogram("by_hour", "Registros por hora del día", times),
        an.counter_chart("by_method", "Cómo se registraron", [REGISTRATION_METHOD_LABELS.get(lg.registration_method, lg.registration_method or "Sin especificar") for lg in first.values()], kind="pie"),
    ]

    # Avance (registrados vs pendientes) por categoría y por entidad.
    by_cat, by_entity = {}, {}
    for uid in ids:
        registered = uid in first
        for cat in (attendees[uid].get_categories() if uid in attendees else []) or []:
            by_cat.setdefault(cat, [0, 0])[0 if registered else 1] += 1
        entity = (users[uid].entity if uid in users else "") or ""
        if entity.strip():
            by_entity.setdefault(entity.strip().upper(), [0, 0])[0 if registered else 1] += 1
    charts.append(an.progress_by_group("by_category", "Avance por categoría", by_cat, horizontal=False))
    charts.append(an.progress_by_group("by_entity", "Avance por entidad (las 10 con más gente)", by_entity))

    staff_ids = {lg.registered_by_staff_id for lg in first.values() if lg.registered_by_staff_id}
    if staff_ids:
        names = {s.id: (s.full_name or s.username) for s in db.query(StaffUser).filter(StaffUser.id.in_(staff_ids))}
        charts.append(an.counter_chart("by_operator", "Registros por operador", [names.get(lg.registered_by_staff_id, "—") for lg in first.values() if lg.registered_by_staff_id], top=10, label="Registros"))
    return an.dashboard("Registro del evento", kpis, [c for c in charts if c])


@router.get("/events/{event_id}/analytics/registro")
async def analytics_registro(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_or_client("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    return registro_dashboard(db, event)
