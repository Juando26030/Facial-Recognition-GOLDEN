"""Lista de «Personas ya registradas» con datos del formulario (cupos por variables). Lógica pura: sin base ni HTTP.

Una lista de solo cédulas (lo de siempre) bloquea repetidos y, con «ocupar cupo», cuenta contra el cupo GENERAL. Para que además cuente contra los cupos
por variables (p. ej. por ciudad) la fila tiene que guardar los valores de los campos que definen esos cupos: aquí se reconocen las columnas del archivo
que corresponden a campos del formulario y se arma el diccionario {id de campo: valor} que se guarda con cada persona."""
from typing import Optional

from app.roster_columns import norm

STORE_TYPES = ("text_short", "text_long", "email", "phone", "number", "date", "select", "radio")          # campos cuyo valor se puede traer en una columna (no casillas, archivos ni pagos)
CANONICAL_KEY = {"nombres": "first_name", "apellidos": "last_name", "correo": "email", "telefono": "phone", "id": "id"}      # columna reconocida por la base → clave de campo del evento
MAX_VALUE = 200


def quota_field_ids(rules: list) -> set:
    """Campos que definen algún cupo por variables (los que aparecen en las condiciones de las reglas vigentes)."""
    return {c["field"] for r in rules for c in r.get("conds", [])}


def field_titles(field: dict, event_label_by_key: dict) -> list:
    """Títulos con los que una columna del archivo puede referirse a un campo: su etiqueta en el formulario, su nombre interno y el del campo del evento."""
    out = [field.get("label"), field.get("internal_name"), (event_label_by_key or {}).get(field.get("key") or "")]
    return [t for t in out if t]


def match_columns(design: dict, headers: list, canonical_of: dict, event_label_by_key: dict, skip: Optional[set] = None) -> dict:
    """{id de campo: título de columna} de las columnas del archivo que corresponden a campos del formulario.
    `headers` = títulos tal como los lee la carga (minúsculas). `canonical_of` = {título: nombre canónico} (cédula, nombres, apellidos, correo, teléfono…).
    `skip` = títulos que ya se usan para otra cosa (la columna de la cédula o la marca «Registrado en formulario»). Una columna se asigna a un solo campo."""
    skip = skip or set()
    by_norm = {norm(h): h for h in headers if h not in skip}
    taken, out = set(), {}
    for fid, f in design["fields"].items():
        if f.get("type") not in STORE_TYPES:
            continue
        col = next((by_norm[norm(t)] for t in field_titles(f, event_label_by_key) if norm(t) in by_norm and by_norm[norm(t)] not in taken), None)
        if col is None and f.get("key"):
            col = next((h for h, canon in canonical_of.items() if h not in skip and h not in taken and CANONICAL_KEY.get(canon) == f["key"]), None)
        if col is not None:
            out[fid] = col
            taken.add(col)
    # segunda pasada, solo columnas sin dueño: un título que CONTIENE todas las palabras de la etiqueta del campo («Ciudad del evento» para «Ciudad»), si hay un único candidato
    free = {h: set(norm(h).split()) for h in headers if h not in skip and h not in taken}
    for fid, f in design["fields"].items():
        if fid in out or f.get("type") not in STORE_TYPES or not f.get("label"):
            continue
        words = set(norm(f["label"]).split())
        cands = [h for h, w in free.items() if h not in taken and words and words <= w]
        if len(cands) == 1:
            out[fid] = cands[0]
            taken.add(cands[0])
    return out


def row_values(row: dict, colmap: dict, skip_field: Optional[str] = None) -> dict:
    """{id de campo: valor} de una fila del archivo (texto limpio, vacíos fuera). `skip_field` = el campo de la cédula, que ya se guarda aparte."""
    out = {}
    for fid, col in colmap.items():
        if fid == skip_field:
            continue
        v = " ".join(str(row.get(col) or "").split())[:MAX_VALUE]
        if v:
            out[fid] = v
    return out


def template_columns(design: dict, identifier_field: str) -> list:
    """Títulos de la plantilla que se descarga: primero el identificador (la cédula) y luego, en el orden del formulario, cada campo cuyo valor se puede traer."""
    order = []
    for row in design.get("rows", []):
        for it in row.get("items", []):
            fid = it if isinstance(it, str) else (it or {}).get("id")
            if fid and fid not in order:
                order.append(fid)
    order += [fid for fid in design["fields"] if fid not in order]
    fields = design["fields"]
    cols = [fields[identifier_field].get("label") or "Cédula"] if identifier_field in fields else []
    for fid in order:
        f = fields.get(fid)
        if f and fid != identifier_field and f.get("type") in STORE_TYPES and f.get("label"):
            cols.append(f["label"])
    return cols


def impact(rules: list, rows_values: list, used: dict) -> list:
    """Por cada cupo que alguna fila alimenta: cuántas personas del archivo entran en él y cuántos lugares quedarían. `rows_values` = [{id de campo: valor}] de las filas NUEVAS."""
    from app import formsvc
    out = []
    for r in rules:
        n = sum(1 for v in rows_values if formsvc.quota_match(r, v))
        if n:
            u = used.get(r["id"], 0)
            out.append({"id": r["id"], "label": r["label"], "limit": r["limit"], "used": u, "adding": n, "left_after": r["limit"] - u - n})
    return out
