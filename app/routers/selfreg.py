"""Autorregistro sin base de datos (Fase 8, pieza 3): ver app/selfreg.py. La pantalla la abre el personal en el equipo del kiosco; la persona solo ve el formulario mínimo."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import event_rules, selfreg, testperson
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import StaffUser, User
from app.routers import parametros
from app.routers.api import _manual_register

router = APIRouter()
NEUTRAL_HELP = "No pudimos completar tu registro aquí. Acércate al punto de ayuda y con gusto te atienden."


def _state(db: Session, event) -> dict:
    fields, unsupported = selfreg.form_fields(parametros.field_configs_for_event(db, event))
    in_progress = event_rules.allowed(event, "registration")
    available = bool(event.selfreg_enabled) and in_progress and not unsupported
    reason = None
    if not event.selfreg_enabled:
        reason = "off"
    elif not in_progress:
        reason = "closed"
    elif unsupported:
        reason = "unsupported"
    return {"enabled": bool(event.selfreg_enabled), "available": available, "reason": reason, "event_name": event.name, "fields": fields if available else [], "unsupported": unsupported}


@router.get("/events/{event_id}/selfreg/form")
def selfreg_form(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    event = get_event_for_staff(event_id, db, staff)
    return _state(db, event)


@router.post("/events/{event_id}/selfreg")
def selfreg_submit(event_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    event = get_event_for_staff(event_id, db, staff)
    state = _state(db, event)
    if not state["available"]:
        raise HTTPException(status_code=403, detail="El autorregistro no está disponible en este momento. Acércate al punto de ayuda.")
    if not selfreg.allow((event.id, staff.id)):
        raise HTTPException(status_code=429, detail="Hay demasiados registros seguidos en este equipo. Espera unos minutos o acércate al punto de ayuda.")
    cedula = str((data or {}).get("id") or "").strip()
    first = str((data or {}).get("first_name") or "").strip()
    last = str((data or {}).get("last_name") or "").strip()
    if not cedula or not first:
        raise HTTPException(status_code=400, detail="Escribe tu cédula y tu nombre.")
    if testperson.is_test(cedula):                                  # la persona de prueba es del personal, no del autoservicio
        raise HTTPException(status_code=409, detail=NEUTRAL_HELP)
    direct, extras = selfreg.split_values((data or {}).get("values") or {})
    cats = direct.get("categories")
    existing = db.query(User).filter(User.id == cedula, User.tenant_id == event.tenant_id).first()
    if existing is not None:
        # F5-9 B: la cédula ya existe. Solo se marca el ingreso si el nombre coincide, y sin tocar NADA de lo guardado: una fecha de menor borraría su biometría,
        # un correo de escarapela se la entregaría a otra persona. El mensaje es el mismo neutro de siempre (no dice de quién es la cédula).
        if not selfreg.same_person(first, existing.first_name):
            raise HTTPException(status_code=409, detail=NEUTRAL_HELP)
        direct, extras, cats = {k: direct[k] for k in ("role", "entity", "phone", "email", "opt_1") if k in direct}, {}, None
    try:
        reply = _manual_register(
            event_id=event.id, id=cedula, first_name=first, last_name=last,
            role=direct.get("role", ""), entity=direct.get("entity", ""), phone=direct.get("phone", ""), email=direct.get("email", ""), opt_1=direct.get("opt_1", ""),
            extra_fields=json.dumps(extras) if extras else None,
            categories=json.dumps(cats if isinstance(cats, list) else [cats]) if cats else None,
            certificate=direct.get("certificate") or None, digital_contact=direct.get("digital_contact") or None,
            send_digital_now=None if existing is None else "false",
            request=request, field_labels=None, file=None, force=False, biometric_consent=None, birth_date=direct.get("birth_date", "") if existing is None else "",
            db=db, staff=staff, took_ms=None, ui_flow="selfreg", origin="autoregistro", method="autoregistro",
        )
    except HTTPException as e:
        if e.status_code == 409:                                    # p. ej. persona con supresión: no se revela por qué
            raise HTTPException(status_code=409, detail=NEUTRAL_HELP)
        raise
    result = (reply or {}).get("result")
    if result == "DUPLICADO":                                       # ya se había registrado en este evento: nada de sus datos
        return {"status": "already", "message": "Ya quedaste registrado en este evento. ¡Bienvenido!"}
    if result == "NEEDS_LABELS" or (reply or {}).get("error"):
        raise HTTPException(status_code=409, detail=NEUTRAL_HELP)
    return {"status": "ok", "message": "¡Listo! Quedaste registrado. Bienvenido."}


@router.get("/events/{event_id}/selfreg-config")
def get_config(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    event = get_event_for_staff(event_id, db, staff)
    st = _state(db, event)
    return {"enabled": st["enabled"], "unsupported": st["unsupported"], "fields": [f["label"] for f in st["fields"]] if st["available"] or st["enabled"] else []}


@router.put("/events/{event_id}/selfreg-config")
def set_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    event = get_event_for_staff(event_id, db, staff)
    value = bool((data or {}).get("enabled"))
    if value:
        _, unsupported = selfreg.form_fields(parametros.field_configs_for_event(db, event))
        if unsupported:
            raise HTTPException(status_code=400, detail="No se puede activar: estos campos obligatorios no se pueden pedir en la pantalla de autorregistro: " + ", ".join(unsupported) + ". Hazlos opcionales en Parámetros → campos.")
    event.selfreg_enabled = value
    db.commit()
    return {"enabled": value}
