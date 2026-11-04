"""Columnas de la base que se carga ("Adjuntar Base de Datos"): reconocer por el TÍTULO de cada columna a qué campo de la persona corresponde.

Dos formas de traer datos adicionales, que conviven en el mismo archivo:
  a) columnas «opcional 1»…«opcional N» de la plantilla: el sistema detecta cuáles traen datos y pregunta qué son (NEEDS_LABELS, ver app/routers/api.py);
  b) columnas con título propio («fecha de nacimiento», «talla de camisa»…): si el título es el de un campo conocido (sin importar mayúsculas, tildes ni variantes comunes) se asigna a ese campo; si no,
     se crea un campo opcional de texto con ese título en los parámetros del evento, SIN preguntar. Volver a cargar el mismo archivo reutiliza ese campo (se busca por título): no crea otro.
Ninguna columna se ignora en silencio: `canonicalize` devuelve el informe «reconocidos / nuevos creados / no usadas» que la pantalla le muestra a quien carga.
"""
import re
import unicodedata

MAX_OPTIONAL_FIELDS = 500          # techo TÉCNICO (archivos corruptos o columnas por error), no un límite de producto: un evento puede traer 60 o más campos propios (Plan 5)
_OPTIONAL_RE = re.compile(r"^opcional[\s_]*([0-9]{1,3})$")

# nombre canónico (el que ya buscan las filas de bulk_register) → títulos equivalentes, ya normalizados (minúsculas, sin tildes, signos como espacio)
KNOWN = {
    "id": {"id", "identificacion", "cedula", "cedula de ciudadania", "cc", "c c", "documento", "documento de identidad", "numero de documento", "numero documento", "no documento", "nro documento",
           "n documento", "numero de cedula", "numero cedula", "nro cedula"},
    "nombres": {"nombres", "nombre", "nombre s", "nombre(s)", "nombre (s)", "nombres(s)", "nombre completo", "nombres completos", "nombres y apellidos", "nombre y apellidos", "nombre y apellido", "nombres y apellido", "nombre apellido", "nombre completo y apellidos",
                "full name", "name"},   # «nombre completo» / «nombres y apellidos» en UNA columna NO se parte (no se puede con certeza): todo va a nombres y apellidos queda vacío, sin error (Plan 5)
    "apellidos": {"apellidos", "apellido"},
    "cargo": {"cargo", "puesto", "posicion"},
    "entidad": {"entidad", "empresa", "organizacion", "compania", "institucion"},
    "telefono": {"telefono", "tel", "celular", "tel celular", "telefono celular", "movil", "numero de celular", "numero celular", "whatsapp"},
    "correo": {"correo", "email", "e mail", "mail", "correo electronico", "e mail corporativo", "email corporativo"},
    "tipo de asistente": {"tipo de asistente", "tipo asistente", "tipo de asistentes"},
    "categoria": {"categoria", "categorias"},
    "certificado": {"certificado", "certificado de asistencia"},
    "registrado en formulario": {"registrado en formulario", "registrado en el formulario", "registrado formulario", "registrada en formulario", "ya registrado en formulario", "ya inscrito", "inscrito en formulario",
                                 "inscrito formulario", "ya inscrito en formulario"},
    "fecha de nacimiento": {"fecha de nacimiento", "fecha nacimiento", "nacimiento", "fecha de nac", "fec nacimiento", "fecha nac", "f nacimiento", "birth date", "birthdate", "date of birth", "dob"},
}
_LOOKUP = {variant: canonical for canonical, variants in KNOWN.items() for variant in variants}

LABELS = {"id": "Cédula", "nombres": "Nombres", "apellidos": "Apellidos", "cargo": "Cargo", "entidad": "Entidad", "telefono": "Teléfono", "correo": "Correo", "tipo de asistente": "Tipo de asistente",
          "categoria": "Categoría", "certificado": "Certificado", "registrado en formulario": "Registrado en formulario", "fecha de nacimiento": "Fecha de nacimiento"}


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


DUP_MARK = " #dup"          # app/routers/api.py `_read_roster_rows` marca así la 2.ª, 3.ª… columna con el MISMO título (la primera se usa; las demás se informan, no se pisan en silencio)
ORIGINAL_ID_LABEL = "Cédula original"      # campo opcional automático de «No eliminar repetidos» (app/roster_dups.py)


