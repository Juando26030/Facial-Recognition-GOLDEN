"""Valores de impresión de escarapelas POR EVENTO (orden B del 23-oct-2026). Cada equipo puede sobrescribirlos en su panel «⚙️ Impresión» (localStorage); lo que no se sobrescribe sale de aquí.

Se guarda en `Event.print_settings_json` solo lo que se fijó (el resto es «de fábrica»). Los nombres y rangos son los mismos que `QLUsb.PREF_DEFAULTS` / `QLUsb.resolvePrefs` (static/js/ql-usb.js);
`SUPPORTED_TAPES` debe coincidir con `QLUsb.MEDIA` (lo comprueba tests/test_ajustes_impresion.py). No usa el interruptor de impresión compartida: el diseñador y Parámetros lo leen siempre."""
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import StaffUser

log = logging.getLogger("golden.print_settings")
router = APIRouter()
READ = require_role("coordinador")
CONFIG = require_role_excluding("coordinador", ("comercial",))

SUPPORTED_TAPES = (62,)          # anchos de cinta (mm) que sabe imprimir QLUsb.MEDIA; las demás se agregan allá al probarlas con la cinta puesta
# Versión de lo guardado. v2 (24-oct-2026): «Espejo» cambió de significado (static/js/ql-usb.js packRow: antes la etiqueta salía reflejada SIN espejo). Lo guardado sin «v»: 2 es
# del significado viejo y su «mirror» se IGNORA al leer (quien lo activó para compensar quedaría ahora con la etiqueta reflejada). Sin migración de base: es el mismo JSON.
SETTINGS_VERSION = 2
LEGACY_KEYS_V1 = ("mirror",)
DEFAULTS = {"cut": True, "feedMm": 1.5, "lengthMm": None, "mirror": False, "invert": False, "tapeWidth": 62, "tapeType": "continuous", "rotation": "auto", "crop": True, "cropMarginMm": 3}


def _num(value: Any, lo: float, hi: float, what: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"«{what}» debe ser un número")
    if not lo <= n <= hi:
        raise HTTPException(status_code=400, detail=f"«{what}» debe estar entre {lo:g} y {hi:g}")
    return int(n) if n == int(n) else n


def sanitize(data: dict) -> dict:
    """Solo las claves conocidas y válidas; 400 con mensaje claro si algo no cuadra. `None` = «volver al valor de fábrica» (no se guarda)."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Los valores de impresión no son válidos")
    out = {}
    for key in ("cut", "mirror", "invert", "crop"):
        if data.get(key) is not None:
            if not isinstance(data[key], bool):
                raise HTTPException(status_code=400, detail=f"«{key}» debe ser sí o no")
            out[key] = data[key]
    if data.get("feedMm") is not None:
        out["feedMm"] = _num(data["feedMm"], 0, 50, "margen de avance (mm)")
    if data.get("cropMarginMm") is not None:
        out["cropMarginMm"] = _num(data["cropMarginMm"], 0, 30, "margen del recorte (mm)")
    if data.get("lengthMm") not in (None, ""):
        out["lengthMm"] = _num(data["lengthMm"], 10, 1000, "largo de la etiqueta (mm)")
    if data.get("tapeWidth") is not None:
        width = _num(data["tapeWidth"], 1, 1000, "ancho de la cinta (mm)")
        if width not in SUPPORTED_TAPES:
            raise HTTPException(status_code=400, detail=f"Ese ancho de cinta no está soportado todavía. Disponibles: {', '.join(str(t) for t in SUPPORTED_TAPES)} mm")
        out["tapeWidth"] = int(width)
    if data.get("tapeType") is not None:
        if data["tapeType"] not in ("continuous", "diecut"):
            raise HTTPException(status_code=400, detail="El tipo de cinta es «continua» o «troquelada»")
        out["tapeType"] = data["tapeType"]
    if data.get("rotation") is not None:
        rot = data["rotation"]
        if rot != "auto":
            rot = _num(rot, 0, 270, "giro")
            if rot not in (0, 90, 180, 270):
                raise HTTPException(status_code=400, detail="El giro es automático, 0, 90, 180 o 270 grados")
        out["rotation"] = rot
    if out.get("tapeType") == "diecut" and not out.get("lengthMm"):
        raise HTTPException(status_code=400, detail="La cinta troquelada necesita el largo de la etiqueta (mm)")
    return out


def read_settings(event) -> dict:
    """Los valores del evento con el significado ACTUAL (sin la clave de versión; lo de la versión vieja que cambió de significado no se hereda)."""
    try:
        raw = json.loads(event.print_settings_json) if event.print_settings_json else {}
    except ValueError:
        raw = {}
    if not isinstance(raw, dict):
        return {}
    out = {k: v for k, v in raw.items() if k != "v"}
    if raw.get("v") != SETTINGS_VERSION:
        for key in LEGACY_KEYS_V1:
            out.pop(key, None)
    return out


def settings_json(event) -> str:
    """Para la pantalla de Registro (meta gw-print-settings): lo mismo que `read_settings`, en JSON."""
    return json.dumps(read_settings(event))


def stored(clean: dict) -> str:
    return json.dumps({"v": SETTINGS_VERSION, **clean}) if clean else None


def job_prefs(data) -> dict | None:
    """Parámetros que manda el equipo que pide una impresión compartida (ya resueltos allá). Se validan con las mismas reglas que los del evento; si algo no cuadra, el pedido sigue
    adelante con los del evento (nunca se bloquea una impresión por esto)."""
    if not isinstance(data, dict) or not data:
        return None
    try:
        clean = sanitize(data)
    except HTTPException:
        log.warning("impresión compartida: parámetros del equipo no válidos; se usan los del evento")
        return None
    return clean or None


@router.get("/events/{event_id}/print-settings")
def get_settings(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(READ)):
    event = get_event_for_staff(event_id, db, staff)
    return {"settings": read_settings(event), "defaults": DEFAULTS, "supported_tapes": list(SUPPORTED_TAPES)}


@router.put("/events/{event_id}/print-settings")
def put_settings(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG)):
    """Reemplaza los valores del evento por los enviados (lo omitido o `null` vuelve al valor de fábrica). `{}` = restablecer todo."""
    event = get_event_for_staff(event_id, db, staff)
    clean = sanitize(data.get("settings") if isinstance(data.get("settings"), dict) else data)
    event.print_settings_json = stored(clean)
    db.commit()
    log.info("valores de impresión del evento %s actualizados por el usuario %s (%s claves)", event.id, staff.id, len(clean))
    return {"settings": clean, "defaults": DEFAULTS, "supported_tapes": list(SUPPORTED_TAPES)}
