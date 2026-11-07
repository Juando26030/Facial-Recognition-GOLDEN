"""Campo «inventario» de la plantilla de evento (Fase 2, entrega 4): validación y resumen de las líneas que el cliente solicitó para un evento.

Formato guardado en `events.extra_json[<clave>]` (retrocompatible con la entrega 2):
    [{"type": "<clave del tipo>", "qty": <entero 1..MAX_QTY>, "ref": "<referencia>" | null}, ...]
Definición del campo (config.inventory_types): [{"key", "label", "refs": [..]}].
  * `refs` con opciones  -> la referencia es OBLIGATORIA y debe ser una de la lista.
  * `refs` vacía         -> la referencia es TEXTO LIBRE opcional (nombre del dispositivo o de la persona), hasta MAX_REF_LEN caracteres.
Pensado para el enlace futuro con el módulo operativo de Inventario (Fase 5, «inventario por cantidad con catálogo y regla de cuadre»): `type` es una
clave estable (el catálogo se enlaza por ella), `qty` es la cantidad solicitada y `ref` la referencia; NO se conecta con kiosk_inventario todavía.

Módulo puro (sin base de datos). Lanza InventoryError; app/event_template.py la convierte en TemplateError con el mismo mensaje.
"""
import re

MAX_LINES = 100
MAX_QTY = 100_000
MAX_REF_LEN = 80
_BAD = re.compile(r"[<>\x00-\x1f\x7f]")


class InventoryError(ValueError):
    pass


def _qty(value, w: str) -> int:
    if isinstance(value, bool) or value is None:
        raise InventoryError(f"{w}: la cantidad debe ser un número entero")
    if isinstance(value, float):
        if value != int(value):
            raise InventoryError(f"{w}: la cantidad debe ser un número entero")
        value = int(value)
    try:
        n = value if isinstance(value, int) else int(str(value).strip())
    except (TypeError, ValueError):
        raise InventoryError(f"{w}: la cantidad debe ser un número entero")
    if n < 1 or n > MAX_QTY:
        raise InventoryError(f"{w}: la cantidad debe estar entre 1 y {MAX_QTY}")
    return n


def _free_ref(value, w: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise InventoryError(f"{w}: la referencia debe ser texto")
    v = value.strip()
    if _BAD.search(v):
        raise InventoryError(f"{w}: la referencia no puede incluir «<», «>» ni caracteres de control")
    if len(v) > MAX_REF_LEN:
        raise InventoryError(f"{w}: la referencia admite hasta {MAX_REF_LEN} caracteres")
    return v or None


def clean_lines(raw, types: list, w: str):
    """Valida las líneas contra los tipos definidos en la plantilla. Devuelve la lista limpia o None si no hay líneas."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise InventoryError(f"{w} debe ser una lista de líneas")
    if len(raw) > MAX_LINES:
        raise InventoryError(f"{w} admite hasta {MAX_LINES} líneas")
    by_key = {t["key"]: t for t in (types or [])}
    out, seen = [], set()
    for line in raw:
        if not isinstance(line, dict) or not isinstance(line.get("type"), str) or line["type"] not in by_key:
            raise InventoryError(f"{w}: tipo de inventario desconocido")
        t = by_key[line["type"]]
        qty = _qty(line.get("qty"), f"{w} ({t['label']})")
        refs = t.get("refs") or []
        ref = line.get("ref")
        if refs:
            if ref not in refs:
                raise InventoryError(f"{w}: elige la referencia de «{t['label']}» de la lista")
        else:
            ref = _free_ref(ref, f"{w} ({t['label']})")
        sig = (line["type"], (ref or "").lower())
        if sig in seen:
            raise InventoryError(f"{w}: «{t['label']}»{' — ' + ref if ref else ''} está repetido; suma las cantidades en una sola línea")
        seen.add(sig)
        out.append({"type": line["type"], "qty": qty, "ref": ref})
    return out or None


def summary(lines, types: list) -> str:
    """«Computadores ×2 — Dell; Impresoras ×3» (mismo texto que GWInventory.summary en el navegador)."""
    labels = {t["key"]: t["label"] for t in (types or [])}
    return "; ".join(f"{labels.get(l['type'], l['type'])} ×{l['qty']}" + (f" — {l['ref']}" if l.get("ref") else "") for l in (lines or []))
