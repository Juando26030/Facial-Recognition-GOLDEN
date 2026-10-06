"""Solicitudes de privacidad (consultas y reclamos, Ley 1581): radicado AÑO-CONSECUTIVO (2026-0001), fecha límite en días HÁBILES (consulta 10, reclamo 15; la bandera «reclamo en trámite» se activa en
máximo 2 días hábiles) y registro de cada cambio. Los festivos de Colombia se leen de `HOLIDAYS_CO` (fechas AAAA-MM-DD separadas por coma; por defecto los de 2026: confirmar cada año)."""
import json
import os
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import PrivacyRequest
from app.timeutil import utcnow

CHANNELS = ("email", "presencial", "web", "telefono", "otro")
TYPES = ("consulta", "reclamo", "actualizacion", "supresion", "revocacion", "prueba_autorizacion")
STATUSES = ("recibida", "en_tramite", "resuelta", "rechazada")
DUE_BUSINESS_DAYS = {"consulta": 10, "prueba_autorizacion": 10, "reclamo": 15, "actualizacion": 15, "supresion": 15, "revocacion": 15}
FLAG_BUSINESS_DAYS = 2
_HOLIDAYS_2026 = "2026-01-01,2026-01-12,2026-03-23,2026-04-02,2026-04-03,2026-05-01,2026-05-18,2026-06-08,2026-06-15,2026-06-29,2026-07-20,2026-08-07,2026-08-17,2026-10-12,2026-11-02,2026-11-16,2026-12-08,2026-12-25"


def holidays() -> set:
    raw = os.getenv("HOLIDAYS_CO") or _HOLIDAYS_2026
    out = set()
    for part in raw.split(","):
        try:
            out.add(date.fromisoformat(part.strip()))
        except ValueError:
            pass
    return out


def add_business_days(start: date, n: int) -> date:
    """`start` + n días hábiles (sin sábados, domingos ni festivos); el día de la solicitud no cuenta."""
    day, hol, left = start, holidays(), n
    while left > 0:
        day += timedelta(days=1)
        if day.weekday() < 5 and day not in hol:
            left -= 1
    return day


def next_radicado(db: Session, year: Optional[int] = None) -> str:
    """AÑO-CONSECUTIVO atómico (2026-0001): un solo INSERT...ON CONFLICT...RETURNING, sin carreras entre procesos."""
    year = year or utcnow().year
    last = db.execute(text("INSERT INTO privacy_request_counters (year, last) VALUES (:y, 1) ON CONFLICT (year) DO UPDATE SET last = privacy_request_counters.last + 1 RETURNING last"), {"y": year}).scalar()
    return f"{year}-{last:04d}"


def _log(req: PrivacyRequest, who: Optional[int], action: str) -> None:
    hist = json.loads(req.history_json or "[]")
    hist.append({"at": utcnow().isoformat(timespec="seconds") + "Z", "by": who, "action": action})
    req.history_json = json.dumps(hist, ensure_ascii=False)


def create(db: Session, *, channel: str, holder_name: str, cedula: str, request_type: str, tenant_id: Optional[str], event_id: Optional[int], staff_id: Optional[int],
           received: Optional[date] = None) -> PrivacyRequest:
    received = received or utcnow().date()
    req = PrivacyRequest(radicado=next_radicado(db, received.year), channel=channel, holder_name=holder_name.strip(), cedula=cedula.strip(), request_type=request_type, tenant_id=tenant_id,
                         event_id=event_id, due_date=add_business_days(received, DUE_BUSINESS_DAYS[request_type]), status="recibida", created_by_staff_id=staff_id,
                         claim_flag_due=add_business_days(received, FLAG_BUSINESS_DAYS) if request_type != "consulta" else None)
    _log(req, staff_id, f"Radicada ({request_type}, canal {channel})")
    db.add(req)
    return req


def set_status(req: PrivacyRequest, status: str, staff_id: Optional[int]) -> None:
    req.status = status
    if status in ("resuelta", "rechazada"):
        req.claim_flag = False                       # resuelto el reclamo, se quita la leyenda
    _log(req, staff_id, f"Estado: {status}")


def set_claim_flag(req: PrivacyRequest, active: bool, staff_id: Optional[int]) -> None:
    req.claim_flag = bool(active)
    _log(req, staff_id, "Bandera «reclamo en trámite» " + ("ACTIVADA" if active else "quitada"))


def open_claim(db: Session, cedula: str) -> Optional[PrivacyRequest]:
    """El reclamo con la bandera activa sobre esa cédula (para mostrar la leyenda), si lo hay."""
    return db.query(PrivacyRequest).filter(PrivacyRequest.cedula == cedula.strip(), PrivacyRequest.claim_flag.is_(True)).order_by(PrivacyRequest.id.desc()).first()


def as_dict(r: PrivacyRequest, today: Optional[date] = None) -> dict:
    today = today or utcnow().date()
    open_ = r.status in ("recibida", "en_tramite")
    return {"id": r.id, "radicado": r.radicado, "created_at": r.created_at.isoformat() if isinstance(r.created_at, datetime) else None, "channel": r.channel, "holder_name": r.holder_name, "cedula": r.cedula,
            "event_id": r.event_id, "request_type": r.request_type, "due_date": r.due_date.isoformat(), "status": r.status, "overdue": bool(open_ and r.due_date < today),
            "claim_flag": r.claim_flag, "claim_flag_due": r.claim_flag_due.isoformat() if r.claim_flag_due else None,
            "claim_flag_overdue": bool(open_ and r.claim_flag_due and not r.claim_flag and r.claim_flag_due < today), "history": json.loads(r.history_json or "[]")}
