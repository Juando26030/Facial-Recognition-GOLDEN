from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import StaffUser
from app.auth import verify_password

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
    staff = db.query(StaffUser).filter(StaffUser.username == username, StaffUser.is_active == True).first()
    if not staff or not verify_password(password, staff.password_hash):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Usuario o contraseña incorrectos"}, status_code=401,
        )
    request.session.clear()
    request.session["staff_user_id"] = staff.id
    request.session["staff_role"] = staff.role
    request.session["staff_name"] = staff.full_name or staff.username
    request.session["staff_username"] = staff.username
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
