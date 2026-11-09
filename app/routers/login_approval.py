"""Ingreso de digitadores autorizado por el coordinador, y desbloqueo de la cuenta (S1; reglas en app/login_control.py).

Lado del digitador (sin sesión todavía; solo la solicitud en su cookie firmada):
  GET  /ingreso/espera            pantalla «Esperando que el coordinador autorice tu ingreso…»
  POST /api/ingreso/estado        la pantalla pregunta cada ~3 s (solo mientras alguien espera, máximo 5 min). Si el coordinador ya la permitió, AQUÍ se crea la sesión con el mismo
                                  código de /login (`complete_login`) y la solicitud se gasta (un solo uso)
  POST /api/ingreso/cancelar      «Volver»: retira la solicitud
Lado de quien administra las cuentas temporales del evento («Usuarios del evento»):
  GET  /api/events/{id}/staff-users/login-state             quién está bloqueado y quién está intentando ingresar (la pantalla lo pide cada ~10 s mientras está visible)
  POST /api/events/{id}/staff-users/{staff_id}/login-request   {"allow": true|false}
  POST /api/events/{id}/staff-users/approve-all                «Autorizar a todos los pendientes» de ESE evento (solo autorizar; tope APPROVE_ALL_MAX por llamada)
  POST /api/events/{id}/staff-users/{staff_id}/unlock
Sin datos personales en el log; los mensajes al usuario en español."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from datetime import timedelta

from app import audit_actions, login_control, security, staticver
from app.auth import effective_roles, get_event_for_staff, require_role
from app.database import get_db
from app.models import EventStaffAuthorization, RateLimitEvent, StaffUser
from app.timeutil import utcnow

router = APIRouter()
templates = Jinja2Templates(directory="templates")
staticver.install(templates)
NO_STORE = {"Cache-Control": "no-store"}


def _can_manage(staff: StaffUser) -> bool:
    """La misma regla que las cuentas temporales del evento (app/routers/events.py `_can_manage_temp`): coordinador+ salvo la comercial pura."""
    return not effective_roles(staff).issubset({"comercial"})


# ------------------------------------------------------------------------------------------------ el navegador que espera
def _pending_req(request: Request) -> dict:
    req = request.session.get(login_control.SESSION_KEY)
    return req if isinstance(req, dict) and req.get("tok") and isinstance(req.get("uid"), int) else None


@router.get("/ingreso/espera")
def waiting_page(request: Request):
    if not _pending_req(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request=request, name="ingreso_espera.html", context={
        "wait_msg": login_control.WAIT_MSG, "poll_seconds": login_control.POLL_SECONDS, "ttl_seconds": int(login_control.REQUEST_TTL.total_seconds())})


def _answer(status: str, **extra) -> JSONResponse:
    return JSONResponse({"status": status, **extra}, headers=NO_STORE)


def _throttled(request: Request, req) -> bool:
    """Tope de sondeos por solicitud y por IP (sin base de datos). La pantalla legítima pregunta cada 3 s, muy por debajo del tope."""
    ip = security.limit_ip(request)
    if ip is not None and not login_control.poll_allowed("ip:" + ip, login_control.POLL_MAX_PER_IP):
        return True
    if req and not login_control.poll_allowed("tok:" + login_control.token_hash(req["tok"])[:24], login_control.POLL_MAX_PER_TOKEN):
        return True
    return False


def _too_many() -> JSONResponse:
    return JSONResponse({"status": "throttled", "message": "Demasiadas consultas seguidas. Espera un momento."}, status_code=429, headers={**NO_STORE, "Retry-After": "30"})


@router.post("/api/ingreso/estado")
def waiting_status(request: Request, db: Session = Depends(get_db)):
    """`pending` (con `expires_in`), `approved` (con `redirect`: la sesión ya quedó creada), `denied` (con `message`), `expired` o `none` (no hay solicitud de este navegador)."""
    req = _pending_req(request)
    if _throttled(request, req):
        return _too_many()
    if not req:
        return _answer("none", message=login_control.EXPIRED_MSG)
    staff = db.query(StaffUser).filter(StaffUser.id == req["uid"], StaffUser.is_active == True).first()  # noqa: E712
    if staff is None or not login_control.applies(staff) or not login_control.matches(staff, req["tok"]):
        request.session.pop(login_control.SESSION_KEY, None)          # otra solicitud más nueva la reemplazó, ya se usó o la cuenta ya no está: este navegador no puede seguir
        return _answer("none", message=login_control.EXPIRED_MSG)
    if not login_control.request_alive(staff):
        login_control.clear_request(staff)
        db.commit()
        request.session.pop(login_control.SESSION_KEY, None)
        return _answer("expired", message=login_control.EXPIRED_MSG)
    if staff.login_req_status == login_control.DENIED:
        login_control.clear_request(staff)
        db.commit()
        request.session.pop(login_control.SESSION_KEY, None)
        return _answer("denied", message=login_control.DENIED_MSG)
    if staff.login_req_status != login_control.APPROVED:
        return _answer("pending", expires_in=login_control.seconds_left(staff))
    # Permitida: se gasta (UPDATE condicional, un solo uso) y se crea la sesión con el MISMO código de /login.
    if not login_control.consume_approved(db, staff, req["tok"]):
        request.session.pop(login_control.SESSION_KEY, None)
        return _answer("none", message=login_control.EXPIRED_MSG)
    if login_control.is_locked(staff) or (login_control.enabled() and not login_control.has_event_in_progress(db, staff)):
        request.session.pop(login_control.SESSION_KEY, None)
        return _answer("denied", message=login_control.DENIED_MSG)
    from app.routers.auth import complete_login
    target, busy = complete_login(request, db, staff, req.get("psid"))
    if busy:
        request.session.pop(login_control.SESSION_KEY, None)
        return _answer("denied", message=busy)
    security.record_login_ok(db, staff.username, security.limit_ip(request))
    return _answer("approved", redirect=target)


@router.post("/api/ingreso/cancelar")
def waiting_cancel(request: Request, db: Session = Depends(get_db)):
    req = _pending_req(request)
    if _throttled(request, req):
        return _too_many()
    if req:
        staff = db.get(StaffUser, req["uid"])
        if staff is not None and login_control.matches(staff, req["tok"]):
            login_control.clear_request(staff)
            db.commit()
        request.session.pop(login_control.SESSION_KEY, None)
    return _answer("none")


# ------------------------------------------------------------------------------------------------ quien administra las cuentas del evento
def _target(db: Session, staff: StaffUser, event_id: int, staff_id: int):
    if not _can_manage(staff):
        raise HTTPException(status_code=403, detail="Un comercial no puede administrar cuentas digitador")
    event = get_event_for_staff(event_id, db, staff)
    target = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.role == "digitador").first()
    if target is None or not db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=target.id).first():
        raise HTTPException(status_code=404, detail="Esa cuenta no está asignada a este evento")
    return event, target


@router.get("/api/events/{event_id}/staff-users/login-state")
def login_state(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Bloqueos e intentos de ingreso de los digitadores de ESTE evento. Solo quien puede administrarlos ve los intentos (y los botones)."""
    event = get_event_for_staff(event_id, db, staff)
    can = _can_manage(staff)
    rows = (db.query(StaffUser).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
            .filter(EventStaffAuthorization.event_id == event.id, StaffUser.role == "digitador").all())
    now = utcnow()
    accounts = [{"id": s.id, "locked": login_control.is_locked(s), "login_pending": bool(can and login_control.pending(s, now)),
                 "expires_in": login_control.seconds_left(s, now) if can and login_control.pending(s, now) else 0,
                 **({"req": login_control.request_code(s)} if can and login_control.pending(s, now) else {})} for s in rows]
    return JSONResponse({"can_manage": can, "event_in_progress": event.status == "en_proceso", "accounts": accounts}, headers=NO_STORE)


