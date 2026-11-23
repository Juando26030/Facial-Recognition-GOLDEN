"""Capa «empresa» del SaaS, primera pieza (22-nov-2026, docs/27_SAAS_EMPRESAS.md): todo lo que antes se hacía «desde código» se hace aquí, dentro de la app.

`router` (prefijo /api/platform, solo super_admin): empresas (listar, crear, editar, suspender, reactivar), su primer administrador (contraseña temporal generada aquí, mostrada una vez) y su
consumo contra los límites del plan. La pantalla es /plataforma (app/main.py).
El primer arranque sin scripts (/instalar) se retiró el 22-nov-2026 por decisión de Juan David: el primer super_admin se crea con scripts/create_staff_user.py."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_actions, localmode, orgs
from app.auth import hash_password, require_super_admin
from app.database import get_db
from app.inputcheck import check_text, check_username
from app.models import Organization, StaffUser

router = APIRouter(prefix="/api/platform")

EDITABLE = ("name", "legal_name", "nit", "contact_email", "contact_phone", "notes")
_LIMITS = {"name": 200, "legal_name": 200, "nit": 40, "contact_email": 200, "contact_phone": 40, "notes": 4000}
_LABELS = {"name": "El nombre", "legal_name": "La razón social", "nit": "El NIT", "contact_email": "El correo", "contact_phone": "El teléfono", "notes": "Las notas", "slug": "El identificador"}


def _cloud_only() -> None:
    if localmode.is_local_server():
        raise HTTPException(status_code=403, detail="Las empresas se administran en la nube, no en un servidor local")


def _clean_fields(data: dict, keys) -> dict:
    """Textos de la empresa: sin «<», «>» ni caracteres de control y dentro del tope de la columna."""
    out = {}
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{_LABELS[key]} debe ser texto")
        try:
            check_text(value, _LABELS[key])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        out[key] = (value or "").strip()[:_LIMITS.get(key, 200)]
    email = out.get("contact_email")
    if email and ("@" not in email or " " in email):
        raise HTTPException(status_code=400, detail="Escribe un correo válido (por ejemplo: contacto@empresa.com)")
    return out


def _org_or_404(db: Session, org_id: int) -> Organization:
    org = orgs.get_org(db, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return org


def _with_usage(db: Session, org: Organization) -> dict:
    return {**orgs.serialize(org), "usage": orgs.usage(db, org)}


def _new_admin(db: Session, org: Organization, data: dict, staff: StaffUser):
    """Crea el administrador con una contraseña temporal generada aquí. Devuelve (cuenta, contraseña en claro para mostrarla UNA vez)."""
    try:
        username = check_username(str(data.get("username") or ""))
        check_text(data.get("full_name"), "El nombre")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    full_name = str(data.get("full_name") or "").strip()
    if len(full_name) < 3:
        raise HTTPException(status_code=400, detail="Escribe el nombre completo del administrador")
    email = str(data.get("email") or "").strip()
    if not email or "@" not in email or " " in email:
        raise HTTPException(status_code=400, detail="Escribe el correo del administrador: lo necesita para recuperar su contraseña")
    phone = str(data.get("phone") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="El teléfono es obligatorio para esta cuenta")
    password = orgs.temp_password()
    try:
        admin = orgs.create_admin(db, org, username, full_name, email, hash_password(password), phone=phone, created_by=staff)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_actions.record(db, staff, "create", "org_admin", admin.id, entity_name=org.name, detail=f"org_id={org.id}")
    return admin, password


def _admin_payload(admin: StaffUser, password: str) -> dict:
    return {"id": admin.id, "username": admin.username, "full_name": admin.full_name, "temp_password": password,
            "notice": "Copia esta contraseña ahora: no se vuelve a mostrar. La persona debe cambiarla en su primer ingreso."}


@router.get("/catalog")
def platform_catalog(staff: StaffUser = Depends(require_super_admin)):
    """Planes, límites de fábrica y textos de ayuda (sin base)."""
    return orgs.catalog()


@router.get("/orgs")
def list_orgs(db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Todas las empresas con su consumo (eventos del mes, usuarios activos, asistentes) y sus límites vigentes."""
    orgs.golden(db)
    db.commit()
    rows = db.query(Organization).order_by(Organization.id).all()
    return {"orgs": [_with_usage(db, o) for o in rows], **orgs.catalog()}


