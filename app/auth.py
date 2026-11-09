import os
import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import event_lease, event_rules, idle, sessions
from app.database import get_db
from app.timeutil import utcnow
from app.models import Event, EventStaffAuthorization, StaffUser, STAFF_ROLES

ROLE_HIERARCHY = {role: i for i, role in enumerate(STAFF_ROLES)}

# Roles de inventario (Fase 5, decisión de Juan David 9-nov-2026): «almacén» y «contabilidad» NO son un escalón de la escalera cliente < … < super_admin. Pueden ser el rol PRINCIPAL de una cuenta (una
# persona solo de almacén o solo de contabilidad) o SUMARSE (extra_roles) a coordinador/comercial y entre ellos (se pueden mezclar los cuatro). Dan únicamente sus permisos propios (inventario). Van en ROLE_HIERARCHY con rango -1 para que `max(ROLE_HIERARCHY[r] for r in effective_roles(...))` siga funcionando (el rango lo pone el rol
# principal; el extra nunca sube ni baja) y para que split_roles los reconozca; NO están en STAFF_ROLES (así ninguna lista de «roles que se crean/cambian» los ofrece como principal).
EXTRA_ONLY_ROLES = {"almacen": "Almacén", "contabilidad": "Contabilidad"}          # (nombre histórico) roles de inventario
STANDALONE_ROLES = tuple(EXTRA_ONLY_ROLES)          # también valen como rol principal de una cuenta
for _r in EXTRA_ONLY_ROLES:
    ROLE_HIERARCHY[_r] = -1


FORM_CLIENT_OWN_PREFIXES = ("/api/form-client/", "/mi-formulario")          # sus propias rutas responden con su mensaje de acceso vencido (403, form_client.resolve)


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def get_current_staff(request: Request, db: Session = Depends(get_db)) -> StaffUser:
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    staff = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()
    if not staff:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sesión inválida o usuario desactivado")
    if sessions.is_replaced(db, request, staff):         # entró con esta cuenta en otro dispositivo (sesión única): el cliente detiene todo y lleva al inicio de sesión
        request.session.clear()
        raise HTTPException(status_code=401, detail="session_replaced")
    if staff.role == "cliente" and not request.url.path.startswith(FORM_CLIENT_OWN_PREFIXES):          # B10: la cuenta de cliente de formulario VENCIDA no usa el resto de la API (assets, estados, sondeos)
        from app import form_client
        grant = form_client.grant_for(db, staff)
        if grant is not None and grant.expires_at <= utcnow():
            request.session.clear()
            raise HTTPException(status_code=401, detail="Tu acceso venció. Pide uno nuevo a tu contacto de Golden.")
    return staff


def effective_roles(staff: StaffUser) -> set:
    """Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden
    ser comerciales" — StaffUser.secondary_role permite exactamente ESE doble rol (coordinador+
    comercial, en cualquier orden), asignado por admin+. Todo el resto de auth.py razona sobre
    este CONJUNTO de roles en vez de un solo `staff.role`, para que alguien con doble rol reciba
    la UNIÓN de permisos de ambos — en particular, para que las exclusiones de Fase 6 (comercial
    no puede Escarapelas/Adjuntar BD/Parámetros) NO le apliquen a quien también es coordinador de
    verdad, no una comercial pura."""
    roles = {staff.role}
    if staff.secondary_role:
        roles.add(staff.secondary_role)
    roles.update(split_roles(getattr(staff, "extra_roles", None)))          # 8-nov-2026: varios roles a una misma cuenta (columna extra_roles)
    return roles


# Roles que se pueden SUMAR al rol principal de una cuenta (8-nov-2026, decisión de Juan David). «almacen» y «contabilidad» (Fase 5) son SOLO extra (EXTRA_ONLY_ROLES).
# Solo cuentas con rol principal en EXTRA_ROLE_PRIMARIES reciben roles extra; «admin» como extra solo lo da el Super Admin.
EXTRA_ROLE_CHOICES = ("coordinador", "comercial", "admin", "almacen", "contabilidad")
EXTRA_ROLE_PRIMARIES = ("coordinador", "comercial", "almacen", "contabilidad")          # rol principal que admite sumar otros


def split_roles(value) -> list:
    """'comercial,admin' -> ['comercial', 'admin'] (sin vacíos ni repetidos, solo roles que existen). También sirve para el valor guardado en la sesión."""
    out = []
    for r in str(value or "").split(","):
        r = r.strip()
        if r and r in ROLE_HIERARCHY and r not in out:
            out.append(r)
    return out


def is_inventory_only(staff_or_roles) -> bool:
    """¿Solo tiene roles de inventario (almacén/contabilidad)? Esas cuentas no tienen panel ni eventos: su única pantalla es /inventario."""
    roles = staff_or_roles if isinstance(staff_or_roles, (set, list, tuple)) else effective_roles(staff_or_roles)
    return bool(roles) and set(roles) <= set(STANDALONE_ROLES)


