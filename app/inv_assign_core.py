"""Reglas PURAS (sin base de datos ni FastAPI) del inventario «lo define la base» y de la base de dependientes (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md).

Lo que vive aquí se prueba sin servidor: normalizar el valor de un producto, reconocer las columnas del archivo de dependientes, decidir quién es cada dependiente,
leer cantidades, elegir las filas de muestra de la vista previa y armar lo que le toca a una persona. app/dependents.py y app/inv_assign.py ponen la base de datos alrededor."""
import re
import unicodedata

MODE_CHOOSE = "choose"
MODE_ASSIGNED = "assigned"
MODES = (MODE_CHOOSE, MODE_ASSIGNED)
ASSIGN_KEYS = ("holder_product", "holder_qty", "dep_product", "dep_qty")
HOLDER_KEY = "h"                 # la asignación del titular (su propio producto en la base de registro)
DEP_PREFIX = "d"                 # la de una fila de dependiente: 'd<uid de event_dependents>' (el uid no cambia al copiar el evento a otro servidor)
MAX_QTY = 1000
SAMPLE_SIZE = 10

# Columnas conocidas del archivo de dependientes (títulos normalizados con norm()). Cualquier otra columna se guarda tal cual como dato del dependiente.
HOLDER_COLS = ("cedula titular", "cedula del titular", "cc titular", "id titular", "documento titular", "documento del titular", "titular", "cedula", "cc", "id", "documento")
NAME_COLS = ("nombre dependiente", "nombre del dependiente", "nombre de dependiente", "dependiente", "nombre hijo", "nombre del hijo", "hijo", "nombre acompanante", "acompanante")
# «nombre» a secas NO es el nombre del dependiente: en las bases reales suele ser el del titular (se guarda como dato y la vista previa lo muestra).
DOC_COLS = ("cedula dependiente", "cedula del dependiente", "documento dependiente", "documento del dependiente", "cc dependiente", "id dependiente", "documento hijo", "documento del hijo",
            "tarjeta de identidad", "ti")
_FLOAT_LOOKING = re.compile(r"^(\d+)\.0+$")


