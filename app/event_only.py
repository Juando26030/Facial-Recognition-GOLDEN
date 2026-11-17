"""Coordinador temporal del evento (16-nov-2026, pedido de Juan David): cuenta con los permisos de un coordinador, pero SOLO sobre el evento (o los eventos) que se le asignan.

Cómo se logra (tres capas, de afuera hacia adentro):
  1. `staff_users.event_only` marca la cuenta (rol `coordinador`). La crea una comercial, un admin o el super admin desde «Usuarios del evento», con usuario `ct-xxxxxx` y contraseña
     aleatoria que se muestra UNA sola vez (igual que el cliente temporal, app/temp_client.py). Nunca se le suman roles.
  2. Filtro por cuenta (esta lista, aplicado en `app/main.py` con lo que hay en la sesión y otra vez en `auth.get_current_staff`): solo pasan las rutas de la API que sirven para operar
     DENTRO de un evento y solo las páginas del evento, la lista de sus eventos y su calendario. Todo lo demás (clientes, CRM, configuración, inventario, gastos, cuentas de cobro, estado del
     sistema, importar/exportar, crear o duplicar eventos…) responde 403 o lleva al inicio. La lista es de PERMITIDOS: una ruta nueva queda cerrada hasta que alguien la agregue aquí
     (tests/test_coordinador_temporal.py clasifica TODAS las rutas del sistema y falla si aparece una sin clasificar).
  3. Pertenencia: `auth._scope_applies` vale siempre para esta cuenta, así que cada ruta que usa `get_event_for_staff` o `scope_events_query` solo ve los eventos con una
     `EventStaffAuthorization` suya que no estén finalizados. Si el evento finaliza, el acceso termina solo.
Este módulo es puro (sin base de datos) para poder probarlo sin servidor."""
import re
from typing import Optional

USER_PREFIX = "ct-"

# --- API: solo lo que se usa para operar dentro de un evento -------------------------------------------------------------------------------------------------------------------------
# Prefijos permitidos con cualquier método (cada ruta valida el evento con get_event_for_staff).
API_ALLOWED_PREFIXES = (
    "/api/events/", "/api/events", "/api/users", "/api/register", "/api/recognize/", "/api/checkin-cedula/", "/api/door-face", "/api/email-check", "/api/email-validate",
    "/api/bulk_", "/api/report/", "/api/attendees/", "/api/badge-assets/", "/api/saved-badge-templates", "/api/reprint-requests", "/api/print-stations", "/api/uploads/",
    "/api/qr/", "/api/form-id-docs/", "/api/cities", "/api/ingreso/", "/api/me/", "/api/my-events", "/api/notifications", "/api/password-policy", "/api/ping-auth", "/api/session/",
    "/api/email-assets/",
)
# Solo lectura (GET): catálogos que las pantallas del evento necesitan y que el coordinador temporal no puede cambiar.
API_GET_ONLY_PREFIXES = ("/api/colors", "/api/event-states", "/api/event-template", "/api/event-types", "/api/calendar/", "/api/settings/golden-logo-height", "/api/ops/version-check")
# Rutas puntuales de /api/staff que usa «Usuarios del evento» (restablecer contraseña y correo de los digitadores del evento; cada una valida a quién puede administrar).
API_ALLOWED_REGEX = (re.compile(r"^/api/staff/\d+/(password|email)$"),)
# Excepciones DENTRO de los prefijos permitidos: cosas que cruzan eventos o crean otros.
API_DENIED = (
    ("POST", re.compile(r"^/api/events/?$")),                # crear un evento (GET /api/events es la lista, ya recortada a sus eventos)
    (None, re.compile(r"^/api/events/next-code$")),
    (None, re.compile(r"^/api/events/\d+/duplicate(-suggestion)?$")),
    (None, re.compile(r"^/api/calendar/(notes|notifiable-staff)")),      # notas y avisos del equipo completo
    (None, re.compile(r"^/api/events/\d+/staff-users/assign-existing$")),
)

# --- Páginas del personal que NO se le abren (el resto de rutas de página es pública, del evento o de sesión) --------------------------------------------------------------------
PAGE_DENIED_PREFIXES = ("/crm", "/clientes", "/configuracion", "/inventario", "/gastos", "/cuentas-de-cobro", "/sincronizacion", "/servidor-local", "/impresion-usb", "/sistema",
                        "/admin", "/eventos/nuevo")

_EVENT_PATH = re.compile(r"^/api/events/(\d+)(?:/|$)")
_KIOSK_PATH = re.compile(r"^/kiosk/(\d+)(?:/|$)")


def event_id_in_path(path: str) -> Optional[int]:
    """El número de evento que nombra la ruta (/api/events/{id}/… o /kiosk/{id}/…), o None."""
    m = _EVENT_PATH.match(path) or _KIOSK_PATH.match(path)
    return int(m.group(1)) if m else None


def _under(path: str, prefix: str) -> bool:
    """`/api/events` cubre /api/events y /api/events/…, nunca /api/eventsX; un prefijo que termina en «_» (/api/bulk_) cubre todo lo que empieza así."""
    base = prefix.rstrip("/")
    return path.startswith(base) if base.endswith("_") else (path == base or path.startswith(base + "/"))


def api_allowed(method: str, path: str) -> bool:
    """¿Puede una cuenta de coordinador temporal llamar a esta ruta de la API? (Solo la forma; el evento lo valida cada ruta.)"""
    if not path.startswith("/api/"):
        return True
    if any((m is None or m == method.upper()) and rx.match(path) for m, rx in API_DENIED):
        return False
    if any(rx.match(path) for rx in API_ALLOWED_REGEX):
        return True
    if any(_under(path, p) for p in API_ALLOWED_PREFIXES):
        return True
    if method.upper() == "GET" and any(_under(path, p) for p in API_GET_ONLY_PREFIXES):
        return True
    return False


def page_allowed(path: str) -> bool:
    """¿Se le abre esta página? Todo lo que no sea una pantalla global del personal (las de evento, la lista de sus eventos, su calendario, las públicas)."""
    if path.startswith("/api/"):
        return True
    return not any(path == p or path.startswith(p + "/") for p in PAGE_DENIED_PREFIXES)
