"""Tablero de analítica del REGISTRO del evento (Sprint 5): la primera fuente del módulo compartido (`app/analytics.py`).
Visible para coordinador+ y para el cliente del evento (reemplaza el placeholder de "Estadísticas" que tenía el rol
`cliente`). Los tableros de los Formularios Web usan el mismo formato y el mismo componente del navegador."""
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import analytics as an, regtime
from app.auth import get_event_for_staff, require_role, require_role_or_client
from app import event_archive
from app.database import get_db
from app import testperson
from app.models import AccessLog, Event, EventAttendee, StaffUser, User
from app.reports import REGISTRATION_METHOD_LABELS
from app.routers.stats import is_staff_view
from app.timeutil import to_local

router = APIRouter()


def registro_dashboard(db: Session, event: Event, with_origin: bool = False, with_operators: bool = False) -> dict:
    """`with_origin`: solo para el personal (admin, coordinador, comercial): agrega de dónde salió la gente de la base (Excel / digitados a mano / formulario). El cliente y los enlaces públicos nunca lo reciben."""
    attendees = {a.user_id: a for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id != testperson.TEST_ID)}
    logs = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado", AccessLog.user_id != testperson.TEST_ID).order_by(AccessLog.timestamp).all()
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
    if with_origin:
        kpis += _origin_kpis(attendees, ids, logs)
    if times:
        kpis.append(an.kpi("Primer registro", an.fmt_local(min(times)), "hora local", icon="flag-start"))
        kpis.append(an.kpi("Último registro", an.fmt_local(max(times)), "hora local", icon="flag-end"))
        kpis.append(an.kpi("Hora pico", an.peak_hour(times) or "—", "más registros en una hora", icon="peak"))
        hours = max(1 / 60, (max(times) - min(times)).total_seconds() / 3600)
        if len(times) > 1:
            kpis.append(an.kpi("Ritmo promedio", f"{len(times) / hours:.0f} / hora", "entre el primer y el último registro", icon="gauge"))

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

    # «Registros por operador» (P9, 6-nov-2026): solo para el personal (`with_operators`); el cliente y el enlace público no lo reciben. Sin nombre se muestra «Digitador N»,
    # nunca el usuario: el del digitador es su cédula.
    staff_ids = {lg.registered_by_staff_id for lg in first.values() if lg.registered_by_staff_id} if with_operators else set()
    if staff_ids:
        names = {s.id: ((s.full_name or "").strip() or f"Digitador {n}") for n, s in enumerate(db.query(StaffUser).filter(StaffUser.id.in_(staff_ids)).order_by(StaffUser.id), start=1)}
        charts.append(an.counter_chart("by_operator", "Registros por operador", [names.get(lg.registered_by_staff_id, "—") for lg in first.values() if lg.registered_by_staff_id], top=10, label="Registros"))
    return an.dashboard("Registro del evento", kpis, [c for c in charts if c])


def _origin_kpis(attendees: dict, ids: set, logs: list) -> list:
    """De dónde salió cada persona de la base: la carga del Excel, las dadas de alta a mano (nuevas) o las que llegaron por el formulario web. Mismas reglas que «Origen de carga» del reporte."""
    new_by_hand = {lg.user_id for lg in logs if lg.record_type == "Nuevo"}
    count = {"base": 0, "manual": 0, "autoregistro": 0, "otro": 0}
    for uid in ids:
        att = attendees.get(uid)
        origin = att.origin if att is not None and att.origin else ("manual" if uid in new_by_hand else None)
        count[origin if origin in count else "otro"] += 1
    total = len(ids)
    out = [an.kpi("Vienen del Excel (base)", count["base"], an.pct(count["base"], total) + " de la base", icon="sheet"),
           an.kpi("Nuevos digitados a mano", count["manual"], an.pct(count["manual"], total) + " de la base", icon="hand"),
           an.kpi("Llegaron por formulario", count["autoregistro"], an.pct(count["autoregistro"], total) + " de la base", icon="form")]
    if count["otro"]:
        out.append(an.kpi("Origen desconocido", count["otro"], "cargas anteriores a este dato", icon="help"))
    return out


@router.get("/events/{event_id}/analytics/registro")
def analytics_registro(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_or_client("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    staff_view = is_staff_view(staff)
    return registro_dashboard(db, event, with_origin=staff_view, with_operators=staff_view)


@router.get("/events/{event_id}/timing-report")
def timing_report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Fase 1A, PR1 (solo lectura, admin y super_admin): p50/p90 del tiempo por registro (`access_logs.took_ms`) del evento, en total, por pantalla (`ui_flow`) y por digitador. Solo agregados:
    ni cédulas ni nombres de asistentes; el digitador va por su nombre de cuenta (nunca su usuario, que es su cédula) o «Digitador N»."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    rows = db.query(AccessLog.registered_by_staff_id, AccessLog.ui_flow, AccessLog.took_ms, AccessLog.record_type).filter(AccessLog.event_id == event.id, AccessLog.user_id != testperson.TEST_ID).all()
    ids = {r[0] for r in rows if r[0] is not None}
    names = {sid: (name or "").strip() for sid, name in db.query(StaffUser.id, StaffUser.full_name).filter(StaffUser.id.in_(ids))} if ids else {}
    return {"event_id": event.id, **regtime.build_report([tuple(r) for r in rows], names)}