def canonicalize(header_columns: dict, rows: list, event_labels: dict, create_fields: bool = True):
    """(header_columns, rows) tal como salen de la lectura (títulos en minúscula) → (header_columns, rows, informe, etiquetas_nuevas) con los títulos conocidos renombrados a su nombre canónico y los
    títulos propios reasignados a un campo opcional libre. `event_labels` = {opcional_N: etiqueta} que el evento ya tiene (un título igual a una etiqueta existente REUTILIZA ese campo).
    `etiquetas_nuevas` = {opcional_N: título} solo de los campos que hay que crear. Con `create_fields=False` («solo agregar») NUNCA se crea un campo: la columna que no corresponde a un campo que el
    evento ya tiene queda como «no usada» en el informe. Informe: {"recognized": [{title, field}], "created": [{title, field}], "unused": [{title, reason}],
    "columns": [{title, kind: entendida|opcional|ignorada, field|reason}]} — este último, columna por columna y en el orden del archivo, es el que ve quien carga (Plan 5)."""
    rename, report = {}, {"recognized": [], "created": [], "unused": [], "columns": []}
    kinds = {}                                                      # título → (kind, field, reason) para el informe por columna
    taken = set()                                                   # nombres canónicos ya asignados (una segunda columna del mismo campo no se usa)
    explicit = {optional_key(h) for h in header_columns} - {None}
    used_slots = set(event_labels) | explicit
    by_label = {norm(v): k for k, v in event_labels.items()}
    new_labels = {}
    has_data = {h: any(str(r.get(h) or "").strip() for r in rows) for h in header_columns}

    def unused(h, reason):
        report["unused"].append({"title": h, "reason": reason})
        kinds[h] = ("ignorada", "", reason)

    for h in header_columns:
        if DUP_MARK in h:
            unused(h, "columna repetida: se usó la primera con ese título")
            report["unused"][-1]["title"] = h.split(DUP_MARK)[0]
            continue
        key = optional_key(h)
        if key:
            if not create_fields and key not in event_labels:
                unused(h, "este evento no tiene ese campo opcional: no se crean campos nuevos")
                continue
            rename[h] = key
            if has_data[h]:
                field = event_labels.get(key) or f"Opcional {key.split('_')[1]}"
                report["recognized"].append({"title": h, "field": field})
                kinds[h] = ("opcional", field, "")
            else:
                unused(h, "columna opcional vacía")
            continue
        canonical = _LOOKUP.get(norm(h))
        if canonical:
            if canonical in taken:
                unused(h, f"repetida: ya se usó otra columna para «{LABELS[canonical]}»")
                continue
            taken.add(canonical)
            rename[h] = canonical
            report["recognized"].append({"title": h, "field": LABELS[canonical]})
            kinds[h] = ("entendida", LABELS[canonical], "")
            continue
        if not has_data[h]:
            unused(h, "columna vacía")
            continue
        slot = by_label.get(norm(h)) or next((k for k, v in new_labels.items() if norm(v) == norm(h)), None)
        created = False
        if slot is None and not create_fields:
            unused(h, "no corresponde a ningún campo de este evento: no se crean campos nuevos")
            continue
        if slot is None:
            slot = next((f"opcional_{n}" for n in range(1, MAX_OPTIONAL_FIELDS + 1) if f"opcional_{n}" not in used_slots), None)
            if slot is None:
                unused(h, f"se alcanzó el techo técnico de {MAX_OPTIONAL_FIELDS} campos opcionales por evento: no hay lugar para «{_pretty(h)}». Revisa que el archivo no tenga columnas de más (¿archivo dañado?)")
                continue
            used_slots.add(slot)
            new_labels[slot] = _pretty(h)
            created = True
        rename[h] = slot
        field = event_labels.get(slot) or new_labels[slot]
        report["created" if created else "recognized"].append({"title": h, "field": field})
        kinds[h] = ("opcional", field, "")
    for h in header_columns:
        if h not in kinds:
            unused(h, "no se pudo asignar")
    report["columns"] = [({"title": h.split(DUP_MARK)[0], "kind": k, "field": f} if k != "ignorada" else {"title": h.split(DUP_MARK)[0], "kind": k, "reason": r}) for h in header_columns for k, f, r in [kinds[h]]]
    new_header = {rename[h]: letter for h, letter in header_columns.items() if h in rename}
    new_rows = [{rename[h]: v for h, v in r.items() if h in rename} for r in rows]
    return new_header, new_rows, report, new_labels


def free_slot(used_labels: dict, extra_taken=()) -> str:
    """Primer campo opcional sin usar (opcional_1…30) o None si el evento ya tiene el máximo."""
    return next((f"opcional_{n}" for n in range(1, MAX_OPTIONAL_FIELDS + 1) if f"opcional_{n}" not in used_labels and f"opcional_{n}" not in extra_taken), None)


def drop_column(header_columns: dict, rows: list, report: dict, canonical: str, reason: str) -> None:
    """Quita una columna ya reconocida (queda en el informe como «no usada», con el motivo): nada se ignora en silencio."""
    header_columns.pop(canonical, None)
    for row in rows:
        row.pop(canonical, None)
    for item in [i for i in report["recognized"] if i["field"] == LABELS[canonical]]:
        report["recognized"].remove(item)
        report["unused"].append({"title": item["title"], "reason": reason})
        for col in report.get("columns", []):
            if col["title"] == item["title"]:
                col.pop("field", None)
                col.update(kind="ignorada", reason=reason)


def merge_reports(*reports) -> dict:
    """Une los informes de varios lotes de una misma carga: una columna cuenta como «nueva» si en algún lote se creó; «no usada» solo si en ningún lote se usó."""
    out = {"recognized": [], "created": [], "unused": [], "columns": []}
    seen = {}
    cols = {}
    for rep in reports:                                                # por columna: gana el lote donde se usó (entendida/opcional) sobre «ignorada» (p. ej. vacía en un lote y con datos en otro)
        for col in rep.get("columns", []):
            if col["title"] not in cols or (cols[col["title"]]["kind"] == "ignorada" and col["kind"] != "ignorada"):
                cols[col["title"]] = col
    out["columns"] = list(cols.values())
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


def public(report: dict) -> dict:
    """Lo que se le devuelve a quien carga: `columns` = los tres listados de siempre (reconocidos / nuevos / no usados) y `columns_detail` = el informe por columna (Plan 5)."""
    return {"columns": {k: v for k, v in report.items() if k != "columns"}, "columns_detail": report.get("columns", [])}


def summary(report: dict) -> str:
    return (f"Campos reconocidos: {len(report['recognized'])} · campos nuevos creados: {len(report['created'])} · columnas no usadas: {len(report['unused'])}.")
