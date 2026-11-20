"""Política de sesiones por rol (26-oct-2026). La sesión sigue siendo la cookie firmada de siempre; lo nuevo es un identificador (`sid`) dentro de ella que se compara con `staff_users.session_token`.

  - SESIÓN ÚNICA solo para las cuentas TEMPORALES: digitador (incluye al «cliente temporal», que es un digitador) y cliente (acceso a las estadísticas de un formulario). Al iniciar sesión se invalida la anterior de esa cuenta;
    sus peticiones reciben 401 `session_replaced`.
  - TODOS LOS DEMÁS (admin, super_admin, coordinador —también el temporal—, comercial): SESIONES MÚLTIPLES SIN LÍMITE (20-nov-2026, pedido de Juan David). Entrar desde otro dispositivo nunca cierra otra sesión
    y no se aplica la protección de «puesto en uso». Como no llevan `sid`, la cookie de uno no se puede invalidar de a una: tienen el tope absoluto de app/idle.py (`ABSOLUTE_ROLES`); cerrar sesión revoca todas las del
    admin/super_admin (`ADMIN_ROLES`), no las del coordinador ni el comercial.
  - (solo para las cuentas de sesión única) cuenta marcada «Puesto de impresión» (`print_station`): PROTEGIDA. Si está en uso (un equipo suyo dio señal en el último minuto), un inicio de sesión desde otro dispositivo se RECHAZA;
    solo un admin puede liberarla (`force_release`, queda en auditoría).
  - (solo para las cuentas de sesión única) cuenta que ATIENDE a otros equipos (alguien tiene su ruta de impresión apuntando a ella, `PrintRoute.printer_staff_id`) y cuyo equipo dio señal en el último minuto: también PROTEGIDA
    (29-oct-2026): un segundo inicio de sesión en OTRO dispositivo se RECHAZA con un mensaje claro; el mismo navegador (mismo `sid`) puede volver a entrar, sin señal en 60 s se libera sola y un admin puede liberarla.
  - Una sesión SIN `sid` (creada antes del cambio) o una cuenta sin `session_token` sigue válida: desplegar no expulsa a nadie.
  - Interruptor «Sesión única» (Configuración → `app_settings.single_session`; la variable de entorno SINGLE_SESSION=0/1 manda sobre él). Apagado = comportamiento anterior: no se guarda ni se compara nada.
  - Varias pestañas del mismo navegador comparten la cookie, y por tanto el `sid`: no se expulsan entre sí.
La impresión NO depende de la sesión (registro de dispositivos por cuenta, app/routers/shared_print.py). Auditoría (`session_audit`, 90 días): cuenta, hora, tipo de dispositivo, navegador y resultado; sin IP."""
import logging
import os
import re
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import AppSetting, PrintDevice, PrintRoute, SessionAudit, StaffUser
from app.timeutil import utcnow

log = logging.getLogger("golden.sessions")

SETTING_KEY = "single_session"
AUDIT_DAYS = 90
STATION_ACTIVE_WINDOW = timedelta(seconds=60)
SINGLE_ROLES = ("digitador", "cliente")          # cuentas temporales: una sola sesión a la vez (el «cliente temporal» tiene rol digitador)
ADMIN_ROLES = ("admin", "super_admin")
MULTI_ROLES = ADMIN_ROLES + ("coordinador", "comercial")          # varias sesiones y varios dispositivos a la vez
FREE_PREFIX = "free:"                      # token de una cuenta liberada por un admin: ya no coincide con ninguna sesión y no cuenta como «en uso»
STATION_BUSY_MSG = "Esta cuenta es un puesto de impresión y ya está en uso. Pídele a un administrador que la libere."
HOST_BUSY_MSG = "Esta cuenta está imprimiendo para otros equipos en otro dispositivo; ciérrala allí o pide a un administrador que la libere."
_seen_closed: set = set()                  # (cuenta, sid) ya auditados como «cerrada» en este proceso (una fila por sesión cerrada, no una por petición)


def single_session_on(db: Session) -> bool:
    env = os.getenv("SINGLE_SESSION", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "si", "sí", "on"):
        return True
    row = db.get(AppSetting, SETTING_KEY)
    return not (row is not None and (row.value or "").strip() == "0")


def set_single_session(db: Session, on: bool) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        db.add(row)
    row.value, row.updated_at = ("1" if on else "0"), utcnow()
    db.commit()


def policy(staff: StaffUser) -> str:
    if staff.role not in SINGLE_ROLES:
        return "multi"
    return "station" if staff.print_station else "single"


def client_info(request) -> tuple:
    ua = (request.headers.get("user-agent") or "") if request is not None else ""
    device = "móvil" if re.search(r"Mobi|Android|iPhone", ua) else "tableta" if re.search(r"iPad|Tablet", ua) else "computador"
    browser = "Edge" if "Edg/" in ua else "Firefox" if "Firefox/" in ua else "Chrome" if re.search(r"Chrome/|CriOS", ua) else "Safari" if "Safari/" in ua else "otro"
    return device, browser