@router.post("/orgs")
def create_org(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Crea una empresa. Con `admin` ({username, full_name, email, phone}) crea también su primer administrador en la misma transacción."""
    _cloud_only()
    fields = _clean_fields(data, EDITABLE + ("slug",))
    payload = {**fields, "plan": data.get("plan"), "entitlements": data.get("entitlements")}
    try:
        org = orgs.create_org(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_actions.record(db, staff, "create", "organization", org.id, entity_name=org.name, detail=f"plan={org.plan}")
    admin_out = None
    if isinstance(data.get("admin"), dict):
        admin, password = _new_admin(db, org, data["admin"], staff)
        admin_out = _admin_payload(admin, password)
    db.commit()
    db.refresh(org)
    return {**_with_usage(db, org), "admin": admin_out}


@router.patch("/orgs/{org_id}")
def update_org(org_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Edita los datos, el plan y los límites propios. Golden (empresa 1) no cambia de plan ni recibe límites: es la cuenta interna."""
    _cloud_only()
    org = _org_or_404(db, org_id)
    fields = _clean_fields(data, EDITABLE)
    if "name" in fields and len(fields["name"]) < 2:
        raise HTTPException(status_code=400, detail="Escribe el nombre de la empresa")
    for key, value in fields.items():
        setattr(org, key, value or (None if key != "name" else org.name))
    if "plan" in data or "entitlements" in data:
        if orgs.is_internal(org):
            raise HTTPException(status_code=400, detail="Golden es la cuenta interna: no tiene plan ni límites")
        if "plan" in data:
            if data["plan"] not in orgs.SELLABLE_PLANS:
                raise HTTPException(status_code=400, detail="Elige un plan: Básico, Pro o Empresa")
            org.plan = data["plan"]
        if "entitlements" in data:
            try:
                own = orgs.clean_entitlements(data["entitlements"])
            except (ValueError, AttributeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Los límites no tienen el formato esperado")
            org.entitlements_json = json.dumps(own) if own else None
    audit_actions.record(db, staff, "update", "organization", org.id, entity_name=org.name, detail=f"plan={org.plan}")
    db.commit()
    db.refresh(org)
    return _with_usage(db, org)


def _set_status(org_id: int, status: str, db: Session, staff: StaffUser) -> dict:
    _cloud_only()
    org = _org_or_404(db, org_id)
    if orgs.is_internal(org):
        raise HTTPException(status_code=400, detail="Golden es la cuenta interna: no se puede suspender")
    org.status = status
    audit_actions.record(db, staff, "suspend" if status == "suspended" else "reactivate", "organization", org.id, entity_name=org.name)
    db.commit()
    db.refresh(org)
    return _with_usage(db, org)


@router.post("/orgs/{org_id}/suspend")
def suspend_org(org_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Suspende la empresa: no puede crear eventos ni cuentas nuevas. No borra nada y se puede reactivar."""
    return _set_status(org_id, "suspended", db, staff)


@router.post("/orgs/{org_id}/reactivate")
def reactivate_org(org_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    return _set_status(org_id, "active", db, staff)


@router.post("/orgs/{org_id}/admin")
def create_org_admin(org_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Primer administrador de la empresa: rol admin, contraseña temporal generada en el servidor (se muestra una sola vez) y cambio obligatorio al primer ingreso."""
    _cloud_only()
    org = _org_or_404(db, org_id)
    admin, password = _new_admin(db, org, data, staff)
    db.commit()
    return _admin_payload(admin, password)


@router.get("/orgs/{org_id}/usage")
def org_usage(org_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    """Consumo contra límites, con el veredicto de cada uno (para la pantalla «Uso»)."""
    org = _org_or_404(db, org_id)
    used = orgs.usage(db, org)
    lines = []
    for key in orgs.NUMERIC_KEYS:
        limit = orgs.entitlement(org, key)
        lines.append({"key": key, "label": orgs.KEY_INFO[key]["label"], "used": used.get(key, 0), "limit": limit, "over": limit is not None and used.get(key, 0) >= limit})
    return {"org": orgs.serialize(org), "usage": used, "lines": lines}