def has_any_role(staff, *roles: str) -> bool:
    """¿La cuenta tiene alguno de estos roles (principal o sumados)?"""
    return bool(effective_roles(staff) & set(roles))


def staff_with_role(db: Session, role: str) -> list:
    """Cuentas ACTIVAS (no archivadas) que tienen este rol, principal o sumado (p. ej. 'almacen', 'contabilidad'): sirve para mandar un correo a todas (`[s.email for s in … if s.email]`).
    Sin filtrar por correo: quien llama decide qué hacer con las que no tienen."""
    rows = db.query(StaffUser).filter(StaffUser.is_active == True, StaffUser.archived_at.is_(None),  # noqa: E712
                                      or_(StaffUser.role == role, StaffUser.extra_roles.like(f"%{role}%"), StaffUser.secondary_role == role)).order_by(StaffUser.id).all()
    return [s for s in rows if role in effective_roles(s)]          # el LIKE solo preselecciona; la pertenencia exacta la decide effective_roles


def all_extra_roles(staff) -> list:
    """Todos los roles que la cuenta tiene ADEMÁS del principal (secundario heredado + extras), en orden y sin repetir."""
    out = split_roles(getattr(staff, "secondary_role", None))
    for r in split_roles(getattr(staff, "extra_roles", None)):
        if r not in out:
            out.append(r)
    return [r for r in out if r != staff.role]


def require_role(minimum_role: str):
    """Exige que el staff logueado tenga al menos este rol (jerarquía en STAFF_ROLES) — considera
    el rol secundario si tiene uno (ver effective_roles)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) < minimum_level:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_role_or_any(minimum_role: str, extra_roles: tuple):
    """Como require_role, pero además deja pasar a quien tenga alguno de `extra_roles` aunque su rango sea menor (p. ej. almacén/contabilidad para el inventario)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        roles = effective_roles(staff)
        if max(ROLE_HIERARCHY[r] for r in roles) < minimum_level and not (roles & set(extra_roles)):
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_role_excluding(minimum_role: str, excluded_roles: tuple):
    """Como require_role, pero además bloquea roles puntuales aunque cumplan la jerarquía — Sprint
    2.4 Fase 6 (2026-09-16, pedido explícito): 'comercial' queda por ENCIMA de 'coordinador' en
    STAFF_ROLES (hereda su acceso operativo por diseño, ver Fase 0), pero el usuario pidió que
    puntualmente NO tenga Adjuntar Base de Datos, Escarapelas ni Parámetros del Evento — un
    require_role('coordinador') simple no puede excluir un rol que está POR ENCIMA del mínimo.
    Con doble rol (Fase 15): solo bloquea si TODOS sus roles efectivos están en excluded_roles —
    una comercial pura queda bloqueada, pero alguien coordinador+comercial no (porque también es
    coordinador de verdad, no solo comercial con la jerarquía prestada)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        roles = effective_roles(staff)
        if roles.issubset(set(excluded_roles)):
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        if max(ROLE_HIERARCHY[r] for r in roles) < minimum_level:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_role_or_client(minimum_role: str):
    """Como require_role, pero además deja pasar siempre a 'cliente' aunque quede por debajo del
    mínimo en STAFF_ROLES — pensado para vistas de solo lectura (Estadísticas, 2026-09-16,
    pedido explícito: el cliente asignado a un evento debe poder ver sus estadísticas) donde
    'cliente' sí debe entrar pero 'digitador' (que en la jerarquía queda POR ENCIMA de 'cliente')
    sigue sin poder, porque no le corresponde ver reportes. 'cliente' nunca tiene rol secundario
    (el doble rol solo aplica a coordinador/comercial), así que effective_roles no cambia este caso."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if staff.role == "cliente" or max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) >= minimum_level:
            return staff
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")

    return checker


