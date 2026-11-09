"""Descargas de «bases de datos de cuentas» (Fase 4): base de digitadores y base de clientes, en Excel (.xlsx) o CSV UTF-8 con BOM.
Sin contraseñas, hashes, sesiones ni datos de salud; texto neutralizado contra fórmulas (app/xlsafe.py); aisladas por cliente/alcance; auditadas (solo cantidad) y con tope por usuario."""
import csv
import io
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app import audit_actions, security
from app.auth import _scope_applies, assert_tenant_id, scope_events_query
from app.database import get_db
from app.download_perms import KIND_CLIENTES, KIND_DIGITADORES, RATE_KIND, RATE_MAX, require_download
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.tenant_scope import staff_tenant_enforced
from app.timeutil import utcnow
from app.xlsafe import safe_cell

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DIGITADOR_HEADERS = ["Cédula", "Nombre", "Teléfono", "Cliente", "Eventos en que ha participado", "Estado", "Cuenta creada"]
CLIENT_HEADERS = ["Código", "Cliente", "Contacto", "Teléfono", "Correo", "Estado", "Eventos"]
CLIENT_ACCOUNT_HEADERS = ["Cliente", "Nombre", "Teléfono", "Correo", "Estado"]


def _state(s: StaffUser) -> str:
    if s.archived_at is not None:
        return "Archivado"
    return "Activo" if s.is_active else "Inactivo"


def _check_rate(db: Session, staff: StaffUser) -> None:
    wait = security.minutes_locked(db, RATE_KIND, str(staff.id), None, RATE_MAX, 0, timedelta(hours=1))
    if wait:
        raise HTTPException(status_code=429, detail=f"Hiciste muchas descargas seguidas. Inténtalo de nuevo en {wait} min.")


def _respond(db: Session, staff: StaffUser, kind: str, fmt: str, sheets: list, rows_count: int) -> Response:
    """`sheets` = [(título, encabezados, filas)]. Registra la auditoría (sin datos personales) y cuenta la descarga en el mismo commit."""
    stamp = utcnow().strftime("%Y%m%d")
    name = f"base_{kind}_{stamp}"
    audit_actions.record(db, staff, "export", f"base_{kind}", staff.id, None, f"{rows_count} filas, {fmt}")
    security.record_event(db, RATE_KIND, str(staff.id), None)          # confirma la transacción completa
    headers = {"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{name}.{fmt}"', "X-Content-Type-Options": "nosniff"}
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        title, head, rows = sheets[0]
        w.writerow(head)
        for r in rows:
            w.writerow([safe_cell(c) for c in r])
        return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
    wb = Workbook()
    wb.remove(wb.active)
    for title, head, rows in sheets:
        ws = wb.create_sheet(title)
        ws.append(head)
        for r in rows:
            ws.append([safe_cell(c) if isinstance(c, str) else c for c in r])
    out = io.BytesIO()
    wb.save(out)
    return Response(content=out.getvalue(), media_type=XLSX, headers=headers)


def _fmt(value: str) -> str:
    v = (value or "xlsx").lower()
    if v not in ("xlsx", "csv"):
        raise HTTPException(status_code=400, detail="Formato no válido (xlsx o csv)")
    return v


@router.get("/staff/export")
def export_staff(kind: str = KIND_DIGITADORES, format: str = "xlsx", db: Session = Depends(get_db), staff: StaffUser = Depends(require_download(KIND_DIGITADORES))):
    """Base de digitadores temporales. Permisos en app/download_perms.py."""
    if kind != KIND_DIGITADORES:
        raise HTTPException(status_code=400, detail="Base no válida")
    fmt = _fmt(format)
    _check_rate(db, staff)
    query = db.query(StaffUser).filter(StaffUser.role == "digitador")
    if staff_tenant_enforced(staff):
        query = query.filter(StaffUser.tenant_id == staff.tenant_id)
    visible = {e.id: e for e in scope_events_query(db.query(Event), staff).all()}          # solo los eventos que su alcance permite
    auth_rows = db.query(EventStaffAuthorization.staff_user_id, EventStaffAuthorization.event_id).filter(EventStaffAuthorization.event_id.in_(list(visible) or [0])).all() if visible else []
    by_staff = {}
    for sid, eid in auth_rows:
        by_staff.setdefault(sid, []).append(visible[eid])
    tenants = {t.id: t.name for t in db.query(Tenant).all()}
    rows = []
    for s in query.order_by(StaffUser.full_name, StaffUser.username).all():
        evs = by_staff.get(s.id, [])
        if _scope_applies(staff) and not evs:
            continue          # A6/A7: con el alcance por evento encendido, solo los digitadores de SUS eventos
        rows.append([s.username, s.full_name or "", s.phone or "", tenants.get(s.tenant_id, ""), "; ".join(f"{e.event_code} {e.name}" for e in sorted(evs, key=lambda e: e.id)), _state(s), s.created_at.strftime("%Y-%m-%d") if s.created_at else ""])
    return _respond(db, staff, KIND_DIGITADORES, fmt, [("Digitadores", DIGITADOR_HEADERS, rows)], len(rows))


@router.get("/tenants/export")
def export_tenants(format: str = "xlsx", tenant_id: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(require_download(KIND_CLIENTES))):
    """Base de clientes: empresas (con su contacto) y las cuentas de usuario tipo cliente. Permisos en app/download_perms.py."""
    fmt = _fmt(format)
    if tenant_id:
        assert_tenant_id(tenant_id, staff)
    _check_rate(db, staff)
    tq = db.query(Tenant)
    cq = db.query(StaffUser).filter(StaffUser.role == "cliente")
    eq = scope_events_query(db.query(Event), staff)
    if staff_tenant_enforced(staff):
        tq = tq.filter(Tenant.id == staff.tenant_id)
        cq = cq.filter(StaffUser.tenant_id == staff.tenant_id)
    events = eq.all()
    if _scope_applies(staff):
        allowed = {e.tenant_id for e in events}
        tq = tq.filter(Tenant.id.in_(allowed or [""]))
        cq = cq.filter(StaffUser.tenant_id.in_(allowed or [""]))
    if tenant_id:
        tq = tq.filter(Tenant.id == tenant_id)
        cq = cq.filter(StaffUser.tenant_id == tenant_id)
    count = {}
    for e in events:
        count[e.tenant_id] = count.get(e.tenant_id, 0) + 1
    tenants = tq.order_by(Tenant.name).all()
    names = {t.id: t.name for t in db.query(Tenant).all()}
    rows = [[t.client_code, t.name, t.contact_name or "", t.contact_phone or "", t.contact_email or "", "Archivado" if t.archived_at else "Activo", count.get(t.id, 0)] for t in tenants]
    accounts = [[names.get(c.tenant_id, ""), c.full_name or "", c.phone or "", c.email or "", _state(c)] for c in cq.order_by(StaffUser.full_name).all()]
    sheets = [("Clientes", CLIENT_HEADERS, rows), ("Cuentas de cliente", CLIENT_ACCOUNT_HEADERS, accounts)]
    if fmt == "csv":
        sheets = sheets[:1]          # el CSV lleva una sola tabla: las empresas
    return _respond(db, staff, KIND_CLIENTES, fmt, sheets, len(rows) + (len(accounts) if fmt == "xlsx" else 0))
