"""Columnas de la base que se carga ("Adjuntar Base de Datos"): reconocer por el TÍTULO de cada columna a qué campo de la persona corresponde.

Dos formas de traer datos adicionales, que conviven en el mismo archivo:
  a) columnas «opcional 1»…«opcional 30» de la plantilla: el sistema detecta cuáles traen datos y pregunta qué son (NEEDS_LABELS, ver app/routers/api.py);
  b) columnas con título propio («fecha de nacimiento», «talla de camisa»…): si el título es el de un campo conocido (sin importar mayúsculas, tildes ni variantes comunes) se asigna a ese campo; si no,
     se crea un campo opcional de texto con ese título en los parámetros del evento, SIN preguntar. Volver a cargar el mismo archivo reutiliza ese campo (se busca por título): no crea otro.
Ninguna columna se ignora en silencio: `canonicalize` devuelve el informe «reconocidos / nuevos creados / no usadas» que la pantalla le muestra a quien carga.
"""
import re
import unicodedata

MAX_OPTIONAL_FIELDS = 30
_OPTIONAL_RE = re.compile(r"^opcional[\s_]*([0-9]{1,2})$")

# nombre canónico (el que ya buscan las filas de bulk_register) → títulos equivalentes, ya normalizados (minúsculas, sin tildes, signos como espacio)
KNOWN = {
    "id": {"id", "identificacion", "cedula", "cedula de ciudadania", "cc", "c c", "documento", "documento de identidad", "numero de documento", "numero documento", "no documento", "nro documento",
           "n documento", "numero de cedula", "numero cedula", "nro cedula"},
    "nombres": {"nombres", "nombre"},   # «nombres y apellidos» en UNA columna no se puede partir con certeza: queda como campo propio en vez de adivinar
    "apellidos": {"apellidos", "apellido"},
    "cargo": {"cargo", "puesto", "posicion"},
    "entidad": {"entidad", "empresa", "organizacion", "compania", "institucion"},
    "telefono": {"telefono", "tel", "celular", "tel celular", "telefono celular", "movil", "numero de celular", "numero celular", "whatsapp"},
    "correo": {"correo", "email", "e mail", "mail", "correo electronico", "e mail corporativo", "email corporativo"},
    "tipo de asistente": {"tipo de asistente", "tipo asistente", "tipo de asistentes"},
    "categoria": {"categoria", "categorias"},
    "certificado": {"certificado", "certificado de asistencia"},
    "fecha de nacimiento": {"fecha de nacimiento", "fecha nacimiento", "nacimiento", "fecha de nac", "fec nacimiento", "fecha nac", "f nacimiento", "birth date", "birthdate", "date of birth", "dob"},
}
_LOOKUP = {variant: canonical for canonical, variants in KNOWN.items() for variant in variants}

LABELS = {"id": "Cédula", "nombres": "Nombres", "apellidos": "Apellidos", "cargo": "Cargo", "entidad": "Entidad", "telefono": "Teléfono", "correo": "Correo", "tipo de asistente": "Tipo de asistente",
          "categoria": "Categoría", "certificado": "Certificado", "fecha de nacimiento": "Fecha de nacimiento"}


