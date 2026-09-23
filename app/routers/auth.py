import os
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.mailer import send_mail
from app.models import StaffUser
from app.auth import hash_password, verify_password
from app import security

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login_form(request: Request):
    if request.session.get("staff_user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = security.client_ip(request)
    username = username.strip()
    # Bloqueo temporal tras varios fallos (por usuario y por IP). Se aplica igual exista o no la cuenta,
    # y el mensaje no dice cuál de las dos cosas falló.
    wait = security.login_minutes_locked(db, username, ip)
    if wait:
        return templates.TemplateResponse(
            request=request, name="login.html", status_code=429,
            context={"error": f"Demasiados intentos fallidos. Espera {wait} minuto(s) e intenta de nuevo."},
        )
    staff = db.query(StaffUser).filter(StaffUser.username == username, StaffUser.is_active == True).first()
    if not staff or not verify_password(password, staff.password_hash):
        security.record_event(db, "login_fail", username, ip)
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Usuario o contraseña incorrectos"}, status_code=401,
        )
    security.clear_events(db, "login_fail", username)
    request.session.clear()
    request.session["staff_user_id"] = staff.id
    request.session["staff_role"] = staff.role
    request.session["staff_secondary_role"] = staff.secondary_role  # Sprint 2.4 Fase 15: doble rol coordinador+comercial
    request.session["staff_name"] = staff.full_name or staff.username
    request.session["staff_username"] = staff.username
    if staff.must_change_password:
        request.session["must_change_password"] = True
        return RedirectResponse("/cambiar-contrasena", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


def _page(request: Request, mode: str, error: str = None, message: str = None, token: str = None, status_code: int = 200):
    return templates.TemplateResponse(request=request, name="password.html", status_code=status_code,
                                      context={"mode": mode, "error": error, "message": message, "token": token})


@router.get("/olvide-contrasena")
async def forgot_form(request: Request):
    return _page(request, "forgot")


@router.post("/olvide-contrasena")
async def forgot_submit(request: Request, username: str = Form(...), db: Session = Depends(get_db)):
    """Manda un enlace de un solo uso al correo de la cuenta. La respuesta es SIEMPRE la misma (exista la
    cuenta, tenga o no correo) para no revelar qué usuarios existen; las cuentas sin correo (ej. los
    digitadores temporales) las restablece un admin/coordinador."""
    ip = security.client_ip(request)
    username = username.strip()
    generic = "Si la cuenta existe y tiene un correo registrado, te enviamos un enlace para elegir una contraseña nueva (vale 60 minutos)."
    if security.minutes_locked(db, "reset_request", username, ip, security.RESET_MAX_REQUESTS, security.RESET_MAX_REQUESTS * 4, security.RESET_WINDOW):
        return _page(request, "forgot", error="Demasiadas solicitudes. Intenta de nuevo más tarde.", status_code=429)
    security.record_event(db, "reset_request", username, ip)
    staff = db.query(StaffUser).filter(func.lower(StaffUser.username) == username.lower(), StaffUser.is_active == True).first()
    if staff and staff.email:
        token = security.create_reset_token(db, staff.id)
        base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
        send_mail(
            staff.email, "Restablecer tu contraseña — Golden Biometrics",
            f"Hola {staff.full_name or staff.username}, recibimos una solicitud para elegir una contraseña nueva.\n\n"
            f"Abre este enlace (vale 60 minutos y solo se puede usar una vez):\n{base}/restablecer/{token}\n\n"
            "Si no fuiste tú, ignora este correo: tu contraseña actual sigue igual.",
        )
    return _page(request, "forgot", message=generic)


@router.get("/restablecer/{token}")
async def reset_form(token: str, request: Request, db: Session = Depends(get_db)):
    if not security.find_valid_reset_token(db, token):
        return _page(request, "invalid", status_code=410)
    return _page(request, "reset", token=token)


@router.post("/restablecer/{token}")
async def reset_submit(
    token: str, request: Request, password: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db),
):
    row = security.find_valid_reset_token(db, token)
    if not row:
        return _page(request, "invalid", status_code=410)
    problem = security.password_problem(password) or (None if password == confirm else "Las contraseñas no coinciden")
    if problem:
        return _page(request, "reset", error=problem, token=token, status_code=400)
    staff = db.query(StaffUser).filter(StaffUser.id == row.staff_user_id).first()
    staff.password_hash = hash_password(password)
    staff.must_change_password = False
    row.used_at = datetime.utcnow()
    db.commit()
    security.clear_events(db, "login_fail", staff.username)
    return _page(request, "done", message="Listo, tu contraseña quedó cambiada. Ya puedes ingresar.")


@router.get("/cambiar-contrasena")
async def change_form(request: Request):
    if not request.session.get("staff_user_id"):
        return RedirectResponse("/login", status_code=302)
    msg = "Debes elegir tu propia contraseña para continuar." if request.session.get("must_change_password") else None
    return _page(request, "change", message=msg)


@router.post("/cambiar-contrasena")
async def change_submit(
    request: Request, current: str = Form(...), password: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db),
):
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        return RedirectResponse("/login", status_code=302)
    staff = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()
    if not staff or not verify_password(current, staff.password_hash):
        return _page(request, "change", error="La contraseña actual no es correcta", status_code=400)
    problem = security.password_problem(password) or (None if password == confirm else "Las contraseñas no coinciden")
    if not problem and verify_password(password, staff.password_hash):
        problem = "La contraseña nueva debe ser distinta a la actual"
    if problem:
        return _page(request, "change", error=problem, status_code=400)
    staff.password_hash = hash_password(password)
    staff.must_change_password = False
    db.commit()
    request.session.pop("must_change_password", None)
    return RedirectResponse("/", status_code=302)
