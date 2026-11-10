"""Permanencia en las zonas y premio por porcentaje de estadía (Fase 10, 10-nov-2026).

Con «Contar el tiempo de permanencia» activo en Parámetros, las entradas y salidas de cada zona se SUMAN por persona (10 min + 5 min = 15 min). El coordinador define el total de referencia
(el 100 %, p. ej. las 24 h de un evento); el panel cuenta cuántas personas llegan a cada porcentaje, se baja la lista (Excel o CSV) y el resultado se usa para habilitar certificados
y para que ciertos ítems de inventario solo se entreguen a quien cumple (ver app/area_dwell_svc.py). La persona de prueba nunca cuenta.
Permisos: los mismos de configurar zonas y bajar reportes de áreas (coordinador en adelante, menos comercial)."""
import csv
import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import area_dwell, area_dwell_svc, audit_actions, event_archive, heavy, testperson
from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import EventAttendee, StaffUser

router = APIRouter()

CONFIG_ROLE = require_role_excluding("coordinador", ("comercial",))


def _event(db: Session, event_id: int, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return event


def _pct(raw, event) -> int:
    try:
        return area_dwell.clean_threshold_pct(raw) if raw not in (None, "") else area_dwell_svc.threshold(event)
    except area_dwell.DwellError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _enabled(event) -> None:
    if not event.areas_dwell_enabled:
        raise HTTPException(status_code=409, detail="El conteo de permanencia no está activado en este evento. Actívalo en Parámetros del evento, en «Zonas e inventario».")


@router.get("/events/{event_id}/areas-dwell/config")
def get_config(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    return area_dwell_svc.config_json(_event(db, event_id, staff))


@router.put("/events/{event_id}/areas-dwell/config")
def put_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Guarda lo que venga: `dwell_enabled`, `prize_enabled`, `reference_minutes`, `threshold_pct`, `areas_autoscan`, `inventory_autoscan`."""
    event = _event(db, event_id, staff)
    try:
        if "reference_minutes" in data:
            event.dwell_reference_minutes = area_dwell.clean_reference_minutes(data["reference_minutes"])
        if "threshold_pct" in data:
            event.dwell_threshold_pct = area_dwell.clean_threshold_pct(data["threshold_pct"])
    except area_dwell.DwellError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    for key, col in (("dwell_enabled", "areas_dwell_enabled"), ("prize_enabled", "dwell_prize_enabled"), ("areas_autoscan", "areas_autoscan"), ("inventory_autoscan", "inventory_autoscan")):
        if key in data:
            setattr(event, col, bool(data[key]))
    if event.dwell_prize_enabled and not event.areas_dwell_enabled:
        raise HTTPException(status_code=400, detail="Para habilitar el premio por porcentaje primero activa el conteo de permanencia")
    if event.dwell_prize_enabled and not area_dwell_svc.reference(event):
        raise HTTPException(status_code=400, detail="Define el tiempo de referencia (el 100 %) o las fechas y horas del evento para calcularlo")
    audit_actions.record(db, staff, "update", "event_dwell_config", event.id, event.name,
                         f"conteo={bool(event.areas_dwell_enabled)} premio={bool(event.dwell_prize_enabled)} ref={event.dwell_reference_minutes} pct={event.dwell_threshold_pct} autoescaneo_zonas={bool(event.areas_autoscan)} autoescaneo_inventario={bool(event.inventory_autoscan)}")
    db.commit()
    return area_dwell_svc.config_json(event)


@router.get("/events/{event_id}/areas-dwell")
def dwell_stats(event_id: int, pct: str = "", area_id: int = 0, only: str = "", limit: int = 300, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Resumen (cuántas personas llegan a cada porcentaje) y las primeras filas. `pct` = porcentaje a evaluar (por defecto el del evento); `only=cumple` deja solo a quien lo alcanza."""
    event = _event(db, event_id, staff)
    _enabled(event)
    thr = _pct(pct, event)
    rows = area_dwell_svc.rows(db, event, area_id=area_id or None, pct=thr)
    summary = area_dwell.summarize(rows, area_dwell_svc.reference(event), thr)
    shown = [r for r in rows if r["meets"]] if only == "cumple" else rows
    return {"config": area_dwell_svc.config_json(event), "summary": summary, "rows": shown[:max(1, min(limit, 1000))], "truncated": len(shown) > max(1, min(limit, 1000)),
            "areas": area_dwell_svc.areas_of(db, event)}


@router.get("/events/{event_id}/areas-dwell/export")
def dwell_export(event_id: int, fmt: str = "xlsx", pct: str = "", area_id: int = 0, only: str = "todos", db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Lista descargable (Excel o CSV) con cédula, nombre, tiempo y porcentaje. `only=cumple` baja solo a quienes alcanzan el porcentaje."""
    event = _event(db, event_id, staff)
    _enabled(event)
    thr = _pct(pct, event)
    rows = area_dwell_svc.rows(db, event, area_id=area_id or None, pct=thr)
    if only == "cumple":
        rows = [r for r in rows if r["meets"]]
    ref = area_dwell_svc.reference(event)
    cols = ["Cédula", "Persona", "Entidad", "Tiempo acumulado (min)", "Tiempo", "Porcentaje de la referencia", f"Cumple el {thr} %", "Entradas", "Quedó sin salida"]
    data = [[r["id"], r["name"], r["entity"], r["minutes"], r["label"], r["percent"] if r["percent"] is not None else "", "Sí" if r["meets"] else "No", r["entries"], "Sí" if r["open"] else "No"] for r in rows]
    kind = "Permanencia en zonas" + (" (cumplen)" if only == "cumple" else "")
    audit_actions.record(db, staff, "export", "event_dwell", event.id, event.name, f"{len(rows)} fila(s); {fmt}; ref {ref} min; {thr} %")
    db.commit()
    if fmt == "csv":
        from app.xlsafe import safe_cell
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for row in data:
            w.writerow([safe_cell(v) for v in row])
        return Response(("\ufeff" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": heavy.content_disposition(heavy.event_report_filename(event, kind, ".csv"))})
    from app.routers.areas_inventory import _xlsx_response
    return _xlsx_response({"Permanencia": pd.DataFrame(data, columns=cols)}, heavy.event_report_filename(event, kind))


@router.post("/events/{event_id}/areas-dwell/apply-certificates")
def apply_certificates(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Marca «Certificado: Sí» a quienes alcanzan el porcentaje. Con `exclusive: true` también quita el certificado a quien no lo alcanza (la persona de prueba nunca se toca)."""
    event = _event(db, event_id, staff)
    _enabled(event)
    thr = _pct(data.get("pct"), event)
    ok = {r["id"] for r in area_dwell_svc.rows(db, event, pct=thr) if r["meets"]}
    q = db.query(EventAttendee).filter(EventAttendee.event_id == event.id, func.upper(EventAttendee.user_id) != testperson.TEST_ID)
    granted = removed = 0
    for att in q.all():
        if att.user_id in ok:
            if not att.certificate:
                att.certificate = True
                granted += 1
        elif data.get("exclusive") and att.certificate:
            att.certificate = False
            removed += 1
    audit_actions.record(db, staff, "update", "event_certificates", event.id, event.name, f"por estadía ≥ {thr} %: +{granted} / -{removed}")
    db.commit()
    return {"qualifying": len(ok), "granted": granted, "removed": removed, "threshold_pct": thr,
            "certificates_enabled": bool(event.certificates_enabled)}
