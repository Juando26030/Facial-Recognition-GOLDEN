"""Inventario por cantidad con catálogo (Fase 5, rama f5/d-inventario): validación, resumen y REGLA DE CUADRE. Módulo puro (sin base de datos ni FastAPI): lo usan
app/routers/inventory.py y las pruebas. Lanza InventoryError con mensajes en español.

Catálogo (lo define el Super Admin en Configuración): categorías y productos (nombre, unidad, SKU opcional, campos propios).
Por evento: una línea por producto con `assigned` (lo que pide el evento) y lo que mueve el almacén: `out` (salió), `returned` (volvió) y `consumed` (se consumió).

Regla de cuadre (docs/29, Fase 5: «suma exacta; sin categorizar en creado; todo categorizado para pasar a en proceso»). `check_balance(rows, stage)`:
  siempre (error)  · ningún número negativo ni pasa de MAX_QTY
                   · devuelto + consumido NO puede superar lo que salió
                   · lo que salió NO puede superar lo asignado
  stage 'creado'      · un producto sin categoría es solo AVISO (se puede preparar sin categorizar)
  stage 'en_proceso'  · TODO producto con línea debe tener categoría (error)
                      · SUMA EXACTA: lo que salió debe ser igual a lo asignado en cada línea (error si falta o sobra)
  stage 'cierre'      · salió = devuelto + consumido (lo que falta por justificar es AVISO, no bloquea: el cierre se hace con calma)
`BalanceReport.ok` es True si no hay errores; los avisos no bloquean. `can_enter_in_progress(rows)` es la puerta para pasar el evento a «en proceso».
"""
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

MAX_QTY = 1_000_000
MAX_NAME = 80
MAX_UNIT = 20
MAX_SKU = 40
MAX_NOTES = 200
MAX_PRODUCT_FIELDS = 6
MAX_FIELD_LABEL = 40
MAX_FIELD_VALUE = 80
FIELD_KINDS = ("text", "number")
DEFAULT_UNIT = "unidad"
STAGES = ("creado", "en_proceso", "cierre")
_BAD = re.compile(r"[<>\x00-\x1f\x7f]")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


class InventoryError(ValueError):
    pass


# ---------------------------------------------------------------- limpieza de datos del catálogo

def clean_text(value, what: str, max_len: int, required: bool = True) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise InventoryError(f"{what}: escríbelo")
        return None
    if not isinstance(value, str):
        raise InventoryError(f"{what} debe ser texto")
    v = " ".join(value.split())
    if _BAD.search(v):
        raise InventoryError(f"{what} no puede incluir «<», «>» ni caracteres de control")
    if len(v) > max_len:
        raise InventoryError(f"{what} admite hasta {max_len} caracteres")
    return v


def clean_name(value, what: str = "El nombre") -> str:
    return clean_text(value, what, MAX_NAME)


def clean_unit(value) -> str:
    return clean_text(value, "La unidad de medida", MAX_UNIT, required=False) or DEFAULT_UNIT


def clean_sku(value) -> Optional[str]:
    return clean_text(value, "El SKU", MAX_SKU, required=False)


