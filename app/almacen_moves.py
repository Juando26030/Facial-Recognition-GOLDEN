"""Almacén — Pieza 2: salidas y entradas por lectura de QR, alistado por fila del checklist y tablero del evento (rama almacen/p2-movimientos, plan: claude/60).

Módulo PURO (sin base de datos ni FastAPI): decide si un movimiento es válido y cuánto cambia cada contador. Lo usa app/routers/almacen.py y lo prueban tests/test_almacen_moves.py.

Cómo encaja con lo que ya existía (app/inventory.py, tabla `event_inventory_items`):
  · NECESARIO  = `qty_assigned` menos lo que se agregó «de emergencia» (extra); CANTIDAD = `qty_out`; Volvió = `qty_returned`.
  · Cada movimiento actualiza esos contadores en la misma transacción, así la regla de cuadre (salió ≤ asignado; devuelto + consumido ≤ salió) sigue valiendo igual.
  · Un consumible que sale se cuenta como consumido en el acto (no vuelve; almacén lo repone y lo cuenta a mano).
  · Salir MÁS de lo que pide el evento: primero se ajusta lo asignado; si no se puede, se pide la RAZÓN en texto o se marca «Plan B» (decisión de Juan David, 17-nov-2026).
    Ese sobrante sube `qty_assigned` para que el cuadre no se rompa, pero queda guardado como `extra` del movimiento y no cuenta como NECESARIO.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from app.almacen import CHECKLIST_ROWS, AlmacenError, inventory_row_keys
from app.inventory import MAX_QTY

EXIT_STATUSES = ("creado", "en_proceso")                      # eventos a los que se puede sacar material
ENTRY_STATUSES = ("creado", "en_proceso", "finalizado")      # eventos de los que se puede devolver material
MODES = ("salida", "entrada")
MAX_REASON = 300
MAX_NOTE = 300


class MoveError(AlmacenError):
    """Movimiento no válido. `needs_reason` = se puede completar escribiendo una razón o marcando Plan B; `extra` = cuánto sobra sobre lo asignado."""

    def __init__(self, message: str, needs_reason: bool = False, extra: int = 0):
        super().__init__(message)
        self.needs_reason = needs_reason
        self.extra = extra


@dataclass
class ExitPlan:
    out_add: int
    consumed_add: int
    extra: int
    reason: Optional[str]
    plan_b: bool


def clean_mode(value) -> str:
    v = str(value or "").strip().lower()
    if v not in MODES:
        raise MoveError("Elige si es una salida o una entrada.")
    return v


def clean_move_qty(value, default: int = 1) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise MoveError("La cantidad debe ser un número entero.")
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise MoveError("La cantidad debe ser un número entero.")
    if n < 1 or n > MAX_QTY:
        raise MoveError(f"La cantidad debe estar entre 1 y {MAX_QTY}.")
    return n


def clean_text(value, maximum: int, what: str) -> Optional[str]:
    if value is None:
        return None
    v = " ".join(str(value).split())
    if not v:
        return None
    if len(v) > maximum:
        raise MoveError(f"{what} no puede pasar de {maximum} caracteres.")
    if any(ord(ch) < 32 or ch in "<>" for ch in v):
        raise MoveError(f"{what} trae caracteres no permitidos.")
    return v


def check_event(status: str, archived: bool, mode: str) -> None:
    """Solo con el evento abierto: la salida con «creado»/«en proceso»; la entrada también con «finalizado»."""
    if archived:
        raise MoveError("El evento está archivado: restáuralo para mover material.")
    allowed = EXIT_STATUSES if mode == "salida" else ENTRY_STATUSES
    if status not in allowed:
        raise MoveError("Las salidas se hacen con el evento en «Creado» o «En proceso»." if mode == "salida" else "Las entradas no se registran con este estado del evento.")


def plan_exit(*, tracking: str, consumable: bool, assigned: int, out: int, qty: int, unit_status: Optional[str] = None, unit_event_name: Optional[str] = None,
              reason=None, plan_b: bool = False, product_name: str = "") -> ExitPlan:
    """Salida de `qty` hacia el evento. Lanza MoveError si no procede; con `needs_reason` cuando solo falta justificar lo que excede lo asignado."""
    if tracking == "serial":
        if qty != 1:
            raise MoveError("Un equipo con serial sale de a uno.")
        if unit_status == "en_evento":
            raise MoveError("Ese equipo ya está en el evento " + (f"«{unit_event_name}»" if unit_event_name else "de otra salida") + ": primero registra su entrada.")
        if unit_status == "novedad":
            raise MoveError("Ese equipo está en novedad: no se puede asignar a un evento hasta que Almacén lo deje disponible.")
        if unit_status not in (None, "disponible"):
            raise MoveError("Ese equipo no está disponible.")
    free = max(assigned - out, 0)
    extra = max(qty - free, 0)
    why = clean_text(reason, MAX_REASON, "La razón")
    if extra and not (why or plan_b):
        name = f"«{product_name}»" if product_name else "Este producto"
        if assigned <= 0:
            msg = f"El evento no pidió {name}. Ajusta primero lo asignado del evento; si no es posible, escribe la razón de incluirlo o márcalo como Plan B."
        else:
            msg = f"El evento tiene asignados {assigned} de {name} y ya salieron {out}: salir {qty} más lo excede. Ajusta primero lo asignado; si no es posible, escribe la razón o márcalo como Plan B."
        raise MoveError(msg, needs_reason=True, extra=extra)
    if out + qty > MAX_QTY:
        raise MoveError(f"Las cantidades no pueden pasar de {MAX_QTY}.")
    return ExitPlan(out_add=qty, consumed_add=qty if consumable else 0, extra=extra, reason=why if extra else None, plan_b=bool(plan_b) if extra else False)


def plan_entry(*, tracking: str, consumable: bool, out: int, returned: int, consumed: int, qty: int, unit_status: Optional[str] = None, product_name: str = "") -> int:
    """Devuelve cuánto suma a `qty_returned`. Un consumible no se devuelve; un equipo con serial solo entra si está afuera."""
    name = f"«{product_name}»" if product_name else "Este producto"
    if consumable:
        raise MoveError(f"{name} es un consumible: no se devuelve (Almacén lo repone y lo cuenta a mano).")
    if tracking == "serial":
        if qty != 1:
            raise MoveError("Un equipo con serial entra de a uno.")
        if unit_status != "en_evento":
            raise MoveError("Ese equipo ya está en bodega: no tiene una salida pendiente.")
    pending = max(out - returned - consumed, 0)
    if pending <= 0:
        raise MoveError(f"No hay nada pendiente por devolver de {name} en este evento.")
    if qty > pending:
        raise MoveError(f"Solo faltan {pending} por devolver de {name} en este evento (intentas devolver {qty}).")
    return qty


@dataclass
class UndoPlan:
    out_sub: int
    consumed_sub: int
    returned_sub: int
    assigned_sub: int


def plan_undo(*, kind: str, qty: int, extra: int, consumable: bool, voided: bool, has_later: bool) -> UndoPlan:
    """Anular un movimiento: deshace sus contadores. No se puede si ya está anulado o si hay un movimiento posterior de lo mismo (se anula primero ese)."""
    if voided:
        raise MoveError("Ese movimiento ya estaba anulado.")
    if has_later:
        raise MoveError("Hay un movimiento posterior de este mismo equipo o producto en el evento: anula primero ese.")
    if kind == "salida":
        return UndoPlan(out_sub=qty, consumed_sub=qty if consumable else 0, returned_sub=0, assigned_sub=extra)
    if kind == "entrada":
        return UndoPlan(out_sub=0, consumed_sub=0, returned_sub=qty, assigned_sub=0)
    raise MoveError("Tipo de movimiento desconocido.")


# ---------------------------------------------------------------- alistado por fila del checklist
_ROW_KEYS = {r["key"] for r in CHECKLIST_ROWS}


def clean_row_key(value) -> str:
    v = str(value or "").strip()
    if v not in _ROW_KEYS:
        raise MoveError("Esa fila del checklist no existe.")
    return v


def clean_check_update(data: dict) -> Dict[str, object]:
    """Cambios de una fila: `done` (casilla OK S/N) y/o `notes` (observación). Solo lo que llegue."""
    out: Dict[str, object] = {}
    if "done" in data:
        v = data.get("done")
        if not isinstance(v, bool):
            raise MoveError("«Alistado» debe ser sí o no.")
        out["done"] = v
    if "notes" in data:
        out["notes"] = clean_text(data.get("notes"), MAX_NOTE, "La observación")
    if not out:
        raise MoveError("No hay nada que guardar en esa fila.")
    return out


# ---------------------------------------------------------------- tablero del evento (una fila por fila del checklist GEYL)
def build_board(lines: Iterable[dict], checks: Dict[str, dict]) -> List[dict]:
    """`lines`: una por producto del evento {row_key, assigned, out, returned, consumed, extra, plan_b}. `checks`: {row_key: {done, notes}}.
    Devuelve las 43 filas del formato en su orden: NECESARIO (lo que pide el evento, sin los extras), CANTIDAD (lo despachado), Volvió, Falta por volver, Alistado y Observaciones."""
    acc: Dict[str, dict] = {k: {"needed": 0, "out": 0, "returned": 0, "consumed": 0, "extra": 0, "plan_b": False} for k in inventory_row_keys()}
    for ln in lines:
        k = ln.get("row_key")
        if k not in acc:
            continue
        a = acc[k]
        a["needed"] += max(int(ln.get("assigned") or 0) - int(ln.get("extra") or 0), 0)
        a["out"] += int(ln.get("out") or 0)
        a["returned"] += int(ln.get("returned") or 0)
        a["consumed"] += int(ln.get("consumed") or 0)
        a["extra"] += int(ln.get("extra") or 0)
        a["plan_b"] = a["plan_b"] or bool(ln.get("plan_b"))
    board = []
    for r in CHECKLIST_ROWS:
        chk = checks.get(r["key"]) or {}
        row = {"key": r["key"], "label": r["label"], "section": r["section"], "section_label": r["section_label"], "kind": r["kind"],
               "done": bool(chk.get("done")), "notes": chk.get("notes") or ""}
        if r["kind"] == "inv":
            a = acc[r["key"]]
            row.update({"needed": a["needed"], "out": a["out"], "returned": a["returned"], "consumed": a["consumed"],
                        "pending": max(a["out"] - a["returned"] - a["consumed"], 0), "extra": a["extra"], "plan_b": a["plan_b"]})
        else:
            row.update({"needed": None, "out": None, "returned": None, "consumed": None, "pending": None, "extra": 0, "plan_b": False})
        board.append(row)
    return board


def board_summary(board: Iterable[dict]) -> dict:
    rows = [r for r in board]
    inv = [r for r in rows if r["kind"] == "inv"]
    return {"rows": len(rows), "done": sum(1 for r in rows if r["done"]), "pending_return": sum(r["pending"] or 0 for r in inv),
            "extras": sum(r["extra"] or 0 for r in inv), "needed_rows": sum(1 for r in inv if r["needed"]), "out_rows": sum(1 for r in inv if r["out"])}
