"""Puestos de impresión configurados desde Parámetros (26-oct-2026). La configuración de impresión la define Golden: el digitador no elige, no configura y no conecta nada.

  - Por cada cuenta de puesto y evento se guarda en el SERVIDOR (`print_stations.settings_json`): modo (Controlador de Windows / USB directo / Automático), «imprime sin cuadro», ancho de página,
    calibración (mm), serie de la impresora USB y los parámetros físicos (los mismos de `print_settings`: corte, avance, espejo, recorte…). Los valores del EVENTO son la base y el puesto los sobrescribe.
  - Sin fila para la cuenta, el equipo usa lo de siempre (valores del evento + lo guardado en el navegador): nada cambia en eventos que ya estaban cargados.
  - El puesto, al cargar, lee su configuración (`GET …/print-station/me`) y se aplica sola. Los endpoints de configuración rechazan a los roles sin permiso (CONFIG = coordinador o más, sin comercial).
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
from app.routers import print_settings
from app.timeutil import utcnow

log = logging.getLogger("golden.print_stations")
router = APIRouter()

ADMIN = require_role("admin")
CONFIG = require_role_excluding("coordinador", ("comercial",))
OPERATOR = require_role_excluding("digitador", ("comercial",))
MODES = ("auto", "usb", "driver")


def _num(value, lo: float, hi: float, what: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"«{what}» debe ser un número")
    if not lo <= n <= hi:
        raise HTTPException(status_code=400, detail=f"«{what}» debe estar entre {lo:g} y {hi:g}")
    return round(n, 2)


def sanitize(data: dict) -> dict:
    """Solo claves conocidas y válidas (400 con mensaje claro si algo no cuadra). Lo omitido o `None` = «usar lo del evento / de fábrica»."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="La configuración del puesto no es válida")
    out = {}
    if data.get("mode") is not None:
        if data["mode"] not in MODES:
            raise HTTPException(status_code=400, detail="El modo es Automático, USB directo o Controlador de Windows")
        out["mode"] = data["mode"]
    if data.get("readerOnly") is not None:
        if not isinstance(data["readerOnly"], bool):
            raise HTTPException(status_code=400, detail="«Solo lector» debe ser sí o no")
        out["readerOnly"] = data["readerOnly"]
    if data.get("noDialog") is not None:
        if not isinstance(data["noDialog"], bool):
            raise HTTPException(status_code=400, detail="«Imprime sin cuadro» debe ser sí o no")
        out["noDialog"] = data["noDialog"]
    if data.get("pageWidthMm") not in (None, ""):
        out["pageWidthMm"] = _num(data["pageWidthMm"], 20, 120, "ancho de página (mm)")
    for key, what in (("dx", "calibración horizontal (mm)"), ("dy", "calibración vertical (mm)")):
        if data.get(key) not in (None, ""):
            out[key] = _num(data[key], -5, 5, what)
    if data.get("usbSerial") not in (None, ""):
        out["usbSerial"] = str(data["usbSerial"]).strip()[:40]
    out.update(print_settings.sanitize({k: v for k, v in data.items() if k in print_settings.DEFAULTS}))
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
            row.settings_json, row.updated_at = json.dumps(clean), utcnow()
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
