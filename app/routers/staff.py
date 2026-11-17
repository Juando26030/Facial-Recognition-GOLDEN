import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccessLog, Event, EventStaffAuthorization, STAFF_ROLES, StaffUser
from app import audit_actions, jobs, security, sessions, staff_credentials, localmode, temp_client
from app.inputcheck import check_text, check_username, text_validator, username_validator
from app.auth import EXTRA_ROLE_CHOICES, ROLE_HIERARCHY, STANDALONE_ROLES, EXTRA_ROLE_PRIMARIES, all_extra_roles, assert_event_scope, assert_event_tenant, effective_roles, hash_password, require_role
from app.tenant_scope import staff_tenant_enforced
from app.timeutil import utcnow

router = APIRouter()

# Roles creables/visibles desde /admin/staff. "digitador" y "cliente" NO están aquí a propósito:
# ambos se crean desde dentro de un evento (ver app/routers/events.py, POST
# /events/{id}/staff-users), donde quedan asociados a ese evento en el mismo paso.
# "comercial" (Sprint 2.4, 2026-09-16): mismo flujo que coordinador, admin+ lo crea desde acá.
ROLES_CREATABLE_BY_ADMIN = ("coordinador", "comercial", "almacen", "contabilidad")

# Qué roles puede BORRAR PERMANENTEMENTE cada rol (siempre "todo lo que está por debajo de mí").
# coordinador es el caso especial: solo temporales (digitador), nada más. "comercial" no borra a
# nadie por ahora (no fue parte del pedido) — solo admin+ puede borrar cuentas comercial.
DELETABLE_ROLES_BY = {
    "coordinador": ("digitador",),
    "admin": ("comercial", "coordinador", "almacen", "contabilidad", "digitador", "cliente"),
    "super_admin": ("admin", "comercial", "coordinador", "almacen", "contabilidad", "digitador", "cliente"),
}


