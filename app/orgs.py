"""Capa «empresa» del SaaS, primera pieza (22-nov-2026, docs/27_SAAS_EMPRESAS.md).

Una EMPRESA (`organizations`) es quien usa la plataforma: Golden es la fila 1 (plan «interno», nunca se limita ni se suspende). Cada empresa tiene un PLAN con límites de fábrica (`PLANS`) y puede
tener límites propios (`entitlements_json`) que pisan los del plan. Aquí vive la lógica pura (planes, límites, mensajes) y las consultas (uso del mes, alta de una empresa con su administrador).

Lo que esta pieza NO hace todavía (ver el plan en docs/27): filtrar por empresa cada consulta, RLS, identidad y marca por empresa, cobro. El aislamiento de hoy es el de siempre, por cliente
(`ENFORCE_STAFF_TENANT`): por eso la cuenta de una empresa distinta de Golden nace ATADA a su cliente y solo se puede crear con ese interruptor encendido (`external_accounts_ready`)."""
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session, object_session

from app.models import Event, EventAttendee, Organization, StaffUser, Tenant
from app.timeutil import utcnow

GOLDEN_ID = 1
INTERNAL_PLAN = "interno"
STATUSES = ("active", "suspended")

# Claves de límite. Las numéricas son topes (None = sin límite); las de sí/no son funciones incluidas en el plan.
NUMERIC_KEYS = ("events_per_month", "attendees_per_event", "users")
FEATURE_KEYS = ("facial", "local_server", "paid_forms", "own_brand")
KEYS = NUMERIC_KEYS + FEATURE_KEYS

# Nombre, para qué sirve y cómo se nombra en los mensajes («Tu plan permite N …»).
KEY_INFO = {
    "events_per_month": {"label": "Eventos por mes", "unit": "eventos por mes", "help": "Cuántos eventos nuevos puede crear la empresa en un mes calendario. Ejemplo: 4."},
    "attendees_per_event": {"label": "Asistentes por evento", "unit": "asistentes por evento", "help": "Cuántas personas caben en la base de UN evento. Ejemplo: 3000."},
    "users": {"label": "Usuarios (cuentas del personal)", "unit": "usuarios", "help": "Cuántas cuentas de personal activas puede tener (sin contar digitadores temporales). Ejemplo: 15."},
    "facial": {"label": "Reconocimiento facial", "unit": "reconocimiento facial", "help": "Si la empresa puede encender el reconocimiento facial voluntario en sus eventos."},
    "local_server": {"label": "Servidor local sin internet", "unit": "servidor local", "help": "Si puede usar llaves de producto para operar un evento sin internet."},
    "paid_forms": {"label": "Formularios con pago", "unit": "formularios con pago", "help": "Si sus formularios web pueden cobrar (Wompi)."},
    "own_brand": {"label": "Marca propia", "unit": "marca propia", "help": "Si puede usar su logo, sus colores y su remitente de correo."},
}

# Valores de fábrica de cada plan (propuesta de docs/revision_2026-11-22/07 §2.3 b; se cambian por empresa desde /plataforma, sin tocar código).
PLANS = {
    "interno": {"label": "Interno (Golden)", "events_per_month": None, "attendees_per_event": None, "users": None, "facial": True, "local_server": True, "paid_forms": True, "own_brand": True},
    "basico": {"label": "Básico", "events_per_month": 1, "attendees_per_event": 500, "users": 5, "facial": False, "local_server": False, "paid_forms": False, "own_brand": False},
    "pro": {"label": "Pro", "events_per_month": 4, "attendees_per_event": 3000, "users": 15, "facial": True, "local_server": True, "paid_forms": True, "own_brand": True},
    "empresa": {"label": "Empresa", "events_per_month": None, "attendees_per_event": 15000, "users": None, "facial": True, "local_server": True, "paid_forms": True, "own_brand": True},
}
SELLABLE_PLANS = ("basico", "pro", "empresa")          # «interno» es solo de Golden

SUPPORT_HINT = "contacta a soporte"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$")

# Golden sin tocar la base: lo que ya existe (org_id NULL o 1) es de Golden y nunca se limita.
_GOLDEN = SimpleNamespace(id=GOLDEN_ID, slug="golden", name="Golden", plan=INTERNAL_PLAN, entitlements_json=None, status="active")


# ------------------------------- lógica pura -------------------------------
def is_internal(org) -> bool:
    """¿Es Golden (la empresa 1)? Nunca se limita, no se suspende y no cambia de plan."""
    return org is None or getattr(org, "id", None) in (None, GOLDEN_ID)


def slugify(name: str) -> str:
    """'Eventos del Caribe S.A.S.' -> 'eventos-del-caribe-s-a-s' (minúsculas, sin tildes, guiones)."""
    plain = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60].strip("-")


