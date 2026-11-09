"""Autorregistro sin base de datos en el kiosco (Fase 8, pieza 3).

Una pantalla aparte (`/kiosk/{id}/autoregistro`, abierta con una cuenta del personal, como «Entrar con mi rostro») donde la PERSONA se crea sola con una versión mínima del «Registrar nuevo»:
cédula, nombres y solo lo OBLIGATORIO del evento (Parámetros → campos). Reutiliza el alta de siempre (`_manual_register`), con origen y método «autoregistro».

Reglas:
- Solo con el interruptor del evento encendido (`Event.selfreg_enabled`, apagado de fábrica) y el evento «En proceso» (la misma puerta de registrar: `require_event_in_progress`).
- Sin rostro, sin foto, sin biometría: la pantalla no capta nada biométrico (la autorización biométrica la da la persona en la pantalla de la auditora, no aquí). Menores: sin biometría por diseño.
- No se puede ver ni buscar a otras personas; una cédula repetida da un mensaje amable que NO revela datos (ni si existía, ni de quién es).
- Límite de intentos por equipo y evento (`SELFREG_MAX_PER_10MIN`, 40 por defecto): el contador vive en memoria de cada proceso (basta para frenar un abuso; no es una cuota exacta).
- La pantalla se reinicia sola tras cada registro y tras un rato sin tocarla (static/js/selfreg.js).
- Seguridad (F5-9 B): la persona de prueba (PRUEBA) no se autorregistra. Si la cédula YA existe en el cliente, la pantalla solo marca el ingreso cuando el nombre escrito coincide con el
  guardado (`same_person`) y NUNCA cambia sus datos: ni fecha de nacimiento (una fecha de menor borraría su biometría), ni correo de la escarapela digital (se la enviaría a otro), ni
  categorías. Quien escribe la cédula de otra persona no puede marcarle el ingreso, borrarle el rostro ni quedarse con su credencial.
"""
import os
import re
import time
import unicodedata
from collections import defaultdict, deque
from typing import Optional

MAX_PER_WINDOW = int(os.getenv("SELFREG_MAX_PER_10MIN", "40"))
WINDOW_S = 600
SUPPORTED_TYPES = ("text_short", "text_long", "select", "boolean", "consent", "email", "date", "categories", "certificate", "digital_contact")
ALWAYS = ("id", "first_name")                     # siempre se piden
DIRECT = ("role", "entity", "phone", "email", "opt_1", "birth_date", "certificate", "digital_contact", "categories")      # parámetros propios del alta; lo demás (opcional_N) viaja en extra_fields

_hits: dict = defaultdict(deque)


def allow(key: tuple, now: Optional[float] = None) -> bool:
    """True si el equipo `key` (evento, cuenta) todavía puede registrar; cuenta el intento. Ventana deslizante de 10 minutos."""
    now = time.monotonic() if now is None else now
    q = _hits[key]
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= MAX_PER_WINDOW:
        return False
    q.append(now)
    return True


def reset() -> None:
    _hits.clear()


def form_fields(field_configs: list) -> tuple:
    """(campos que pide la pantalla, nombres de los obligatorios que la pantalla NO sabe pedir). Cédula y nombres siempre; apellidos y el resto solo si son obligatorios en Parámetros.
    Un obligatorio de un tipo que la pantalla no maneja (firma) hace que el autorregistro no se pueda ofrecer: se avisa al personal en vez de dejar a la persona atascada."""
    fields, unsupported = [], []
    for cfg in field_configs:
        key = cfg["key"]
        required = bool(cfg.get("required")) or key in ALWAYS
        if not required:
            continue
        ftype = cfg.get("field_type") or "text_short"
        if ftype not in SUPPORTED_TYPES:
            unsupported.append(cfg.get("label") or key)
            continue
        fields.append({"key": key, "label": cfg.get("label") or key, "type": ftype, "required": True, "options": list(cfg.get("options") or []), "help": cfg.get("help_text") or ""})
    order = {"id": 0, "first_name": 1, "last_name": 2}
    fields.sort(key=lambda f: order.get(f["key"], 3))          # cédula y nombres primero; el resto, en el orden de Parámetros (el sort es estable)
    return fields, unsupported


def split_values(values: dict) -> tuple:
    """Separa lo que llega en `values` en los parámetros propios del alta y los campos opcionales (opcional_N)."""
    direct, extras = {}, {}
    for k, v in (values or {}).items():
        k = str(k)
        v = "" if v is None else (str(v).strip() if not isinstance(v, (list, dict)) else v)
        if k in DIRECT:
            direct[k] = v
        elif k.startswith("opcional_"):
            extras[k] = v
    return direct, extras


def _name_tokens(text) -> set:
    plain = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return {t for t in re.split(r"[^a-z0-9]+", plain) if len(t) >= 2}


def same_person(typed_first, stored_first) -> bool:
    """¿El nombre escrito en el kiosco corresponde al guardado? Basta UNA palabra del nombre en común (sin tildes ni mayúsculas): «maria» vale para «María José».
    Sin nombre guardado no se puede comprobar: no coincide (la persona va al punto de ayuda)."""
    stored = _name_tokens(stored_first)
    return bool(stored) and bool(_name_tokens(typed_first) & stored)
