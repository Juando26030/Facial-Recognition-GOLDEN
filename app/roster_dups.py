"""«No eliminar repetidos» (Plan 5, paso 3): qué hacer con una cédula que aparece en varias filas de la base que se carga.

Apagado (lo de siempre): la última fila gana, con una advertencia. Encendido: la PRIMERA aparición conserva su cédula; las siguientes reciben un serial `CED-2`, `CED-3`… (guion + número de aparición), así
cada fila es una persona distinta. La cédula original queda en un campo opcional automático «Cédula original» (ya no depende de ningún cupo: el tope de 30 campos opcionales se eliminó; solo hay un techo técnico de 500).

La numeración se decide UNA vez, por el orden del archivo, ANTES de partirlo en pasos (la carga por pasos guarda las filas ya con su serial) o en lotes del navegador (el navegador manda cuántas veces
ya vio cada cédula en los lotes anteriores: `offsets`), de modo que la misma cédula en lotes distintos recibe seriales consecutivos y sin choques.

Recargar el MISMO archivo es idempotente solo si el orden de las filas no cambió (el serial depende del orden); con otro orden, `CED-2` podría quedar en otra persona.
No toca la purga ni la supresión: suprimir la cédula 123456 NO borra a 123456-2 (decisión del dueño). La escarapela y el QR usan el id CON serial (123456-2); la «Cédula original» queda solo como campo opcional (directorio y variables opcionales), no reemplaza al id."""
import json
import re
from typing import Optional

SERIAL_RE = re.compile(r"^(.+)-(\d{1,3})$")
_FLOAT_LOOKING = re.compile(r"^(\d+)\.0+$")
NOTE_RELOAD = "ℹ️ «No eliminar repetidos»: el serial de cada repetida depende del orden de las filas. Volver a cargar este mismo archivo es seguro solo si el orden de las filas no cambió."


def clean_id(raw) -> str:
    """Misma limpieza de la cédula que `_extract_identificador` (Excel la vuelve '123.0')."""
    val = str(raw or "").strip()
    m = _FLOAT_LOOKING.match(val)
    return m.group(1) if m else val


def serial_for(base: str, occurrence: int) -> str:
    """`occurrence` = 0 para la primera aparición (queda igual), 1 para la segunda (`CED-2`), 2 para la tercera (`CED-3`)…"""
    return base if occurrence == 0 else f"{base}-{occurrence + 1}"


MAX_OFFSET_KEYS = 5000          # tope de cédulas distintas que el navegador puede mandar en `offsets`
MAX_OFFSET_KEY_LEN = 64
MAX_OFFSET_VALUE = 100000
OFFSETS_IGNORED_NOTE = "⚠️ «No eliminar repetidos»: se ignoraron datos de conteo inválidos o excesivos que mandó el navegador."


def parse_offsets(raw) -> dict:
    """JSON {cédula: veces que ya apareció en lotes anteriores} que manda el navegador; lo inválido se ignora (a lo sumo 5000 claves de máx. 64 caracteres, valores enteros 0..100000)."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError, RecursionError):
            return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for i, (k, v) in enumerate(data.items()):
        if i >= MAX_OFFSET_KEYS:
            break
        if isinstance(v, bool) or not isinstance(k, str) or len(k) > MAX_OFFSET_KEY_LEN:
            continue
        try:
            n = int(v)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 < n <= MAX_OFFSET_VALUE:
            out[clean_id(k)] = n
    return out


def assign(rows: list, offsets: Optional[dict] = None, original_key: Optional[str] = None) -> dict:
    """Pone el serial en la celda `id` de cada fila repetida (en el lugar). Si `original_key` (p. ej. «opcional_3»), guarda ahí la cédula original de las filas que recibieron serial.
    Devuelve {"serials": cuántas filas recibieron serial, "ids": cuántas cédulas distintas se repetían, "collisions": [serial que ya era una cédula del archivo]}."""
    seen = dict(offsets or {})
    file_ids = {clean_id(r.get("id")) for r in rows if clean_id(r.get("id"))}
    serials, repeated, collisions = 0, set(), []
    for row in rows:
        base = clean_id(row.get("id"))
        if not base:
            continue
        n = seen.get(base, 0)
        seen[base] = n + 1
        if n == 0:
            continue
        final = serial_for(base, n)
        row["id"] = final
        if original_key:
            row[original_key] = base
        serials += 1
        repeated.add(base)
        if final in file_ids:
            collisions.append(final)
    return {"serials": serials, "ids": len(repeated), "collisions": collisions}


def has_repeats(rows: list, offsets: Optional[dict] = None) -> bool:
    seen = dict(offsets or {})
    for row in rows:
        base = clean_id(row.get("id"))
        if not base:
            continue
        if seen.get(base, 0) > 0:
            return True
        seen[base] = 1
    return False