class StaffIn(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    role: str
    phone: Optional[str] = None  # Sprint 2.4: notificaciones por WhatsApp más adelante
    email: Optional[str] = None  # correo para notificaciones (informe final del evento a la comercial)

    _u = username_validator("username")
    _t = text_validator("full_name")


def _serialize(s: StaffUser) -> dict:
    return {
        "id": s.id, "username": s.username, "full_name": s.full_name,
        "role": s.role, "secondary_role": s.secondary_role, "extra_roles": all_extra_roles(s), "is_active": s.is_active, "phone": s.phone, "email": s.email,
        "event_only": bool(s.event_only), "archived": s.archived_at is not None, "archived_at": s.archived_at.isoformat() if s.archived_at else None,
    }


# Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "el único doble rol permitido es coordinador
# comercial" — ambos deben estar entre coordinador/comercial, y distintos entre sí.
DUAL_ROLE_PAIR = {"coordinador", "comercial"}


def _rank(u: StaffUser) -> int:
    """Rango efectivo: el más alto entre el rol principal y los sumados (un coordinador con admin sumado pesa como admin)."""
    return max(ROLE_HIERARCHY[r] for r in effective_roles(u) if r in ROLE_HIERARCHY)


def _assert_can_manage(db: Session, actor: StaffUser, target: StaffUser) -> None:
    """Cierre de seguridad P1/P4 (6-nov-2026): además del rol, quien administra una cuenta debe poder alcanzarla.
    - Limitado a su cliente (ENFORCE_STAFF_TENANT): solo cuentas de su mismo cliente.
    - Sin admin/super_admin (el coordinador con los digitadores): si la cuenta está asignada a eventos, al menos uno debe ser accesible para quien actúa
      (tenant y pertenencia, ENFORCE_STAFF_EVENT_SCOPE). Así un coordinador no se queda con (ni borra) la cuenta de puerta de un evento ajeno.
    404 (no 403) para no confirmar que la cuenta existe. Con los dos interruptores apagados no cambia nada."""
    if staff_tenant_enforced(actor) and target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if target.id != actor.id and actor.role != "super_admin" and {"admin", "super_admin"} & effective_roles(target):
        # Ronda de seguridad F4: una cuenta con el rol admin SUMADO (extra_roles) es admin a todos los efectos; solo el Super Admin la administra (antes solo se miraba el rol principal).
        raise HTTPException(status_code=403, detail="Solo el Super Admin administra cuentas con rol Admin")
    if {"admin", "super_admin"} & effective_roles(actor):
        return
    event_ids = [eid for (eid,) in db.query(EventStaffAuthorization.event_id).filter(EventStaffAuthorization.staff_user_id == target.id)]
    if not event_ids:
        return
    for event in db.query(Event).filter(Event.id.in_(event_ids)):
        try:
            assert_event_tenant(event, actor)
            assert_event_scope(event, actor, db)
            return
        except HTTPException:
            continue
    raise HTTPException(status_code=404, detail="Cuenta no encontrada")


@router.get("/staff/coordinators")
def list_coordinators(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Liviano y accesible desde coordinador+ (a diferencia de /staff, que es admin+) — para
    poblar el selector de 'coordinador asignado' al crear/editar un evento. Incluye a quien tenga
    'coordinador' como rol PRIMARIO o SECUNDARIO (Fase 15: doble rol coordinador+comercial)."""
    coords = db.query(StaffUser).filter(
        or_(StaffUser.role == "coordinador", StaffUser.secondary_role == "coordinador"),
        StaffUser.is_active == True, StaffUser.archived_at.is_(None), StaffUser.event_only.is_(False),          # el coordinador temporal (16-nov-2026) no se asigna como coordinador de un evento: se administra desde «Usuarios del evento»
    ).all()
    return [{"id": c.id, "username": c.username, "full_name": c.full_name} for c in coords]


@router.get("/staff/commercials")
def list_commercials(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("comercial"))):
    """Sprint 2.4 Fase 5 (2026-09-16): mismo patrón que /staff/coordinators — poblar el selector
    de 'comercial asignada' al crear/editar un evento y el filtro de admin+ en /eventos. Incluye a
    quien tenga 'comercial' como rol PRIMARIO o SECUNDARIO (Fase 15)."""
    commercials = db.query(StaffUser).filter(
        or_(StaffUser.role == "comercial", StaffUser.secondary_role == "comercial"),
        StaffUser.is_active == True, StaffUser.archived_at.is_(None),
    ).all()
    return [{"id": c.id, "username": c.username, "full_name": c.full_name} for c in commercials]


@router.get("/staff/assignable")
def list_assignable_staff(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("comercial"))):
    """digitador + cliente activos, para el desplegable de 'autorizar/reautorizar para un evento'
    en /admin/staff — independiente del filtro de ROLES_CREATABLE_BY_ADMIN de /staff (que oculta
    digitador/cliente de la tabla general a propósito, pero aquí sí hacen falta)."""
    query = db.query(StaffUser).filter(StaffUser.is_active == True, StaffUser.archived_at.is_(None))
    if effective_roles(staff) & {"admin", "super_admin"}:
        query = query.filter(or_(StaffUser.role.in_(("digitador", "cliente")), StaffUser.event_only.is_(True)))
    else:
        query = query.filter(StaffUser.event_only.is_(True))          # el comercial solo busca coordinadores temporales
    if staff_tenant_enforced(staff):          # P4: limitado a su cliente, solo las cuentas de su cliente
        query = query.filter(StaffUser.tenant_id == staff.tenant_id)
    return [_serialize(s) for s in query.all()]


@router.get("/staff")
def list_staff(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Por defecto SOLO las cuentas no archivadas. `include_archived=true` (admin+, pantalla «Ver archivados») devuelve las archivadas."""
    query = db.query(StaffUser).filter(StaffUser.event_only.is_(False))          # los coordinadores temporales viven en «Usuarios del evento», no en la lista de cuentas permanentes
    query = query.filter(StaffUser.archived_at.isnot(None) if include_archived else StaffUser.archived_at.is_(None))
    if staff.role != "super_admin":
        query = query.filter(StaffUser.role.in_(ROLES_CREATABLE_BY_ADMIN))
    if staff_tenant_enforced(staff):          # P4: limitado a su cliente, solo las cuentas de su cliente
        query = query.filter(StaffUser.tenant_id == staff.tenant_id)
    return [_serialize(s) for s in query.order_by(StaffUser.created_at.desc()).all()]


@router.post("/staff")
def create_staff(
    data: StaffIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    if data.role not in STAFF_ROLES and data.role not in STANDALONE_ROLES:
        raise HTTPException(status_code=400, detail="Rol inválido")
    if data.role == "super_admin":
        raise HTTPException(status_code=403, detail="No se puede crear otro Super Admin desde la app")
    if data.role in ("digitador", "cliente"):
        raise HTTPException(
            status_code=400,
            detail=f"Las cuentas '{data.role}' se crean desde dentro de un evento (pestaña Usuarios del Evento), no aquí",
        )
    if data.role == "admin" and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede crear cuentas Admin")
    if localmode.is_local_server():
        raise HTTPException(status_code=403, detail="Las cuentas se crean en la nube: aquí llegan solas al conectarse")          # Fase 6: la nube manda
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ese usuario ya existe")
    problem = security.password_problem(data.password, data.username, strict=True)         # 0C (C11)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    # Sprint 2.4 Fase 4 (2026-09-16, pedido explícito): el teléfono es obligatorio y único para
    # todas las cuentas que se crean por acá (coordinador/comercial/admin) — digitador/cliente,
    # las dos excepciones, no pasan por este endpoint (ver create_event_staff en events.py).
    phone = (data.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="El teléfono es obligatorio para esta cuenta")
    if db.query(StaffUser).filter(StaffUser.phone == phone).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese teléfono")

    new_staff = StaffUser(
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        tenant_id=staff.tenant_id,
        created_by_id=staff.id,
        phone=phone,
        email=(data.email or "").strip() or None,
        must_change_password=security.must_change_on_set_by_other(data.role),       # Fase 4: la contraseña inicial la puso el admin; la persona elige la suya al ingresar
    )
    db.add(new_staff)
    db.flush()          # autoflush=False: hace falta el id para el trabajo en cola
    mail_queued = staff_credentials.enqueue(db, new_staff, "created", pw=staff_credentials.password_mode(new_staff, data.password))      # el correo (sin contraseña) sale en segundo plano, en la misma transacción
    db.commit()
    if mail_queued:
        jobs.kick()
    db.refresh(new_staff)
    return {**_serialize(new_staff), "credentials_mail": "queued" if mail_queued else "no_email"}


@router.patch("/staff/{staff_id}/email")
def set_staff_email(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    """Completa/corrige el correo de una cuenta (las creadas antes de que existiera el campo no lo tienen)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target or (staff.tenant_id is not None and target.tenant_id != staff.tenant_id):
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    # 0C (A1): el correo de una cuenta decide quién recibe el enlace de «olvidé mi contraseña»; cambiarlo equivale a tomar la cuenta. Solo sobre cuentas de rango INFERIOR (o la propia).
    if target.id != staff.id and _rank(target) >= _rank(staff):
        raise HTTPException(status_code=403, detail="No puedes cambiar el correo de una cuenta de tu mismo rango o superior")
    email = str(data.get("email") or "").strip()
    if email and (len(email) > 120 or not re.fullmatch(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email)):
        raise HTTPException(status_code=400, detail="Correo con formato inválido")
    target.email = email or None
    db.commit()
    return _serialize(target)


@router.patch("/staff/{staff_id}/secondary-role")
def assign_secondary_role(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin")),
):
    """Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden
    ser comerciales, esos son los únicos usuarios que pueden tener doble rol... lo hace el
    administrador". `data: {"secondary_role": "comercial"|"coordinador"|null}` — null quita el rol
    secundario. El rol primario del objetivo y el secundario elegido deben ser, entre los dos,
    exactamente el par {coordinador, comercial} — no se admite ninguna otra combinación (ej. un
    admin no puede ganar un rol secundario, ni comercial+comercial)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    _assert_can_manage(db, staff, target)          # P4: solo cuentas de su cliente

    secondary = data.get("secondary_role")
    keep = [r for r in all_extra_roles(target) if r not in DUAL_ROLE_PAIR]          # los extras que no son del par (p. ej. admin) no se tocan
    if secondary is None:
        _set_extra_roles(target, keep)
        sessions.revoke_all(target)
        db.commit()
        return _serialize(target)

    if target.role not in DUAL_ROLE_PAIR:
        raise HTTPException(status_code=400, detail="Solo cuentas coordinador o comercial pueden tener un rol secundario")
    if secondary not in DUAL_ROLE_PAIR or secondary == target.role:
        raise HTTPException(status_code=400, detail="El rol secundario debe ser el otro de coordinador/comercial")

    _set_extra_roles(target, [secondary] + keep)
    sessions.revoke_all(target)
    db.commit()
    return _serialize(target)


def _set_extra_roles(target: StaffUser, extras: list) -> None:
    """Guarda los roles que se suman al principal. `secondary_role` queda como espejo del primero entre coordinador/comercial (las consultas heredadas lo siguen leyendo)."""
    extras = [r for i, r in enumerate(extras) if r and r != target.role and r not in extras[:i]]
    target.extra_roles = ",".join(extras) or None
    target.secondary_role = next((r for r in extras if r in DUAL_ROLE_PAIR), None)


@router.put("/staff/{staff_id}/roles")
def set_staff_roles(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin")),
):
    """Varios roles para una misma cuenta (8-nov-2026, decisión de Juan David): `{"extra_roles": ["comercial", "admin"]}` REEMPLAZA la lista de roles que se suman al principal ([] los quita todos).
    Solo cuentas coordinador/comercial reciben extras; los permisos son la UNIÓN de todos. El rol «admin» como extra solo lo da (o lo quita) el Super Admin. Nunca la propia cuenta."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    _assert_can_manage(db, staff, target)
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes cambiar tus propios roles")
    if target.role not in EXTRA_ROLE_PRIMARIES or target.role not in _manageable_roles(staff):
        raise HTTPException(status_code=403, detail=f"No puedes asignar roles extra a una cuenta '{target.role}'")
    wanted = data.get("extra_roles")
    if not isinstance(wanted, list) or any(not isinstance(r, str) for r in wanted):
        raise HTTPException(status_code=400, detail="extra_roles debe ser una lista de roles")
    for r in wanted:
        if r not in EXTRA_ROLE_CHOICES:
            raise HTTPException(status_code=400, detail=f"El rol «{r}» no se puede sumar a una cuenta")
        if r == target.role:
            raise HTTPException(status_code=400, detail="Ese ya es su rol principal")
    had_admin = "admin" in all_extra_roles(target)
    if ("admin" in wanted) != had_admin and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede dar o quitar el rol Admin")
    _set_extra_roles(target, wanted)
    sessions.revoke_all(target)             # que la sesión abierta recargue sus permisos
    audit_actions.record(db, staff, "update", "staff_user", target.id, _audit_name(target), f"roles extra: {target.extra_roles or 'ninguno'}")
    db.commit()
    return _serialize(target)


@router.patch("/staff/{staff_id}/profile")
def edit_staff_profile(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin")),
):
    """Editar el perfil completo de una cuenta (8-nov-2026): usuario, nombre, correo y celular (solo los que vengan en el cuerpo). Cuentas de rango INFERIOR, o la propia (sin cambiar el usuario).
    Cambiar el usuario cierra la sesión abierta de esa persona. El celular es obligatorio y único salvo en digitador/cliente (donde, si se pone, también es único)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    _assert_can_manage(db, staff, target)
    own = target.id == staff.id
    if not own and _rank(target) >= _rank(staff):
        raise HTTPException(status_code=403, detail="No puedes editar una cuenta de tu mismo rango o superior")
    changed = []
    if "username" in data:
        try:
            username = check_username(str(data.get("username") or "").strip())
        except Exception as exc:                                    # el validador responde con ValueError/HTTPException
            raise HTTPException(status_code=400, detail=getattr(exc, "detail", None) or str(exc))
        if username != target.username:
            if own:
                raise HTTPException(status_code=400, detail="Tu propio usuario no se cambia desde aquí")
            if db.query(StaffUser.id).filter(func.lower(StaffUser.username) == username.lower(), StaffUser.id != target.id).first():
                raise HTTPException(status_code=400, detail="Ese usuario ya existe")
            target.username = username
            changed.append("usuario")
    if "full_name" in data:
        try:
            target.full_name = check_text(str(data.get("full_name") or "").strip(), "«nombre»") or None
        except Exception as exc:
            raise HTTPException(status_code=400, detail=getattr(exc, "detail", None) or str(exc))
        changed.append("nombre")
    if "email" in data:
        email = str(data.get("email") or "").strip()
        if email and (len(email) > 120 or not re.fullmatch(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email)):
            raise HTTPException(status_code=400, detail="Correo con formato inválido")
        target.email = email or None
        changed.append("correo")
    if "phone" in data:
        phone = str(data.get("phone") or "").strip()
        if not phone and target.role not in ("digitador", "cliente"):
            raise HTTPException(status_code=400, detail="El teléfono es obligatorio para esta cuenta")
        if phone and not re.fullmatch(r"[0-9+() \-]{7,30}", phone):
            raise HTTPException(status_code=400, detail="El celular solo admite números, espacios, + ( ) y -")
        if phone and db.query(StaffUser.id).filter(StaffUser.phone == phone, StaffUser.id != target.id).first():
            raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese teléfono")
        target.phone = phone or None
        changed.append("celular")
    if "usuario" in changed:
        sessions.revoke_all(target)
    audit_actions.record(db, staff, "update", "staff_user", target.id, _audit_name(target), f"perfil editado: {', '.join(changed) or 'sin cambios'}")
    db.commit()
    return _serialize(target)


def _manageable_roles(actor: StaffUser) -> set:
    """Roles de cuenta que `actor` puede administrar (cambiar rol / restablecer contraseña): los mismos que
    puede borrar (DELETABLE_ROLES_BY), siguiendo el principio "todo lo que está por debajo de mí"."""
    roles = set()
    for r in effective_roles(actor):
        roles |= set(DELETABLE_ROLES_BY.get(r, ()))
    return roles


@router.patch("/staff/{staff_id}/role")
def change_staff_role(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin")),
):
    """Cambia el rol de una cuenta ya creada (Sprint 4). Solo entre los roles que se crean desde Configuración >
    Staff (coordinador / comercial / admin); digitador y cliente son de un evento y no cambian de rol. Un admin
    solo puede tocar cuentas que estén por debajo de él, y solo el Super Admin puede nombrar admins. Al cambiar el
    rol se limpia un rol secundario que ya no encaje (el único doble rol válido es coordinador+comercial)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    _assert_can_manage(db, staff, target)
    new_role = data.get("role")
    if new_role not in ("coordinador", "comercial", "admin") + STANDALONE_ROLES:
        raise HTTPException(status_code=400, detail="El rol debe ser coordinador, comercial, almacén, contabilidad o admin")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes cambiar tu propio rol")
    if target.role not in _manageable_roles(staff) or target.role in ("digitador", "cliente"):
        raise HTTPException(status_code=403, detail=f"No puedes cambiar el rol de una cuenta '{target.role}'")
    if new_role == "admin" and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede nombrar cuentas Admin")
    target.role = new_role
    sessions.revoke_all(target)             # la sesión abierta recarga sus permisos (las páginas leen el rol guardado al entrar)
    _set_extra_roles(target, [r for r in all_extra_roles(target) if new_role in EXTRA_ROLE_PRIMARIES])          # lo que ya no encaja (o ya es el principal) se quita
    db.commit()
    return _serialize(target)


@router.put("/staff/{staff_id}/password")
def reset_staff_password(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Restablece la contraseña de una cuenta que `staff` puede administrar (un coordinador, las de digitador; un
    admin, las de abajo). Salvo el digitador temporal, la persona debe elegir su propia contraseña al ingresar
    (`must_change_password`, siempre; Fase 4)."""
    localmode.assert_passwords_allowed()          # Fase 6: en un servidor local las contraseñas solo se cambian en la nube
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="Para cambiar tu propia contraseña usa \"Cambiar contraseña\"")
    if target.role not in _manageable_roles(staff):
        raise HTTPException(status_code=403, detail=f"No puedes restablecer la contraseña de una cuenta '{target.role}'")
    _assert_can_manage(db, staff, target)          # P1: el coordinador solo con digitadores de eventos a los que tiene acceso
    generated = None
    if data.get("generate") and getattr(target, "client_temp", False):
        generated = temp_client.new_password(target.username)          # cliente temporal (12-nov-2026): contraseña aleatoria nueva, se muestra UNA vez a quien la restablece; no vence
        new_password, must_change = generated, False
    elif data.get("use_username") and target.role == "digitador" and getattr(target, "client_temp", False):
        raise HTTPException(status_code=400, detail="El cliente temporal no usa la cédula: genera una contraseña nueva")
    elif data.get("use_username") and target.role == "digitador":
        new_password, must_change = target.username, False         # digitador temporal (6-nov-2026): vuelve a entrar con su cédula como contraseña; sin política de contraseña segura
    else:
        new_password, must_change = str(data.get("new_password") or ""), security.must_change_on_set_by_other(target.role)      # Fase 4: ya no es opcional (se ignora `must_change` del cuerpo)
        problem = security.password_problem(new_password, target.username, strict=True)         # 0C (C11): la fija un administrador
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    target.password_hash = hash_password(new_password)
    target.must_change_password = must_change
    sessions.revoke_all(target)             # S2: las sesiones abiertas con la contraseña anterior dejan de valer
    mail_queued = staff_credentials.enqueue(db, target, "reset", pw=staff_credentials.password_mode(target, new_password), nonce=str(target.session_epoch))      # Fase 4: aviso por correo, sin la contraseña (una vez por restablecimiento)
    db.commit()
    if mail_queued:
        jobs.kick()
    security.clear_events(db, "login_fail", target.username)  # por si estaba bloqueada por intentos fallidos
    if generated:
        return {"message": f"Contraseña de {target.username} restablecida: entrégale la nueva, no se vuelve a mostrar", "new_password": generated, "credentials_mail": "disabled"}
    return {"message": f"Contraseña de {target.username} restablecida" + (" — deberá elegir la suya al ingresar" if target.must_change_password else "")
            + (". Se le envió un correo con las instrucciones" if mail_queued else ". No tiene correo registrado: entrégale la hoja impresa"), "credentials_mail": "queued" if mail_queued else "no_email"}


@router.patch("/staff/{staff_id}/deactivate")
def deactivate_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    _assert_can_manage(db, staff, target)
    if target.role == "super_admin":
        raise HTTPException(status_code=403, detail="Un Super Admin no se puede desactivar")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta")
    if target.role == "admin" and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    target.is_active = False
    db.commit()
    return {"message": f"{target.username} desactivado"}


@router.patch("/staff/{staff_id}/activate")
def activate_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    _assert_can_manage(db, staff, target)
    if target.role in ("admin", "super_admin") and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    if target.archived_at is not None:
        raise HTTPException(status_code=400, detail="La cuenta está archivada: restáurala primero")
    target.is_active = True
    db.commit()
    return {"message": f"{target.username} reactivado"}


def _audit_name(target: StaffUser) -> Optional[str]:
    """Nombre para el registro de acciones: el usuario, salvo el digitador (su usuario es la cédula: dato personal)."""
    return None if target.role == "digitador" else target.username


def _target_for_lifecycle(db: Session, staff: StaffUser, staff_id: int) -> StaffUser:
    """Cuenta sobre la que se archiva / restaura: alcance (`_assert_can_manage`), nunca la propia y solo roles que quien actúa administra
    (los mismos que puede borrar). Un super_admin solo lo archiva otro super_admin (ver `archive_staff`)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    _assert_can_manage(db, staff, target)
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes archivar ni restaurar tu propia cuenta")
    if target.role == "super_admin":
        if staff.role != "super_admin":
            raise HTTPException(status_code=403, detail="No autorizado")
    elif target.role not in _manageable_roles(staff):
        raise HTTPException(status_code=403, detail=f"No puedes administrar cuentas de rol '{target.role}'")
    return target


@router.post("/staff/{staff_id}/archive")
def archive_staff(staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Archivar = la cuenta deja de existir para el día a día: no inicia sesión (se desactiva y se cierra su sesión), no sale en la lista ni en los selectores de asignación.
    No borra nada (sus eventos, impresiones y registros siguen) y un administrador la restaura. No se archiva a uno mismo, al último Super Admin ni a quien sea
    coordinador/comercial de un evento «En Proceso»."""
    target = _target_for_lifecycle(db, staff, staff_id)
    if target.archived_at is not None:
        raise HTTPException(status_code=400, detail="La cuenta ya está archivada")
    if target.role == "super_admin":
        others = db.query(StaffUser.id).filter(StaffUser.role == "super_admin", StaffUser.id != target.id, StaffUser.is_active == True, StaffUser.archived_at.is_(None)).first()  # noqa: E712
        if not others:
            raise HTTPException(status_code=400, detail="No se puede archivar al último Super Admin")
    if db.query(Event.id).filter(Event.status == "en_proceso", or_(Event.coordinator_staff_id == target.id, Event.commercial_staff_id == target.id)).first():
        raise HTTPException(status_code=400, detail="No se puede archivar: es coordinador o comercial de un evento en proceso")
    target.archived_at = utcnow()
    target.archived_by_id = staff.id
    target.is_active = False
    sessions.revoke_all(target)             # la sesión abierta cae en la siguiente petición
    audit_actions.record(db, staff, "archive", "staff_user", target.id, _audit_name(target), f"rol: {target.role}")
    db.commit()
    return _serialize(target)


@router.post("/staff/{staff_id}/restore")
def restore_staff(staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Vuelve a mostrar la cuenta. Queda DESACTIVADA a propósito: para que pueda ingresar de nuevo un administrador la reactiva (decisión explícita, no un efecto lateral)."""
    target = _target_for_lifecycle(db, staff, staff_id)
    if target.archived_at is None:
        raise HTTPException(status_code=400, detail="La cuenta no está archivada")
    target.archived_at = None
    target.archived_by_id = None
    audit_actions.record(db, staff, "restore", "staff_user", target.id, _audit_name(target), f"rol: {target.role}")
    db.commit()
    return _serialize(target)


@router.delete("/staff/{staff_id}")
def delete_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    """Eliminar cuenta (8-nov-2026, decisión de Juan David): el administrador borra de verdad cualquier cuenta que administra (comercial, coordinador, digitador, cliente; el super_admin también admin),
    sin pasar por «archivar» (para dejar sin acceso sin borrar está «Desactivar»). Nunca un super_admin. No se puede si la cuenta es coordinador o comercial de algún evento (hay que reasignarlo primero);
    las autorizaciones de digitador/cliente a eventos se quitan solas. No borra Eventos ni AccessLogs: las referencias a esta cuenta quedan en NULL. Queda registrado."""
    target = _target_for_lifecycle(db, staff, staff_id)
    if target.role == "super_admin":
        raise HTTPException(status_code=403, detail="Una cuenta de Super Admin no se elimina")
    if db.query(Event.id).filter(or_(Event.coordinator_staff_id == target.id, Event.commercial_staff_id == target.id)).first():
        raise HTTPException(status_code=400, detail="No se puede eliminar: es coordinador o comercial de un evento. Reasigna el evento primero (o desactiva la cuenta)")
    sessions.revoke_all(target)

    db.query(EventStaffAuthorization).filter(EventStaffAuthorization.staff_user_id == target.id).delete()
    db.query(EventStaffAuthorization).filter(EventStaffAuthorization.authorized_by_id == target.id).update({"authorized_by_id": None})
    db.query(Event).filter(Event.coordinator_staff_id == target.id).update({"coordinator_staff_id": None})
    db.query(Event).filter(Event.created_by_id == target.id).update({"created_by_id": None})
    db.query(AccessLog).filter(AccessLog.registered_by_staff_id == target.id).update({"registered_by_staff_id": None})
    db.query(StaffUser).filter(StaffUser.created_by_id == target.id).update({"created_by_id": None})

    from app import staff_refs
    username = target.username
    audit_name, target_id, role = _audit_name(target), target.id, target.role
    outcome = staff_refs.delete_or_deactivate(db, target)      # D3: suelta TODAS las referencias (impresiones, áreas, inventario, cargas, formularios…); si una no se puede soltar, desactiva
    if outcome == "deleted":
        audit_actions.record(db, staff, "delete", "staff_user", target_id, audit_name, f"rol: {role}")
    if outcome != "deleted":
        if target.archived_at is None:
            target.archived_at, target.archived_by_id = utcnow(), staff.id
        target.is_active = False
    db.commit()
    if outcome == "deactivated":
        return {"message": f"{username} tiene registros que no se pueden desvincular: quedó archivada y desactivada en lugar de borrarse", "deactivated": True}
    return {"message": f"{username} eliminado permanentemente de la base de datos"}



# Nota: la autorización de un digitador/cliente EXISTENTE a un evento ya no vive aquí — se movió
# a app/routers/events.py (POST/DELETE /events/{id}/staff-users, /assign-existing), porque todo
# lo relacionado a "quién puede operar en este evento" se gestiona desde dentro del evento.
