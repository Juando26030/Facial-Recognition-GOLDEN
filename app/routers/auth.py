import os
import secrets
from datetime import datetime
from app.timeutil import utcnow

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import publicurl, staticver
from app.database import get_db
from app.mailer import send_mail
from app.models import StaffUser
from app import localmode
from app.auth import all_extra_roles, get_current_staff, hash_password, verify_password
from app import idle, login_control, pledge, security, sessions

router = APIRouter()
templates = Jinja2Templates(directory="templates")
staticver.install(templates)


@router.get("/login")
def login_form(request: Request):
    if request.session.get("staff_user_id"):
        return RedirectResponse("/", status_code=302)
    notice = "Tu sesión se cerró por inactividad. Ingresa de nuevo para continuar." if request.query_params.get("expirada") else None
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "notice": notice})


GENERIC_LOGIN_ERROR = "Usuario o contraseña incorrectos"
_dummy_hash = None


def _dummy_verify(password: str) -> None:
    """S6: si el usuario no existe se compara igual contra un hash bcrypt de relleno, para que el tiempo de respuesta no diga qué usuarios existen."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(16))
    verify_password(password, _dummy_hash)


def _login_page(request: Request, error: str, status_code: int, error_body: str = None):
    return templates.TemplateResponse(request=request, name="login.html", status_code=status_code, context={"error": error, "error_body": error_body})


def complete_login(request: Request, db: Session, staff: StaffUser, prev_sid=None):
    """Crea la sesión del personal (lo ÚNICO que lo hace: /login y la autorización del coordinador en app/routers/login_approval.py). Devuelve (destino, None) o (None, mensaje)
    si la sesión se rechaza (puesto de impresión en uso, app/sessions.py)."""
    busy = sessions.login_gate(db, request, staff, prev_sid)      # puesto de impresión en uso: se rechaza (sesión única / protegida; ver app/sessions.py)
    if busy:
        return None, busy
    sid = request.session.get("sid")                # login_gate lo dejó en la sesión actual; se conserva al limpiarla
    request.session.clear()                         # nada de la sesión anterior pasa a la nueva (ni una solicitud de ingreso pendiente)
    if sid:
        request.session["sid"] = sid
    request.session["ep"] = int(staff.session_epoch or 0)         # S2: época de sesión de la cuenta (cambiar/restablecer la contraseña la sube)
    request.session["staff_user_id"] = staff.id
    request.session["staff_role"] = staff.role
    request.session["staff_secondary_role"] = ",".join(all_extra_roles(staff)) or None  # Fase 15 + 0103: los roles que se suman al principal (coma); las páginas lo leen con auth.split_roles
    request.session["staff_name"] = staff.full_name or staff.username
    request.session["staff_username"] = staff.username
    request.session["tours_off"] = bool(staff.tours_auto_off)   # preferencia de la CUENTA: vale igual en cualquier dispositivo
    idle.start(request.session, db, staff)           # inactividad: marca la última actividad (y exime a los puestos de impresión)
    if staff.must_change_password and staff.role != "digitador" and not localmode.is_local_server():       # en un servidor local la contraseña no se cambia (solo en la nube): no se obliga       # el digitador temporal nunca cambia contraseña (Fase 4)
        request.session["must_change_password"] = True
        return "/cambiar-contrasena", None
    return "/", None


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = security.limit_ip(request)                 # None = IP de Google: solo cuenta el límite por usuario
    username = username.strip()
    # Bloqueo temporal tras varios fallos (0C-C7: por PAR usuario+IP, por IP y un tope global alto por usuario). Se aplica igual exista o no la cuenta,
    # y el mensaje no dice cuál de las dos cosas falló.
    wait = security.login_minutes_locked(db, username, ip)
    if wait:
        return _login_page(request, f"Demasiados intentos fallidos. Espera {wait} minuto(s) e intenta de nuevo.", 429)
    staff = db.query(StaffUser).filter(StaffUser.username == username, StaffUser.is_active == True).first()
    if login_control.applies(staff) and login_control.is_locked(staff):          # S1 (b): digitador bloqueado tras 3 fallos
        return _login_page(request, login_control.LOCKED_MSG, 403, "Solo el coordinador del evento puede desbloquearla desde «Usuarios del evento».")
    security.record_event(db, "login_fail", username, ip)       # S5: el intento se anota ANTES de bcrypt (peticiones en paralelo ya cuentan); si sale bien se borra abajo
    if staff is None:
        _dummy_verify(password)
        return _login_page(request, GENERIC_LOGIN_ERROR, 401)
    if not verify_password(password, staff.password_hash):
        if login_control.applies(staff) and login_control.register_fail(db, staff):
            return _login_page(request, login_control.LOCKED_MSG, 403, "Solo el coordinador del evento puede desbloquearla desde «Usuarios del evento».")
        return _login_page(request, GENERIC_LOGIN_ERROR, 401)
    if login_control.applies(staff) and login_control.enabled():
        # S1 (a): sin un evento EN PROCESO asignado, el mismo error genérico (la cédula sola no abre nada). El intento queda anotado como fallido.
        if not login_control.has_event_in_progress(db, staff):
            return _login_page(request, GENERIC_LOGIN_ERROR, 401)
        # Fase 4: si la cuenta está en un evento en proceso que exige el compromiso digital y no lo ha firmado, ANTES de la fila de espera va al formulario del compromiso (el del motor de formularios, ya identificada).
        missing = pledge.missing_for_login(db, staff)
        if missing is not None:
            link = pledge.begin_session_flow(request, db, staff, missing, request.session.get("sid"))
            if link is None:
                return _login_page(request, "Debes firmar el compromiso de tu evento, pero todavía no está disponible. Avisa a tu coordinador.", 403)
            login_control.reset_fails(staff)
            db.commit()
            security.clear_events(db, "login_fail", username)
            return RedirectResponse(link, status_code=303)
        # S1 (c): la contraseña es correcta, pero la sesión NO se crea todavía: queda una solicitud que el coordinador permite o no («Usuarios del evento»).
        login_control.reset_fails(staff)
        token = login_control.new_request(staff)
        db.commit()
        security.clear_events(db, "login_fail", username)
        prev_sid = request.session.get("sid")
        request.session.clear()
        request.session[login_control.SESSION_KEY] = {"uid": staff.id, "tok": token, "psid": prev_sid}     # el token solo vive en la cookie firmada de ESTE navegador
        return RedirectResponse("/ingreso/espera", status_code=303)
    if login_control.applies(staff) and staff.failed_logins:
        login_control.reset_fails(staff)
        db.commit()
    security.clear_events(db, "login_fail", username)       # el login correcto limpia TODOS los fallos del usuario (de cualquier IP)
    security.record_login_ok(db, username, ip)              # S3: IP conocida de esta cuenta (el tope global por usuario no la frena)
    target, busy = complete_login(request, db, staff, request.session.get("sid"))
    if busy:
        return _login_page(request, busy, 403)
    return RedirectResponse(target, status_code=302)


@router.get("/api/session/idle")
def session_idle(request: Request):
    """Cuánto le queda a esta sesión antes de cerrarse por inactividad. Pasivo: NO la renueva (la página lo usa para saber cuándo avisar). Sin tocar la base."""
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    return JSONResponse(idle.snapshot(request.session), headers={"Cache-Control": "no-store"})


@router.post("/api/session/touch")
def session_touch(request: Request):
    """La persona hizo algo (clic, teclas, toque, scroll): el middleware ya renovó la sesión; aquí se devuelve lo que le queda. Sin tocar la base."""
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    return JSONResponse(idle.snapshot(request.session), headers={"Cache-Control": "no-store"})


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    staff_id, sid = request.session.get("staff_user_id"), request.session.get("sid")
    if staff_id:
        staff = db.get(StaffUser, staff_id)
        if staff is not None:
            if sid and staff.session_token == sid:      # al cerrar sesión la cuenta queda libre (un puesto puede volver a entrar sin esperar)
                staff.session_token = sessions.logout_token()      # S2: NULL volvía a dar por buenas las cookies viejas (también las reemplazadas); este valor no coincide con ninguna
            if staff.role in sessions.MULTI_ROLES and int(request.session.get("ep") or 0) == int(staff.session_epoch or 0):
                sessions.revoke_all(staff)          # B7: admin/super_admin no tienen `sid`; subir la época invalida toda copia de la cookie (y cierra también sus otras sesiones, que es lo esperable de «cerrar sesión»)
            db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


def _page(request: Request, mode: str, error: str = None, message: str = None, token: str = None, status_code: int = 200):
    return templates.TemplateResponse(request=request, name="password.html", status_code=status_code,
                                      context={"mode": mode, "error": error, "message": message, "token": token, "policy": security.password_policy(strict=False),
                                               "username": request.session.get("staff_username") if mode == "change" else None})


@router.get("/api/password-policy")
def password_policy(strict: int = 0):
    """Requisitos de contraseña (misma lista que aplica el servidor). `strict=1`: contraseñas que fija un administrador (10+ caracteres, letra y número). Sin datos de nadie."""
    return security.password_policy(strict=bool(strict))


@router.get("/olvide-contrasena")
def forgot_form(request: Request):
    if localmode.is_local_server():
        return _page(request, "forgot", error=localmode.PASSWORD_ONLY_CLOUD, status_code=403)
    return _page(request, "forgot")


@router.post("/olvide-contrasena")
def forgot_submit(request: Request, username: str = Form(...), db: Session = Depends(get_db)):
    localmode.assert_passwords_allowed()
    """Manda un enlace de un solo uso al correo de la cuenta. La respuesta es SIEMPRE la misma (exista la
    cuenta, tenga o no correo) para no revelar qué usuarios existen; las cuentas sin correo (ej. los
    digitadores temporales) las restablece un admin/coordinador."""
    ip = security.limit_ip(request)
    username = username.strip()
    generic = "Si la cuenta existe y tiene un correo registrado, te enviamos un enlace para elegir una contraseña nueva (vale 60 minutos)."
    # S3: con el límite lleno la respuesta es la MISMA (sin correo): un 429 decía que esa cuenta recibía solicitudes y servía para medir el bloqueo.
    if security.minutes_locked(db, "reset_request", username, ip, security.RESET_MAX_REQUESTS, security.RESET_MAX_REQUESTS * 4, security.RESET_WINDOW):
        return _page(request, "forgot", message=generic)
    security.record_event(db, "reset_request", username, ip)
    # S6 (pendiente, documentado en docs/SEGURIDAD_SESIONES.md): el correo sale dentro de la petición, así que tarda más cuando la cuenta existe y tiene correo. No se
    # pasa a app/jobs.py porque el enlace (token en claro) quedaría guardado en la tabla `jobs`; el límite por usuario/IP acota cuánto se puede medir.
    staff = db.query(StaffUser).filter(func.lower(StaffUser.username) == username.lower(), StaffUser.is_active == True).first()
    if staff and staff.email:
        token = security.create_reset_token(db, staff.id)
        base = publicurl.base(str(request.base_url))
        send_mail(
            staff.email, "Restablecer tu contraseña — GoldenWeb 2.0",
            f"Hola {staff.full_name or staff.username}, recibimos una solicitud para elegir una contraseña nueva.\n\n"
            f"Abre este enlace (vale 60 minutos y solo se puede usar una vez):\n{base}/restablecer/{token}\n\n"
            "Si no fuiste tú, ignora este correo: tu contraseña actual sigue igual.",
        )
    return _page(request, "forgot", message=generic)


@router.get("/restablecer/{token}")
def reset_form(token: str, request: Request, db: Session = Depends(get_db)):
    if localmode.is_local_server():
        return _page(request, "invalid", error=localmode.PASSWORD_ONLY_CLOUD, status_code=403)
    if not security.find_valid_reset_token(db, token):
        return _page(request, "invalid", status_code=410)
    return _page(request, "reset", token=token)


@router.post("/restablecer/{token}")
def reset_submit(
    token: str, request: Request, password: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db),
):
    localmode.assert_passwords_allowed()
    row = security.find_valid_reset_token(db, token)
    if not row:
        return _page(request, "invalid", status_code=410)
    staff_row = db.query(StaffUser).filter(StaffUser.id == row.staff_user_id).first()
    problem = security.password_problem(password, staff_row.username if staff_row else None) or (None if password == confirm else "Las contraseñas no coinciden")
    if problem:
        return _page(request, "reset", error=problem, token=token, status_code=400)
    staff = db.query(StaffUser).filter(StaffUser.id == row.staff_user_id).first()
    staff.password_hash = hash_password(password)
    staff.must_change_password = False
    sessions.revoke_all(staff)              # S2: toda cookie emitida antes del restablecimiento deja de valer (también la de un atacante)
    row.used_at = utcnow()
    db.commit()
    security.clear_events(db, "login_fail", staff.username)
    return _page(request, "done", message="Listo, tu contraseña quedó cambiada. Ya puedes ingresar.")


@router.get("/cambiar-contrasena")
def change_form(request: Request):
    if localmode.is_local_server():
        return RedirectResponse("/", status_code=302)
    if not request.session.get("staff_user_id"):
        return RedirectResponse("/login", status_code=302)
    msg = "Debes elegir tu propia contraseña para continuar." if request.session.get("must_change_password") else None
    return _page(request, "change", message=msg)


@router.post("/cambiar-contrasena")
def change_submit(
    request: Request, current: str = Form(...), password: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db),
):
    localmode.assert_passwords_allowed()
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        return RedirectResponse("/login", status_code=302)
    staff = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()
    if not staff:
        return _page(request, "change", error="La contraseña actual no es correcta", status_code=400)
    ip = security.limit_ip(request)
    wait = security.login_minutes_locked(db, staff.username, ip)          # S7: la contraseña actual tiene el mismo límite de intentos que el login
    if wait:
        return _page(request, "change", error=f"Demasiados intentos fallidos. Espera {wait} minuto(s) e intenta de nuevo.", status_code=429)
    if not verify_password(current, staff.password_hash):
        security.record_event(db, "login_fail", staff.username, ip)
        return _page(request, "change", error="La contraseña actual no es correcta", status_code=400)
    problem = security.password_problem(password, staff.username) or (None if password == confirm else "Las contraseñas no coinciden")
    if not problem and verify_password(password, staff.password_hash):
        problem = "La contraseña nueva debe ser distinta a la actual"
    if problem:
        return _page(request, "change", error=problem, status_code=400)
    staff.password_hash = hash_password(password)
    staff.must_change_password = False
    sessions.revoke_others(request, staff)          # S2: las demás sesiones de la cuenta dejan de valer; esta sigue
    db.commit()
    request.session.pop("must_change_password", None)
    return RedirectResponse("/", status_code=302)


@router.put("/api/me/tours-auto-off")
def set_tours_auto_off(data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """«Deshabilitar demos automáticas»: se guarda en la cuenta (así vale en el celular y en el computador) y en la sesión actual. Las guías a mano siguen funcionando."""
    staff.tours_auto_off = bool(data.get("off"))
    db.commit()
    request.session["tours_off"] = bool(staff.tours_auto_off)
    return {"off": bool(staff.tours_auto_off)}