def norm(value) -> str:
    """Clave para comparar textos: minúsculas, sin tildes, signos como espacio y espacios colapsados. «Astronauta  Proyector» = «astronauta proyector»."""
    text = unicodedata.normalize("NFD", str(value or "").strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def clean_id(raw) -> str:
    """La misma limpieza de cédula que la carga de personas (Excel vuelve '123' en '123.0')."""
    val = str(raw or "").strip()
    m = _FLOAT_LOOKING.match(val)
    return m.group(1) if m else val


def parse_qty(raw):
    """Cantidad de una celda: entero de 0 a MAX_QTY. Vacío -> None (se usa la regla «una fila = una unidad»). Texto que no es número -> False (se avisa)."""
    text = str(raw if raw is not None else "").strip().replace(",", ".")
    if not text:
        return None
    try:
        num = float(text)
    except ValueError:
        return False
    if num < 0 or num != int(num) or num > MAX_QTY:
        return False
    return int(num)


def clean_assign_config(raw) -> dict:
    """{holder_product, holder_qty, dep_product, dep_qty} con texto o None; ignora lo demás."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in ASSIGN_KEYS:
        v = raw.get(k)
        v = str(v).strip()[:120] if v not in (None, "") else None
        out[k] = v
    return out


def _find(columns: dict, options) -> str:
    """Primera columna del archivo (título normalizado -> título real) que coincide con alguna de las opciones, en el orden de las opciones."""
    for opt in options:
        if opt in columns:
            return columns[opt]
    return ""


def detect_columns(titles) -> dict:
    """Qué columna del archivo es la cédula del titular, el nombre y el documento del dependiente. `titles`: los títulos tal como vienen."""
    by_norm = {}
    for t in titles:
        n = norm(t)
        if n and n not in by_norm:
            by_norm[n] = t
    holder = _find(by_norm, HOLDER_COLS)
    rest = {k: v for k, v in by_norm.items() if v != holder}
    doc = _find(rest, DOC_COLS)
    rest = {k: v for k, v in rest.items() if v != doc}
    name = _find(rest, NAME_COLS)
    return {"holder": holder, "name": name, "doc": doc}


def person_key(name: str, doc: str, row_num: int) -> str:
    """Quién es el dependiente dentro de su titular: por su documento; si no, por su nombre; si no trae ninguno, cada fila es un dependiente distinto."""
    if clean_id(doc):
        return "doc:" + norm(clean_id(doc))
    if norm(name):
        return "name:" + norm(name)
    return f"row:{int(row_num)}"


def parse_dependent_rows(rows, columns: dict, start_row: int = 2) -> list:
    """Filas del archivo -> [{row_num, holder, name, doc, person_key, data}] (data = las demás columnas con valor). Las filas totalmente vacías se saltan."""
    out = []
    skip = {c for c in (columns.get("holder"), columns.get("name"), columns.get("doc")) if c}
    for i, row in enumerate(rows):
        row_num = start_row + i
        if not any(str(v or "").strip() for v in row.values()):
            continue
        holder = clean_id(row.get(columns.get("holder"), "")) if columns.get("holder") else ""
        name = str(row.get(columns.get("name"), "") or "").strip() if columns.get("name") else ""
        doc = clean_id(row.get(columns.get("doc"), "")) if columns.get("doc") else ""
        data = {k: str(v).strip() for k, v in row.items() if k not in skip and str(v or "").strip()}
        out.append({"row_num": row_num, "holder": holder, "name": name, "doc": doc, "person_key": person_key(name, doc, row_num), "data": data})
    return out


def sample_indices(n: int, k: int = SAMPLE_SIZE) -> list:
    """Índices repartidos de punta a punta del archivo (la primera fila, la última y las del medio), sin repetir: una muestra «graneada» y no solo las primeras filas."""
    if n <= 0:
        return []
    if n <= k:
        return list(range(n))
    step = (n - 1) / (k - 1)
    return sorted({round(i * step) for i in range(k)})


def dep_line_key(uid: str) -> str:
    return f"{DEP_PREFIX}{uid}"


def lines_for(holder_value, holder_qty_raw, deps: list, cfg: dict) -> list:
    """Lo que le toca a una persona en el modo «la base lo define», ANTES de mirar el inventario: [{key, who, product, product_key, qty, problem}].
    `holder_value` = el valor del campo de producto del titular (o None si no se usa); `deps` = [{uid, label, name, data}] de sus dependientes (filas del archivo).
    Sin columna de cantidad, una fila = 1 unidad; con columna y la celda vacía, también 1; una cantidad inválida o 0 queda con `problem` y qty 0."""
    cfg = clean_assign_config(cfg)
    out = []

    def qty_of(raw, use_col):
        if not use_col:
            return 1, ""
        q = parse_qty(raw)
        if q is None:
            return 1, ""
        if q is False:
            return 0, "la cantidad de la base no es un número válido"
        return q, ("la base dice 0 unidades" if q == 0 else "")

    if cfg["holder_product"] and str(holder_value or "").strip():
        q, problem = qty_of(holder_qty_raw, cfg["holder_qty"])
        out.append({"key": HOLDER_KEY, "who": "", "dependent": False, "product": str(holder_value).strip(), "product_key": norm(holder_value), "qty": q, "problem": problem})
    if cfg["dep_product"]:
        col = norm(cfg["dep_product"])
        qcol = norm(cfg["dep_qty"]) if cfg["dep_qty"] else ""
        for d in deps:
            data = {norm(k): v for k, v in (d.get("data") or {}).items()}
            value = str(data.get(col) or "").strip()
            if not value:
                continue
            q, problem = qty_of(data.get(qcol) if qcol else None, bool(qcol))
            out.append({"key": dep_line_key(d["uid"]), "who": d.get("label") or d.get("name") or "", "dependent": True, "product": value, "product_key": norm(value), "qty": q, "problem": problem})
    return out


def group_people(dep_rows: list) -> list:
    """Filas de dependientes de UN titular -> personas (mismo person_key = misma persona con varios productos), en orden de aparición, con su etiqueta «Dependiente N» si no traen nombre."""
    people, order = {}, []
    for r in dep_rows:
        k = r["person_key"]
        if k not in people:
            people[k] = {"person_key": k, "name": r.get("name") or "", "doc": r.get("doc") or "", "rows": []}
            order.append(k)
        people[k]["rows"].append(r)
    out = []
    for i, k in enumerate(order, start=1):
        p = people[k]
        p["seq"] = i
        p["label"] = p["name"] or f"Dependiente {i}"
        out.append(p)
    return out