def parse_entitlements(raw) -> dict:
    """El JSON guardado como dict; cualquier cosa rara (vacío, texto roto, no es un objeto) = sin límites propios."""
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clean_entitlements(data) -> dict:
    """Valida lo que llega de la pantalla: solo claves conocidas; numéricas = entero ≥ 0 o None (sin límite); funciones = sí/no. Lanza ValueError con el mensaje para la persona."""
    out = {}
    for key, value in (data or {}).items():
        if key not in KEYS:
            raise ValueError(f"El límite «{key}» no existe")
        if key in NUMERIC_KEYS:
            if value is None or value == "":
                out[key] = None
                continue
            if isinstance(value, bool) or not str(value).strip().lstrip("-").isdigit() or int(value) < 0:
                raise ValueError(f"«{KEY_INFO[key]['label']}» debe ser un número entero (0 o más), o vacío para dejarlo sin límite")
            out[key] = int(value)
        else:
            if not isinstance(value, bool):
                raise ValueError(f"«{KEY_INFO[key]['label']}» debe ser sí o no")
            out[key] = value
    return out


def entitlement(org, key: str):
    """Valor vigente de un límite para la empresa: el propio (si la clave está en `entitlements_json`, aunque sea null = sin límite) o el de su plan. Golden: siempre sin límite / incluido."""
    if key not in KEYS:
        raise KeyError(key)
    if is_internal(org):
        return PLANS[INTERNAL_PLAN][key]
    own = parse_entitlements(getattr(org, "entitlements_json", None))
    if key in own:
        return own[key]
    return PLANS.get(getattr(org, "plan", None) or "basico", PLANS["basico"])[key]


def entitlements(org) -> dict:
    return {key: entitlement(org, key) for key in KEYS}


def limit_message(key: str, limit) -> str:
    if key in FEATURE_KEYS:
        return f"Tu plan no incluye {KEY_INFO[key]['unit']}; {SUPPORT_HINT}"
    return f"Tu plan permite {limit} {KEY_INFO[key]['unit']}; {SUPPORT_HINT}"


SUSPENDED_MESSAGE = f"La cuenta de tu empresa está suspendida; {SUPPORT_HINT}"


def check_limit(db: Optional[Session], org, key: str, current: Optional[int] = None):
    """¿La empresa puede hacer UNO más de `key`? Devuelve (ok, mensaje en español). `current` = cuántos tiene ya; si no se da, se cuenta en la base (`usage`).
    Golden nunca se limita (y no se consulta nada). Una empresa suspendida no puede crear nada."""
    if is_internal(org):
        return True, ""
    if getattr(org, "status", "active") == "suspended":
        return False, SUSPENDED_MESSAGE
    limit = entitlement(org, key)
    if key in FEATURE_KEYS:
        return (True, "") if limit else (False, limit_message(key, limit))
    if limit is None:
        return True, ""
    if current is None:
        current = usage(db, org).get(key, 0) if db is not None else 0
    if current >= limit:
        return False, limit_message(key, limit)
    return True, ""


def external_accounts_ready() -> bool:
    """¿Se pueden dar cuentas a una empresa distinta de Golden? Solo con el aislamiento por cliente encendido (ENFORCE_STAFF_TENANT=1): sin él, esa cuenta vería los eventos de todas."""
    return os.getenv("ENFORCE_STAFF_TENANT", "0") == "1"


EXTERNAL_BLOCKED_MESSAGE = ("Todavía no se pueden dar cuentas a otra empresa: el aislamiento entre empresas está apagado (ENFORCE_STAFF_TENANT=0) y esa cuenta vería los eventos de Golden. "
                            "Enciéndelo primero en staging (docs/27_SAAS_EMPRESAS.md, «Antes del primer cliente»).")