def norm(title) -> str:
    """Minúsculas, sin tildes, signos (_ - . / :) como espacio y espacios colapsados."""
    text = unicodedata.normalize("NFD", str(title or "").strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[_\-./:]+", " ", text)).strip()


def optional_key(title):
    """'opcional 3' / 'opcional_3' / 'opcional3' → 'opcional_3' (1 a 30); None si no es una columna opcional de la plantilla."""
    m = _OPTIONAL_RE.match(str(title or "").strip().lower())
    n = int(m.group(1)) if m else 0
    return f"opcional_{n}" if 1 <= n <= MAX_OPTIONAL_FIELDS else None


def _pretty(title: str) -> str:
    t = str(title).strip()
    return t[:1].upper() + t[1:]


def canonicalize(header_columns: dict, rows: list, event_labels: dict):
    """(header_columns, rows) tal como salen de la lectura (títulos en minúscula) → (header_columns, rows, informe, etiquetas_nuevas) con los títulos conocidos renombrados a su nombre canónico y los
    títulos propios reasignados a un campo opcional libre. `event_labels` = {opcional_N: etiqueta} que el evento ya tiene (un título igual a una etiqueta existente REUTILIZA ese campo).
    `etiquetas_nuevas` = {opcional_N: título} solo de los campos que hay que crear. Informe: {"recognized": [{title, field}], "created": [{title, field}], "unused": [{title, reason}]}."""
    rename, report = {}, {"recognized": [], "created": [], "unused": []}
    taken = set()                                                   # nombres canónicos ya asignados (una segunda columna del mismo campo no se usa)
    explicit = {optional_key(h) for h in header_columns} - {None}
    used_slots = set(event_labels) | explicit
    by_label = {norm(v): k for k, v in event_labels.items()}
    new_labels = {}
    has_data = {h: any(str(r.get(h) or "").strip() for r in rows) for h in header_columns}
    for h in header_columns:
        key = optional_key(h)
        if key:
            rename[h] = key
            report["recognized" if has_data[h] else "unused"].append({"title": h, "field": event_labels.get(key) or f"Opcional {key.split('_')[1]}"} if has_data[h]
                                                                    else {"title": h, "reason": "columna opcional vacía"})
            continue
        canonical = _LOOKUP.get(norm(h))
        if canonical:
            if canonical in taken:
                report["unused"].append({"title": h, "reason": f"repetida: ya se usó otra columna para «{LABELS[canonical]}»"})
                continue
            taken.add(canonical)
            rename[h] = canonical
            report["recognized"].append({"title": h, "field": LABELS[canonical]})
            continue
        if not has_data[h]:
            report["unused"].append({"title": h, "reason": "columna vacía"})
            continue
        slot = by_label.get(norm(h)) or next((k for k, v in new_labels.items() if norm(v) == norm(h)), None)
        created = False
        if slot is None:
            slot = next((f"opcional_{n}" for n in range(1, MAX_OPTIONAL_FIELDS + 1) if f"opcional_{n}" not in used_slots), None)
            if slot is None:
                report["unused"].append({"title": h, "reason": f"el evento ya tiene {MAX_OPTIONAL_FIELDS} campos opcionales: no hay lugar para uno nuevo"})
                continue
            used_slots.add(slot)
            new_labels[slot] = _pretty(h)
            created = True
        rename[h] = slot
        report["created" if created else "recognized"].append({"title": h, "field": event_labels.get(slot) or new_labels[slot]})
    for h in header_columns:
        if h not in rename and not any(u["title"] == h for u in report["unused"]):
            report["unused"].append({"title": h, "reason": "no se pudo asignar"})
    new_header = {rename[h]: letter for h, letter in header_columns.items() if h in rename}
    new_rows = [{rename[h]: v for h, v in r.items() if h in rename} for r in rows]
    return new_header, new_rows, report, new_labels


def drop_column(header_columns: dict, rows: list, report: dict, canonical: str, reason: str) -> None:
    """Quita una columna ya reconocida (queda en el informe como «no usada», con el motivo): nada se ignora en silencio."""
    header_columns.pop(canonical, None)
    for row in rows:
        row.pop(canonical, None)
    for item in [i for i in report["recognized"] if i["field"] == LABELS[canonical]]:
        report["recognized"].remove(item)
        report["unused"].append({"title": item["title"], "reason": reason})


def merge_reports(*reports) -> dict:
    """Une los informes de varios lotes de una misma carga: una columna cuenta como «nueva» si en algún lote se creó; «no usada» solo si en ningún lote se usó."""
    out = {"recognized": [], "created": [], "unused": []}
    seen = {}
    for rep in reports:
        for kind in ("created", "recognized"):
            for item in rep.get(kind, []):
                if item["title"] not in seen or kind == "created":
                    seen[item["title"]] = (kind, item)
    for kind, item in seen.values():
        out[kind].append(item)
    for rep in reports:
        for item in rep.get("unused", []):
            if item["title"] not in seen and not any(u["title"] == item["title"] for u in out["unused"]):
                out["unused"].append(item)
    return out


def summary(report: dict) -> str:
    return (f"Campos reconocidos: {len(report['recognized'])} · campos nuevos creados: {len(report['created'])} · columnas no usadas: {len(report['unused'])}.")
