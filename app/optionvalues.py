"""Valores que ya existen en la base para un campo del evento, para armar sus opciones de lista desplegable (P7).
Lógica pura (sin base ni HTTP): qué campos se pueden consultar y cómo se agrupan las variantes («Bogota» / «Bogotá»).
PRIVACIDAD: las opciones de un formulario público las ve cualquiera; por eso solo se consultan campos NO identificantes y el
resultado son valores sueltos con su conteo, nunca registros de personas."""
import re

from app.formlib import norm_value

LIMIT = 200                      # tope de opciones distintas que se devuelven
MAX_VALUE_LEN = 120              # igual que una opción de formulario (formlib: _text(o, 120))
# Solo estos campos del evento (lista blanca): cargo, entidad, tipo de asistente, categoría y los opcionales.
ALLOWED_FIXED = ("role", "entity", "opt_1", "categories")
# Un opcional lo nombra el cliente: si su nombre dice que es un dato personal, tampoco se consulta.
_IDENTIFYING = re.compile(r"c[eé]dula|documento|identific|nombre|apellido|correo|e-?mail|mail|tel[eé]fono|celular|m[oó]vil|whats|nacimiento|naci[oó]|direcci[oó]n|\bcc\b|\bnit\b|pasaporte", re.I)


def check_key(key: str, label: str = "") -> None:
    """Lanza ValueError (mensaje en español) si el campo no se puede consultar."""
    if not (key in ALLOWED_FIXED or re.fullmatch(r"opcional_\d{1,2}", key or "")):
        raise ValueError("Este campo identifica a las personas (cédula, nombres, correo, teléfono, fecha de nacimiento…): sus valores no se pueden traer como opciones.")
    if key.startswith("opcional_") and _IDENTIFYING.search(label or ""):
        raise ValueError(f"«{label}» parece un dato personal: sus valores no se pueden traer como opciones públicas.")


def group_values(counts: dict, limit: int = LIMIT) -> dict:
    """`counts`: {valor tal cual: veces}. Junta las variantes que solo difieren en espacios, mayúsculas o tildes.
    Devuelve {"groups": [{"values": [{"value","count"}], "suggested", "count"}] (A–Z), "total", "truncated", "limit", "skipped"}.
    Con más de `limit` grupos quedan los más frecuentes (el resto se avisa en `total`/`truncated`)."""
    by_norm, skipped = {}, 0
    for raw, n in counts.items():
        value = " ".join(str(raw or "").split())
        if not value:
            continue
        if len(value) > MAX_VALUE_LEN:
            skipped += 1
            continue
        by_norm.setdefault(norm_value(value), {})
        by_norm[norm_value(value)][value] = by_norm[norm_value(value)].get(value, 0) + n
    groups = []
    for variants in by_norm.values():
        # la sugerida: la más frecuente; a igualdad, la que tiene tildes/mayúsculas (suele ser la bien escrita)
        ordered = sorted(variants.items(), key=lambda kv: (-kv[1], -sum(not c.isascii() for c in kv[0]), kv[0]))
        groups.append({"values": [{"value": v, "count": n} for v, n in ordered], "suggested": ordered[0][0], "count": sum(variants.values())})
    total, truncated = len(groups), len(groups) > limit
    if truncated:
        groups = sorted(groups, key=lambda g: (-g["count"], g["suggested"]))[:limit]
    groups.sort(key=lambda g: (norm_value(g["suggested"]), g["suggested"]))
    return {"groups": groups, "total": total, "truncated": truncated, "limit": limit, "skipped": skipped}