def require_super_admin(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede hacer esto")
    return staff


def _closed_detail(event: Event, prefix: str) -> str:
    """Mensaje de «el evento no está disponible»: con el nombre del estado configurado cuando lo hay (si no, el de siempre: no ha comenzado / ya finalizó)."""
    if event.state is not None and event.state.name not in ("Creado", "En proceso", "Finalizado"):
        return f"{prefix} está en el estado «{event.state.name}», que no lo permite"
    label = "todavía no ha comenzado" if event.status == "creado" else "ya está finalizado"
    return f"{prefix} {label}"


def assert_event_tenant(event: Event, staff: StaffUser) -> None:
    """Aislamiento por cliente (0C, H1/A9): con ENFORCE_STAFF_TENANT=1, un usuario del personal con `tenant_id` solo ve eventos de ese tenant (nulo = global, p. ej. Golden/super_admin).
    Apagado por defecto: hoy todo el personal es de Golden; se enciende (en staging primero) antes de dar acceso a personal de otra empresa."""
    if os.getenv("ENFORCE_STAFF_TENANT", "0") == "1" and staff.tenant_id is not None and event.tenant_id != staff.tenant_id:
        raise HTTPException(status_code=404, detail="Evento no encontrado")


def assert_tenant_id(tenant_id: str, staff: StaffUser) -> None:
    """Como `assert_event_tenant`, para recursos que solo traen el id del cliente en la ruta (p. ej. imágenes de escarapela): con ENFORCE_STAFF_TENANT=1, el personal de un cliente no toca los de otro."""
    if os.getenv("ENFORCE_STAFF_TENANT", "0") == "1" and staff.tenant_id is not None and tenant_id != staff.tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")


def event_scope_enforced() -> bool:
    """A6/A7 (0C): con ENFORCE_STAFF_EVENT_SCOPE=1, el coordinador y el comercial solo operan en los eventos a los que PERTENECEN (los coordina, son su comercial, lo crearon o tienen una autorización
    explícita). Admin y super_admin siguen viendo todos (dentro de su tenant). Apagado por defecto: hoy los coordinadores de Golden operan en cualquier evento por diseño; se enciende (en staging primero,
    con la asignación de coordinador/comercial al día) antes de abrir el SaaS."""
    return os.getenv("ENFORCE_STAFF_EVENT_SCOPE", "0") == "1"


def _scope_applies(staff: StaffUser) -> bool:
    return event_scope_enforced() and staff.role not in ("digitador", "cliente") and not ({"admin", "super_admin"} & effective_roles(staff))


def assert_event_scope(event: Event, staff: StaffUser, db: Session) -> None:
    """Pertenencia al evento (A6/A7) para coordinador/comercial; ver `event_scope_enforced`. 404 (no 403) para no confirmar que el evento existe."""
    if not _scope_applies(staff):
        return
    if staff.id in (event.coordinator_staff_id, event.commercial_staff_id, event.created_by_id):
        return
    if db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=staff.id).first():
        return
    raise HTTPException(status_code=404, detail="Evento no encontrado")


def scope_events_query(query, staff: StaffUser):
    """Listas de eventos: el mismo recorte que `assert_event_tenant` + `assert_event_scope`, aplicado a una consulta de `Event` (con ambos interruptores apagados no cambia nada)."""
    if os.getenv("ENFORCE_STAFF_TENANT", "0") == "1" and staff.tenant_id is not None:
        query = query.filter(Event.tenant_id == staff.tenant_id)
    if _scope_applies(staff):
        mine = [Event.coordinator_staff_id == staff.id, Event.commercial_staff_id == staff.id, Event.created_by_id == staff.id,
                Event.id.in_(select(EventStaffAuthorization.event_id).where(EventStaffAuthorization.staff_user_id == staff.id))]
        query = query.filter(or_(*mine))
    return query


def get_event_for_staff(event_id: int, db: Session, staff: StaffUser) -> Event:
    """Resuelve el evento y valida acceso. coordinador+ tiene alcance de tenant (acceso a
    cualquier evento); digitador/cliente necesitan una EventStaffAuthorization para ESE evento
    puntual, y el evento debe estar en estado 'en_proceso' (ver EVENT_STATUSES en models.py)."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    idle.note_event(event)                      # tiempo de inactividad propio del evento (solo en proceso); ver app/idle.py

    if staff.role in ("digitador", "cliente"):
        authorized = db.query(EventStaffAuthorization).filter_by(
            event_id=event_id, staff_user_id=staff.id
        ).first()
        if not authorized:
            raise HTTPException(status_code=403, detail="No estás autorizado para este evento")
        rule = "client_access" if staff.role == "cliente" else "temp_digitadores_enter"
        if not event_rules.allowed(event, rule):
            raise HTTPException(status_code=403, detail=_closed_detail(event, "Este evento"))

    return event


def require_event_in_progress(event: Event) -> None:
    """Gate aparte de get_event_for_staff, para las acciones de REGISTRAR en sí
    (recognize/register/bulk_register) — a diferencia del acceso general al evento, esto aplica a
    TODOS los roles por igual, incluido admin/super_admin: si el evento no está 'en_proceso', nadie
    registra, solo se puede ver/editar el evento y gestionar sus usuarios."""
    event_lease.assert_editable(event)          # Fase 6: en un servidor local el evento es de solo lectura en la nube
    if not event_rules.allowed(event, "registration"):
        raise HTTPException(status_code=403, detail=_closed_detail(event, "No se puede registrar: este evento"))
