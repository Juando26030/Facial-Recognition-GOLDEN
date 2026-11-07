"""Puestos de impresión configurados desde Parámetros (26-oct-2026; 27-oct-2026: la impresión vuelve a la del domingo 25-oct 18:00).

  - Por cada cuenta de puesto y evento se guarda en el SERVIDOR (`print_stations.settings_json`) solo lo que NO cambia cómo sale la etiqueta: «solo lector» (`readerOnly`) y si en su
    Registro se muestra o esconde el menú de impresión (`showConfig`; sin el campo = Mostrar). La etiqueta sale con los valores del evento y lo de ⚙️ de cada computador.
  - Lo que se haya guardado antes (modo, ancho de página, calibración, serie USB, giro, recorte, corte…) NO se borra: se conserva tal cual en el JSON y se IGNORA.
  - El puesto, al cargar, lee su configuración (`GET …/print-station/me`). Los endpoints de configuración rechazan a los roles sin permiso (CONFIG = coordinador o más, sin comercial).
  - Casilla «Puesto de impresión» (`staff_users.print_station`): la cuenta queda protegida contra un segundo inicio de sesión (app/sessions.py). Solo admin la marca y la libera."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import sessions
from app.auth import get_current_staff, get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import PrintStation, StaffUser
from app.timeutil import utcnow

log = logging.getLogger("golden.print_stations")
router = APIRouter()

ADMIN = require_role("admin")
CONFIG = require_role_excluding("coordinador", ("comercial",))
OPERATOR = require_role_excluding("digitador", ("comercial",))


MANAGED = ("readerOnly", "showConfig")      # lo único que se usa; el resto de lo guardado se conserva y se ignora


def sanitize(data: dict) -> dict:
    """Solo «solo lector» y «Mostrar/Esconder» (sí/no; 400 si no). Cualquier otra clave se ignora (ya no cambia la impresión)."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="La configuración del puesto no es válida")
    out = {}
    if data.get("showConfig") is not None:
        if not isinstance(data["showConfig"], bool):
            raise HTTPException(status_code=400, detail="«Mostrar la configuración de impresión» debe ser sí o no")
        out["showConfig"] = data["showConfig"]
    if data.get("readerOnly") is not None:
        if not isinstance(data["readerOnly"], bool):
            raise HTTPException(status_code=400, detail="«Solo lector» debe ser sí o no")
        out["readerOnly"] = data["readerOnly"]
    return out


def read_station(db: Session, event_id: int, staff_id: int) -> Optional[dict]:
    row = db.query(PrintStation).filter_by(event_id=event_id, staff_user_id=staff_id).first()
    if row is None or not row.settings_json:
        return None
    try:
        data = json.loads(row.settings_json)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@router.get("/session/ping")
def session_ping(staff: StaffUser = Depends(get_current_staff)):
    """Comprobación mínima de que la sesión sigue vigente (si la cuenta entró en otro dispositivo responde 401 «session_replaced»): la consulta el navegador de quien tiene sesión única."""
    return {"ok": True}


@router.get("/events/{event_id}/print-station/me")
def my_station(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Lo que necesita el Registro al cargar: ¿es administrador (ve la configuración)?, ¿es cuenta de puesto? y su configuración guardada en el servidor (None = lo de siempre)."""
    event = get_event_for_staff(event_id, db, staff)
    return {"admin": staff.role in sessions.MULTI_ROLES, "station": bool(staff.print_station), "settings": read_station(db, event.id, staff.id)}


@router.put("/events/{event_id}/print-stations/{staff_id}")
def put_station(event_id: int, staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG)):
    """Guarda la configuración del puesto (`settings`; `null` o `{}` la borra: vuelve a lo de siempre) y, solo si lo manda un admin, la casilla `print_station`."""
    event = get_event_for_staff(event_id, db, staff)
    target = db.get(StaffUser, staff_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    get_event_for_staff(event.id, db, target)                 # la cuenta debe tener acceso a ESTE evento
    if "print_station" in data:
        if staff.role not in sessions.MULTI_ROLES:
            raise HTTPException(status_code=403, detail="Solo un administrador marca una cuenta como puesto de impresión.")
        target.print_station = bool(data["print_station"])
    if "settings" in data:
        clean = sanitize(data["settings"]) if data["settings"] else {}
        row = db.query(PrintStation).filter_by(event_id=event.id, staff_user_id=target.id).first()
        if not clean:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = PrintStation(event_id=event.id, staff_user_id=target.id)
                db.add(row)
            old = {}
            try:
                old = json.loads(row.settings_json) if row.settings_json else {}
            except ValueError:
                old = {}
            kept = {k: v for k, v in (old if isinstance(old, dict) else {}).items() if k not in MANAGED}      # lo guardado antes no se borra (se ignora)
            row.settings_json, row.updated_at = json.dumps({**kept, **clean}), utcnow()
    db.commit()
    log.info("puesto de impresión %s del evento %s actualizado por el usuario %s", target.id, event.id, staff.id)
    return {"staff_id": target.id, "print_station": bool(target.print_station), "settings": read_station(db, event.id, target.id)}


@router.post("/print-stations/{staff_id}/release")
def release(staff_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Un admin libera la cuenta de un puesto (por ejemplo, cambió de computador): la sesión anterior se cierra y el siguiente inicio de sesión entra. Queda en auditoría."""
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    sessions.force_release(db, target, request)
    return {"released": True}


@router.get("/settings/single-session")
def get_single_session(db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    import os
    return {"enabled": sessions.single_session_on(db), "forced_by_env": os.getenv("SINGLE_SESSION", "").strip() != ""}


@router.put("/settings/single-session")
def put_single_session(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    sessions.set_single_session(db, bool(data.get("enabled")))
    log.info("«Sesión única» %s por el usuario %s", "activada" if data.get("enabled") else "desactivada", staff.id)
    return get_single_session(db, staff)


@router.get("/settings/golden-logo-height")
def get_golden_logo_height(db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    from app import logosize
    return {"height": logosize.get(db), "min": logosize.MIN_H, "max": logosize.MAX_H}


@router.put("/settings/golden-logo-height")
def put_golden_logo_height(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Alto del logo de Golden para TODO el sistema (6-nov-2026): solo el super administrador."""
    from app import logosize
    try:
        wanted = int(data.get("height"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El alto del logo debe ser un número entre 30 y 80")
    if not logosize.MIN_H <= wanted <= logosize.MAX_H:
        raise HTTPException(status_code=400, detail="El alto del logo debe ser un número entre 30 y 80")
    h = logosize.set_height(db, wanted)
    log.info("alto del logo de Golden fijado en %s px por el usuario %s", h, staff.id)
    return {"height": h, "min": logosize.MIN_H, "max": logosize.MAX_H}