def temp_password() -> str:
    """Contraseña temporal generada en el servidor (se muestra UNA vez; la persona la cambia en su primer ingreso). Siempre con letras y números."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"          # sin 0/O/1/l/I: se dicta por teléfono
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.isdigit() for c in value) and any(c.islower() for c in value) and any(c.isupper() for c in value):
            return value


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or utcnow()
    return datetime(now.year, now.month, 1)


# ------------------------------- consultas -------------------------------
def golden(db: Session) -> Organization:
    """La fila 1 (Golden). La crea la migración 0162; si falta (base recién vaciada), se repone aquí para que la siguiente empresa nunca tome el id 1."""
    org = db.query(Organization).filter(Organization.id == GOLDEN_ID).first()
    if org is None:
        org = Organization(id=GOLDEN_ID, slug="golden", name="Golden", legal_name="Golden Eventos y Logística S.A.S.", plan=INTERNAL_PLAN, status="active")
        db.add(org)
        db.flush()
        if db.get_bind().dialect.name == "postgresql":          # id explícito: la secuencia sigue desde el mayor
            db.execute(text("SELECT setval(pg_get_serial_sequence('organizations', 'id'), (SELECT MAX(id) FROM organizations))"))
    return org


def get_org(db: Session, org_id) -> Optional[Organization]:
    return db.query(Organization).filter(Organization.id == org_id).first() if org_id else None


def current_org(user):
    """La empresa de una cuenta del personal. Sin `org_id` (o 1) = Golden, sin consultar la base."""
    org_id = getattr(user, "org_id", None)
    if org_id in (None, GOLDEN_ID):
        return _GOLDEN
    db = object_session(user)
    org = get_org(db, org_id) if db is not None else None
    return org or SimpleNamespace(id=org_id, slug="", name="", plan="basico", entitlements_json=None, status="suspended")          # empresa que ya no existe: nada se le permite


def org_for_tenant(db: Session, tenant):
    """La empresa dueña de un cliente (`tenants.org_id`). Golden sin consultar la base (así crear un evento de Golden no cuesta una consulta más)."""
    org_id = getattr(tenant, "org_id", None)
    if org_id in (None, GOLDEN_ID):
        return _GOLDEN
    return get_org(db, org_id) or SimpleNamespace(id=org_id, slug="", name="", plan="basico", entitlements_json=None, status="suspended")


def _tenant_ids(db: Session, org) -> list:
    q = db.query(Tenant.id)
    if is_internal(org):
        q = q.filter((Tenant.org_id == GOLDEN_ID) | (Tenant.org_id.is_(None)))
    else:
        q = q.filter(Tenant.org_id == org.id)
    return [tid for (tid,) in q]


def usage(db: Session, org, now: Optional[datetime] = None) -> dict:
    """Consumo de la empresa: eventos creados este mes (UTC), cuentas activas del personal (sin digitadores ni clientes temporales), asistentes en total y el evento más grande.
    La persona de prueba (`PRUEBA`) no cuenta."""
    from app import testperson
    tenant_ids = _tenant_ids(db, org)
    staff_q = db.query(func.count(StaffUser.id)).filter(StaffUser.is_active.is_(True), StaffUser.archived_at.is_(None), StaffUser.role.notin_(("digitador", "cliente")))
    staff_q = staff_q.filter((StaffUser.org_id == GOLDEN_ID) | (StaffUser.org_id.is_(None))) if is_internal(org) else staff_q.filter(StaffUser.org_id == org.id)
    out = {"events_per_month": 0, "events_total": 0, "attendees_total": 0, "attendees_per_event": 0, "users": staff_q.scalar() or 0, "clients": len(tenant_ids)}
    if not tenant_ids:
        return out
    events = db.query(Event.id).filter(Event.tenant_id.in_(tenant_ids))
    out["events_total"] = events.count()
    out["events_per_month"] = events.filter(Event.created_at >= month_start(now)).count()
    per_event = (db.query(EventAttendee.event_id, func.count(EventAttendee.user_id))
                 .filter(EventAttendee.tenant_id.in_(tenant_ids), EventAttendee.user_id != testperson.TEST_ID).group_by(EventAttendee.event_id).all())
    out["attendees_total"] = sum(n for _, n in per_event)
    out["attendees_per_event"] = max((n for _, n in per_event), default=0)
    return out


def home_tenant(db: Session, org: Organization) -> Tenant:
    """El cliente «propio» de una empresa que no es Golden: a él queda atada su cuenta de administrador (el aislamiento de hoy es por cliente). Se crea la primera vez."""
    tenant = db.query(Tenant).filter(Tenant.org_id == org.id, Tenant.archived_at.is_(None)).order_by(Tenant.id).first()
    if tenant is not None:
        return tenant
    base = f"org{org.id}_{slugify(org.name).replace('-', '_')}"[:60]
    tenant_id, n = base, 1
    while db.query(Tenant.id).filter(Tenant.id == tenant_id).first():
        n += 1
        tenant_id = f"{base}_{n}"
    code = secrets.token_hex(4).upper()
    while db.query(Tenant.id).filter(Tenant.client_code == code).first():
        code = secrets.token_hex(4).upper()
    tenant = Tenant(id=tenant_id, client_code=code, name=org.name, contact_email=org.contact_email, contact_phone=org.contact_phone, org_id=org.id)
    db.add(tenant)
    db.flush()
    return tenant


def create_org(db: Session, data: dict) -> Organization:
    """Crea la empresa (sin confirmar la transacción). `data`: name (obligatorio), slug, legal_name, nit, contact_email, contact_phone, plan, entitlements, notes. ValueError con el mensaje."""
    golden(db)          # la fila 1 existe antes que cualquier otra
    name = str(data.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("Escribe el nombre de la empresa")
    plan = data.get("plan") or "basico"
    if plan not in SELLABLE_PLANS:
        raise ValueError("Elige un plan: Básico, Pro o Empresa")
    slug = str(data.get("slug") or "").strip().lower() or slugify(name)
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("El identificador solo admite minúsculas, números y guiones (por ejemplo: eventos-del-caribe)")
    if db.query(Organization.id).filter(Organization.slug == slug).first():
        raise ValueError(f"Ya existe una empresa con el identificador «{slug}»: escribe otro")
    own = clean_entitlements(data.get("entitlements"))
    org = Organization(slug=slug, name=name[:200], legal_name=_opt(data.get("legal_name"), 200), nit=_opt(data.get("nit"), 40), contact_email=_opt(data.get("contact_email"), 200),
                       contact_phone=_opt(data.get("contact_phone"), 40), plan=plan, entitlements_json=json.dumps(own) if own else None, status="active", notes=_opt(data.get("notes"), 4000))
    db.add(org)
    db.flush()
    return org


def create_admin(db: Session, org: Organization, username: str, full_name: str, email: Optional[str], temp_password_hash: str, phone: Optional[str] = None,
                 created_by: Optional[StaffUser] = None) -> StaffUser:
    """Primer administrador (rol `admin`) de la empresa, con contraseña temporal (`must_change_password`: la cambia al ingresar; docs/FASE_4_CLAVE_PRIMERA_VEZ.md). Sin confirmar la
    transacción. Una empresa distinta de Golden: solo con el aislamiento encendido, y la cuenta nace atada al cliente propio de la empresa. ValueError / PermissionError con el mensaje."""
    username = str(username or "").strip()
    if not username:
        raise ValueError("Escribe el usuario del administrador")
    if db.query(StaffUser.id).filter(StaffUser.username == username).first():
        raise ValueError("Ese usuario ya existe: elige otro")
    phone = str(phone or "").strip() or None
    if phone and db.query(StaffUser.id).filter(StaffUser.phone == phone).first():
        raise ValueError("Ya existe una cuenta con ese teléfono")
    tenant_id = None
    if not is_internal(org):
        if not external_accounts_ready():
            raise PermissionError(EXTERNAL_BLOCKED_MESSAGE)
        ok, message = check_limit(db, org, "users")
        if not ok:
            raise ValueError(message)
        tenant_id = home_tenant(db, org).id
    admin = StaffUser(username=username, password_hash=temp_password_hash, full_name=str(full_name or "").strip() or None, role="admin", email=str(email or "").strip() or None, phone=phone,
                      tenant_id=tenant_id, org_id=org.id, must_change_password=True, created_by_id=created_by.id if created_by is not None else None)
    db.add(admin)
    db.flush()
    return admin


def create_org_with_admin(db: Session, data: dict, admin_username: str, admin_full_name: str, admin_email: Optional[str], temp_password_hash: str, admin_phone: Optional[str] = None,
                          created_by: Optional[StaffUser] = None):
    """Empresa + su primer administrador en UNA transacción (sin confirmarla: lo hace quien llama). Devuelve (empresa, administrador)."""
    org = create_org(db, data)
    admin = create_admin(db, org, admin_username, admin_full_name, admin_email, temp_password_hash, phone=admin_phone, created_by=created_by)
    return org, admin


def _opt(value, limit: int) -> Optional[str]:
    v = str(value or "").strip()
    return v[:limit] or None


def serialize(org) -> dict:
    return {
        "id": org.id, "slug": org.slug, "name": org.name, "legal_name": org.legal_name, "nit": org.nit, "contact_email": org.contact_email, "contact_phone": org.contact_phone,
        "plan": org.plan, "plan_label": PLANS.get(org.plan, {}).get("label", org.plan), "status": org.status, "notes": org.notes, "internal": is_internal(org),
        "own_entitlements": parse_entitlements(org.entitlements_json), "entitlements": entitlements(org),
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


def catalog() -> dict:
    """Lo que la pantalla necesita para pintar planes y límites sin repetir números."""
    return {
        "plans": [{"key": k, "label": PLANS[k]["label"], "sellable": k in SELLABLE_PLANS, "values": {key: PLANS[k][key] for key in KEYS}} for k in PLANS],
        "keys": [{"key": k, "numeric": k in NUMERIC_KEYS, **KEY_INFO[k]} for k in KEYS],
        "external_accounts_ready": external_accounts_ready(),
    }