@router.post("/api/events/{event_id}/staff-users/{staff_id}/login-request")
def decide_login(event_id: int, staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event, target = _target(db, staff, event_id, staff_id)
    allow = data.get("allow") is True
    if not login_control.pending(target):
        raise HTTPException(status_code=409, detail="Esa persona ya no está esperando para ingresar (la solicitud venció o ya se respondió)")
    req = data.get("req")
    if req is not None and str(req) != login_control.request_code(target):          # B6: otra solicitud reemplazó a la que el coordinador estaba viendo
        raise HTTPException(status_code=409, detail="La solicitud cambió mientras la mirabas: revisa de nuevo quién está pidiendo entrar")
    if allow and event.status != "en_proceso":
        raise HTTPException(status_code=400, detail="Solo se puede autorizar el ingreso desde un evento en proceso")
    if allow:
        ok, why = login_control.can_approve(db, event, target)
        if not ok:
            raise HTTPException(status_code=409, detail=why)
        if not _approve_one(db, staff, event, target):
            raise HTTPException(status_code=409, detail="Esa persona ya no está esperando para ingresar (la solicitud venció o ya se respondió)")
    else:
        target.login_req_status = login_control.DENIED
    db.commit()
    return {"status": target.login_req_status, "message": "Ingreso autorizado" if allow else "Ingreso no autorizado"}


def _approve_one(db: Session, actor: StaffUser, event, target: StaffUser) -> bool:
    """LA autorización de un ingreso (la usan el botón individual y «Autorizar a todos»): UPDATE condicionado a la misma solicitud pendiente + registro por persona (solo ids). No confirma."""
    if not login_control.approve_if_pending(db, target.id, target.login_req_hash):
        return False
    audit_actions.record(db, actor, "approve", "login_request", target.id, None, f"evento {event.id}")
    target.login_req_status = login_control.APPROVED
    return True


APPROVE_ALL_MAX = 500                  # personas por llamada (30 a la vez es lo normal)
APPROVE_ALL_PER_MINUTE = 6             # llamadas por usuario y minuto


def _approve_all_limited(db: Session, staff: StaffUser) -> bool:
    """Tope por usuario (en Postgres, vale con varios procesos). True si ya llegó al límite; si no, cuenta esta llamada."""
    key = f"staff:{staff.id}"
    since = utcnow() - timedelta(minutes=1)
    hits = db.query(RateLimitEvent.id).filter(RateLimitEvent.kind == "approve_all", RateLimitEvent.key == key, RateLimitEvent.created_at > since).count()
    if hits >= APPROVE_ALL_PER_MINUTE:
        return True
    security.record_event(db, "approve_all", key, None)          # confirma
    return False


@router.post("/api/events/{event_id}/staff-users/approve-all")
def approve_all_pending(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Autoriza de una vez a TODOS los digitadores de ESTE evento que esperan su ingreso. Mismos permisos que el botón individual (coordinador+, no la comercial pura) y mismo requisito
    (evento en proceso). Cada autorización es `_approve_one`; las solicitudes que cambiaron entre medias (ya respondidas, vencidas, reemplazadas) no se tocan. Idempotente: la segunda llamada da 0.
    Responde {approved, skipped, skipped_reasons:{motivo: n}, truncated}."""
    if not _can_manage(staff):
        raise HTTPException(status_code=403, detail="Un comercial no puede administrar cuentas digitador")
    event = get_event_for_staff(event_id, db, staff)
    if event.status != "en_proceso":
        raise HTTPException(status_code=400, detail="Solo se puede autorizar el ingreso desde un evento en proceso")
    if _approve_all_limited(db, staff):
        raise HTTPException(status_code=429, detail="Demasiadas autorizaciones seguidas. Espera un momento.")
    # Filas con bloqueo (orden por id: sin interbloqueos entre dos coordinadores); FOR UPDATE sí es compatible con el pooler de Neon.
    rows = (db.query(StaffUser).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
            .filter(EventStaffAuthorization.event_id == event.id, StaffUser.role == "digitador", StaffUser.login_req_status == login_control.PENDING)
            .order_by(StaffUser.id).limit(APPROVE_ALL_MAX + 1).with_for_update(of=StaffUser).all())
    truncated = len(rows) > APPROVE_ALL_MAX
    now = utcnow()
    approved, reasons = 0, {}

    def skip(why: str):
        reasons[why] = reasons.get(why, 0) + 1

    for target in rows[:APPROVE_ALL_MAX]:
        if not login_control.request_alive(target, now):
            skip("solicitud vencida")
        elif login_control.is_locked(target):
            skip("cuenta bloqueada")
        else:
            ok, why = login_control.can_approve(db, event, target)
            if not ok:
                skip(why or "no cumple los requisitos")
            elif _approve_one(db, staff, event, target):
                approved += 1
            else:
                skip("ya cambió su solicitud")
    skipped = sum(reasons.values())
    audit_actions.record(db, staff, "approve_all", "event_login_requests", event.id, event.name, f"autorizados {approved}; omitidos {skipped}")
    db.commit()
    return {"approved": approved, "skipped": skipped, "skipped_reasons": reasons, "truncated": truncated,
            "message": f"{approved} autorizado(s)" + (f", {skipped} omitido(s)" if skipped else "")}


@router.post("/api/events/{event_id}/staff-users/{staff_id}/unlock")
def unlock_account(event_id: int, staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    _event, target = _target(db, staff, event_id, staff_id)
    login_control.unlock(target)
    db.commit()
    security.clear_events(db, "login_fail", target.username)
    return {"message": f"Cuenta {target.username} desbloqueada"}
