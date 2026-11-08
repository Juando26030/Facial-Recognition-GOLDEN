"""Datos visibles en la escarapela digital pública (/b/<token>): lógica PURA, se prueba sola.

El evento puede elegir (Parámetros > Escarapelas) qué datos de la persona salen en su enlace. `events.digital_badge_fields` guarda una lista JSON de claves:
  * NULL  = comportamiento de siempre: solo los campos que la plantilla de escarapela pinta de verdad.
  * lista = exactamente esos campos (los que el evento tenga y estén permitidos). Nombre y apellido salen siempre.
Claves permitidas: role, entity, opt_1, categories, opcional_N (los rótulos del evento) y, SOLO si se marcan expresamente, phone y email.
La cédula (`id`) no es una clave elegible: no se puede marcar. (El QR de la escarapela la lleva como siempre; no es un campo de texto.)"""
import json
import re
from typing import Iterable, Optional

BASE_KEYS = ("role", "entity", "opt_1", "categories")
SENSITIVE_KEYS = ("phone", "email")           # datos de contacto: nunca por defecto, solo marcados a mano
OPTIONAL_RE = re.compile(r"^opcional_\d{1,3}$")
MAX_KEYS = 120

SENSITIVE_WARNING = ("Teléfono y correo son datos personales: los verá cualquier persona que tenga el enlace de la escarapela. "
                     "Márcalos solo si la persona lo sabe y es necesario.")


class FieldsError(ValueError):
    """Lista inválida; el mensaje va en español, listo para mostrar."""


def allowed_keys(optional_labels: Optional[dict]) -> list:
    """Claves que este evento puede mostrar (en orden): base + opcionales rotulados + datos de contacto."""
    optional = sorted((k for k in (optional_labels or {}) if OPTIONAL_RE.match(k)), key=lambda k: int(k.split("_")[1]))
    return [*BASE_KEYS, *optional, *SENSITIVE_KEYS]


def parse_stored(raw: Optional[str]) -> Optional[list]:
    """Texto guardado -> lista de claves o None (nulo, vacío o dañado = por defecto)."""
    if raw is None or not str(raw).strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return [k for k in value if isinstance(k, str)] if isinstance(value, list) else None


def validate(value, optional_labels: Optional[dict]) -> Optional[list]:
    """Valida lo que manda el administrador. None -> None (por defecto). Rechaza lo que no sea lista de textos y toda clave fuera del conjunto permitido."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_KEYS or not all(isinstance(k, str) for k in value):
        raise FieldsError("La lista de datos de la escarapela no es válida")
    allowed = set(allowed_keys(optional_labels))
    unknown = [k for k in dict.fromkeys(value) if k not in allowed]
    if unknown:
        raise FieldsError("Dato no permitido en la escarapela digital: " + ", ".join(k[:40] for k in unknown[:5]))
    return list(dict.fromkeys(value))


def visible_keys(stored: Optional[list], template_vars: Iterable[str], optional_labels: Optional[dict]) -> set:
    """Claves que se entregan en la consulta pública. Sin lista: las que la plantilla usa (menos contacto, como siempre). Con lista: las elegidas que sigan permitidas."""
    allowed = set(allowed_keys(optional_labels))
    if stored is None:
        return {k for k in template_vars if k in allowed and k not in SENSITIVE_KEYS}
    return {k for k in stored if k in allowed}


def build_person(user, attendee, keys: set) -> dict:
    """{campos planos, extra_fields} solo con las claves visibles. Nunca cédula ni encodings."""
    flat = {"role": user.role, "entity": user.entity, "opt_1": user.opt_1, "categories": ", ".join(attendee.get_categories()),
            "phone": user.phone, "email": user.email}
    out = {k: v for k, v in flat.items() if k in keys}
    out["extra_fields"] = {k: v for k, v in user.get_extras().items() if k in keys and OPTIONAL_RE.match(k)}
    return out


def display_list(keys: set, person: dict, labels: dict, order: list) -> list:
    """[{key, label, value}] de lo marcado que tenga valor, en el orden de `order` (para la lista bajo el nombre)."""
    extras = person.get("extra_fields") or {}
    rows = []
    for k in order:
        if k not in keys:
            continue
        value = extras.get(k) if k in extras else person.get(k)
        if value not in (None, ""):
            rows.append({"key": k, "label": labels.get(k) or k, "value": str(value)})
    return rows