def same_name(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def clean_product_fields(raw) -> List[dict]:
    """Campos propios de un producto: [{key, label, kind:'text'|'number'}]. La clave se deduce del nombre si no viene."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InventoryError("Los campos del producto deben ser una lista")
    if len(raw) > MAX_PRODUCT_FIELDS:
        raise InventoryError(f"Un producto admite hasta {MAX_PRODUCT_FIELDS} campos propios")
    out, keys, labels = [], set(), set()
    for f in raw:
        if not isinstance(f, dict):
            raise InventoryError("Campo del producto inválido")
        label = clean_text(f.get("label"), "El nombre del campo", MAX_FIELD_LABEL)
        kind = f.get("kind", "text")
        if kind not in FIELD_KINDS:
            raise InventoryError("El tipo del campo debe ser texto o número")
        key = f.get("key") if isinstance(f.get("key"), str) and _KEY_RE.match(f.get("key")) else _slug(label, keys)
        if key in keys:
            raise InventoryError("Hay dos campos con la misma clave")
        if label.lower() in labels:
            raise InventoryError(f"Hay dos campos llamados «{label}»")
        keys.add(key)
        labels.add(label.lower())
        out.append({"key": key, "label": label, "kind": kind})
    return out


def _slug(label: str, taken: set) -> str:
    import unicodedata
    base = "".join(c for c in unicodedata.normalize("NFD", label.lower()) if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "campo"
    if not base[0].isalpha():
        base = "c_" + base
    base = base[:20]
    key, n = base, 2
    while key in taken:
        key = f"{base}_{n}"
        n += 1
    return key


def dump_fields(fields: List[dict]) -> Optional[str]:
    return json.dumps(fields, ensure_ascii=False) if fields else None


def load_fields(raw: Optional[str]) -> List[dict]:
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [f for f in data if isinstance(f, dict) and f.get("key") and f.get("label")] if isinstance(data, list) else []


def clean_attrs(raw, fields: List[dict]) -> dict:
    """Valores de los campos propios de un producto en un evento: solo claves definidas; número válido para los numéricos; vacío = sin valor."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InventoryError("Los datos del producto deben ser un objeto")
    by_key = {f["key"]: f for f in fields}
    out = {}
    for k, v in raw.items():
        f = by_key.get(k)
        if f is None:
            raise InventoryError("Hay un campo que el producto no tiene")
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if f.get("kind") == "number":
            try:
                n = float(str(v).replace(",", ".").strip())
            except ValueError:
                raise InventoryError(f"«{f['label']}» debe ser un número")
            if n != n or abs(n) > 1e12:
                raise InventoryError(f"«{f['label']}» debe ser un número válido")
            out[k] = int(n) if n == int(n) else round(n, 4)
        else:
            out[k] = clean_text(v if isinstance(v, str) else str(v), f"«{f['label']}»", MAX_FIELD_VALUE)
    return out


# ---------------------------------------------------------------- cantidades

def clean_qty(value, what: str) -> int:
    """Entero 0..MAX_QTY (None o vacío = 0)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if isinstance(value, bool):
        raise InventoryError(f"{what}: debe ser un número entero")
    try:
        if isinstance(value, float):
            if value != int(value):
                raise ValueError
            n = int(value)
        else:
            n = int(str(value).strip())
    except (TypeError, ValueError):
        raise InventoryError(f"{what}: debe ser un número entero")
    if n < 0 or n > MAX_QTY:
        raise InventoryError(f"{what}: debe estar entre 0 y {MAX_QTY}")
    return n


def clean_notes(value) -> Optional[str]:
    return clean_text(value, "La nota", MAX_NOTES, required=False)


# ---------------------------------------------------------------- regla de cuadre

@dataclass
class Row:
    """Una línea para el cuadre. `name` solo sirve para los mensajes."""
    name: str
    assigned: int = 0
    out: int = 0
    returned: int = 0
    consumed: int = 0
    category_id: Optional[int] = None
    product_id: Optional[int] = None


@dataclass
class Issue:
    level: str            # 'error' | 'warn'
    code: str
    product: str
    message: str
    product_id: Optional[int] = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "product": self.product, "message": self.message, "product_id": self.product_id}


@dataclass
class BalanceReport:
    stage: str
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def balanced(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict:
        return {"stage": self.stage, "ok": self.ok, "balanced": self.balanced, "errors": [i.as_dict() for i in self.errors], "warnings": [i.as_dict() for i in self.warnings]}


def as_row(obj) -> Row:
    if isinstance(obj, Row):
        return obj
    if isinstance(obj, dict):
        return Row(name=str(obj.get("name") or "Producto"), assigned=int(obj.get("assigned") or 0), out=int(obj.get("out") or 0), returned=int(obj.get("returned") or 0),
                   consumed=int(obj.get("consumed") or 0), category_id=obj.get("category_id"), product_id=obj.get("product_id"))
    raise InventoryError("Línea de inventario inválida")


def check_balance(rows: Iterable, stage: str = "creado") -> BalanceReport:
    """Regla de cuadre (ver el docstring del módulo). `rows`: Row o dicts {name, assigned, out, returned, consumed, category_id}. Devuelve un BalanceReport; nunca lanza por datos de línea."""
    if stage not in STAGES:
        raise InventoryError(f"Etapa de cuadre desconocida: {stage}")
    rep = BalanceReport(stage=stage)

    def add(level, code, r, msg):
        rep.issues.append(Issue(level, code, r.name, msg, r.product_id))

    for r in (as_row(x) for x in rows):
        if min(r.assigned, r.out, r.returned, r.consumed) < 0 or max(r.assigned, r.out, r.returned, r.consumed) > MAX_QTY:
            add("error", "invalid_qty", r, f"«{r.name}»: las cantidades deben estar entre 0 y {MAX_QTY}.")
            continue
        if r.returned + r.consumed > r.out:
            add("error", "over_returned", r, f"«{r.name}»: devuelto ({r.returned}) + consumido ({r.consumed}) supera lo que salió ({r.out}).")
        if r.out > r.assigned:
            add("error", "over_assigned", r, f"«{r.name}»: salieron {r.out} y el evento tiene asignados {r.assigned}.")
        if r.category_id is None:
            if stage == "en_proceso":
                add("error", "uncategorized", r, f"«{r.name}» no tiene categoría: categorízalo para pasar el evento a «En proceso».")
            elif stage == "creado":
                add("warn", "uncategorized", r, f"«{r.name}» no tiene categoría (se puede mientras el evento está en «Creado»).")
        if stage == "en_proceso" and r.out < r.assigned:
            add("error", "short_out", r, f"«{r.name}»: faltan {r.assigned - r.out} por sacar del almacén (asignados {r.assigned}, salieron {r.out}).")
        if stage == "cierre" and r.out > r.returned + r.consumed:
            add("warn", "unaccounted", r, f"«{r.name}»: faltan {r.out - r.returned - r.consumed} por devolver o justificar como consumidos.")
    return rep


def can_enter_in_progress(rows: Iterable) -> BalanceReport:
    """Puerta para pasar un evento a «En proceso»: el reporte de la etapa 'en_proceso' (ok = se puede). Un evento sin líneas de inventario pasa."""
    return check_balance(rows, "en_proceso")


def stage_for_status(status: str) -> str:
    """Estado base del evento -> etapa de cuadre que se muestra: creado -> 'creado', en_proceso -> 'en_proceso', finalizado -> 'cierre'."""
    return {"creado": "creado", "en_proceso": "en_proceso", "finalizado": "cierre"}.get(status, "creado")


def blocking_message(rep: BalanceReport, limit: int = 4) -> str:
    """Texto para el usuario cuando el cuadre impide pasar a «En proceso»."""
    msgs = [i.message for i in rep.errors[:limit]]
    extra = len(rep.errors) - len(msgs)
    return "El inventario no cuadra para pasar a «En proceso»: " + " ".join(msgs) + (f" (y {extra} más)" if extra > 0 else "")


def summary(rows: Iterable) -> dict:
    """Totales para mostrar: asignado, salió, devuelto, consumido y pendiente de regresar (salió - devuelto - consumido, nunca negativo)."""
    t = {"assigned": 0, "out": 0, "returned": 0, "consumed": 0}
    for r in (as_row(x) for x in rows):
        t["assigned"] += r.assigned
        t["out"] += r.out
        t["returned"] += r.returned
        t["consumed"] += r.consumed
    t["pending"] = max(t["out"] - t["returned"] - t["consumed"], 0)
    return t