def audit(db: Session, staff_id, request, result: str) -> None:
    device, browser = client_info(request)
    db.add(SessionAudit(staff_user_id=staff_id, device=device, browser=browser, result=result, created_at=utcnow()))
    db.commit()
    log.info("sesión %s (cuenta %s, %s/%s)", result, staff_id, device, browser)


def _station_in_use(db: Session, staff: StaffUser) -> bool:
    if not staff.session_token or staff.session_token.startswith(FREE_PREFIX):
        return False
    return db.query(PrintDevice.id).filter(PrintDevice.staff_user_id == staff.id, PrintDevice.last_seen_at >= utcnow() - STATION_ACTIVE_WINDOW).first() is not None


def _hosts_others(db: Session, staff: StaffUser) -> bool:
    """¿Esta cuenta es el anfitrión de la impresora de OTROS usuarios (alguien eligió su equipo en Parámetros)? Imprimirse a sí misma no cuenta."""
    return db.query(PrintRoute.id).filter(PrintRoute.printer_staff_id == staff.id, PrintRoute.staff_user_id != staff.id).first() is not None


def login_gate(db: Session, request, staff: StaffUser, prev_sid=None):
    """Se llama con la contraseña ya verificada. Devuelve un texto de error si el inicio de sesión se RECHAZA (cuenta de puesto en uso); si no, deja en `request.session['sid']` el
    identificador de esta sesión (cuando la política lo usa) y devuelve None. `prev_sid`: el `sid` que traía este navegador (un mismo navegador puede volver a entrar a su puesto)."""
    if not single_session_on(db):
        return None
    pol = policy(staff)
    if pol == "multi":
        return None
    protected = pol == "station" or _hosts_others(db, staff)               # puesto de impresión, o cuenta que atiende a otros equipos
    if protected and prev_sid and prev_sid == staff.session_token:
        return _issue(db, request, staff, replaced=False)                 # el mismo navegador de siempre (reinicio de pestaña, volver a entrar)
    if protected and _station_in_use(db, staff):
        audit(db, staff.id, request, "rechazada")
        return STATION_BUSY_MSG if pol == "station" else HOST_BUSY_MSG
    return _issue(db, request, staff, replaced=bool(staff.session_token) and not staff.session_token.startswith(FREE_PREFIX) and prev_sid != staff.session_token)


def _issue(db: Session, request, staff: StaffUser, replaced: bool):
    staff.session_token = secrets.token_hex(16)
    db.commit()
    request.session["sid"] = staff.session_token
    if replaced:
        audit(db, staff.id, request, "reemplazada")
    return None


def is_replaced(db: Session, request, staff: StaffUser) -> bool:
    """¿Esta sesión ya no es la vigente de su cuenta? Sin `sid` (sesión anterior al cambio) o sin token registrado: vigente."""
    if int(request.session.get("ep") or 0) != int(getattr(staff, "session_epoch", 0) or 0):
        return True                     # S2: la contraseña cambió o se restableció después de crear esta cookie (época vieja): deja de valer en TODOS los roles
    sid = request.session.get("sid")
    token = staff.session_token
    if not sid or not token or sid == token:
        return False
    if policy(staff) == "multi" or not single_session_on(db):
        return False
    key = (staff.id, sid)
    if key not in _seen_closed:
        if len(_seen_closed) > 5000:
            _seen_closed.clear()
        _seen_closed.add(key)
        audit(db, staff.id, request, "cerrada")
    return True


def logout_token() -> str:
    """Token que deja el cierre de sesión (S2): como el de `force_release`, no coincide con ningún `sid` ni cuenta como «en uso». Antes se dejaba NULL y eso volvía
    a dar por buenas TODAS las cookies viejas de la cuenta, también las ya reemplazadas."""
    return FREE_PREFIX + secrets.token_hex(8)


def revoke_all(staff: StaffUser) -> None:
    """S2: invalida TODAS las sesiones de la cuenta (restablecimiento de contraseña por enlace o por un admin). Sube la época y libera el token. El que llama confirma."""
    staff.session_epoch = int(staff.session_epoch or 0) + 1
    if staff.session_token:
        staff.session_token = logout_token()


def revoke_others(request, staff: StaffUser) -> None:
    """S2: la persona cambió su propia contraseña: se invalidan las DEMÁS sesiones de la cuenta y la actual sigue (época y `sid` nuevos en su cookie). El que llama confirma."""
    staff.session_epoch = int(staff.session_epoch or 0) + 1
    request.session["ep"] = staff.session_epoch
    if staff.session_token and request.session.get("sid") == staff.session_token:
        staff.session_token = secrets.token_hex(16)
        request.session["sid"] = staff.session_token


def force_release(db: Session, staff: StaffUser, request) -> None:
    """Un admin libera la cuenta: la sesión actual deja de valer y el siguiente inicio de sesión entra sin que lo rechace el «en uso». Queda en auditoría."""
    staff.session_token = FREE_PREFIX + secrets.token_hex(8)
    db.commit()
    audit(db, staff.id, request, "forzada")


def purge_audit(db: Session, now=None) -> int:
    cut = (now or utcnow()) - timedelta(days=AUDIT_DAYS)
    n = db.query(SessionAudit).filter(SessionAudit.created_at < cut).delete(synchronize_session=False)
    db.commit()
    return n
