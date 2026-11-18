"""Preimpresiones (18-nov-2026, pedido de Juan David): imprimir las escarapelas de un grupo de personas (VIPs, expositores…) ANTES de que lleguen, para no imprimirlas en la puerta.

Módulo puro (sin base de datos ni FastAPI): se prueba sin servidor. Aquí viven:
  · las reglas (en qué estados del evento se puede preimprimir, cuántas escarapelas por ventana de impresión);
  · el filtro por condiciones, que es el MISMO de la ruleta (`roulette._match`) más un campo propio, «¿ya está preimpresa?»;
  · la búsqueda de texto de la selección a mano.
La impresión en sí NO se reimplementa: se usa la ventana de siempre (`templates/badge_print.html`, parámetros inamovibles de docs/IMPRESION_PARAMETROS_INAMOVIBLES.md)."""
import unicodedata
from typing import Callable, Iterable, List, Optional

KIND_PRE = "pre"                 # PrintLog.kind de una escarapela preimpresa (la normal es 'normal')
KIND_NORMAL = "normal"
MAX_BATCH = 300                 # escarapelas en UNA sola ventana/ejecución de impresión (varias páginas, como «Imprimir pendientes»); la dirección lleva los ids
MAX_PEOPLE = 2000                # tope de personas que devuelve la lista (igual que la ruleta)
PREPRINT_STATUSES = ("creado", "en_proceso")          # «finalizado» no: ya no hay a quién entregarle la escarapela
PREPRINTED_FIELD = "preprinted"          # campo de filtro propio del módulo: 'si' = ya tiene escarapela preimpresa, 'no' = aún no


def can_preprint(status: Optional[str]) -> bool:
    """¿Se puede preimprimir con el evento en este estado? Antes de empezar («creado») y durante («en proceso»); no al finalizar."""
    return status in PREPRINT_STATUSES


def norm(text) -> str:
    """Minúsculas y sin tildes: para buscar «jose» y encontrar «José»."""
    s = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def clean_ids(ids: Iterable, limit: int = MAX_PEOPLE) -> List[str]:
    """Quita vacíos y repetidos conservando el orden (la selección a mano puede repetir un clic)."""
    out, seen = [], set()
    for raw in ids or []:
        v = str(raw or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
        if len(out) >= limit:
            break
    return out


def chunk(ids: List[str], size: int = MAX_BATCH) -> List[List[str]]:
    """Parte una lista en tandas de a lo sumo `size` (la pantalla NO lo usa: imprime todo en una sola ejecución; queda por si se necesita)."""
    size = max(1, int(size))
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def matches_text(person: dict, query: Optional[str]) -> bool:
    """Búsqueda de la selección a mano: cada palabra escrita debe aparecer en el nombre, la cédula, la entidad o el cargo."""
    words = [w for w in norm(query).split() if w]
    if not words:
        return True
    hay = " ".join(norm(person.get(k)) for k in ("name", "id", "entity", "role", "opt_1"))
    return all(w in hay for w in words)


def condition_met(person: dict, cond: dict, base_match: Callable[[dict, dict], bool]) -> bool:
    """Una condición del filtro. `preprinted` se resuelve aquí; todo lo demás (estado, categoría, entidad, cargo, campos opcionales, horas) lo decide el filtro de la ruleta (`base_match`)."""
    if cond.get("field") == PREPRINTED_FIELD:
        return bool(person.get("preprinted_at")) == (cond.get("value") == "si")
    return base_match(person, cond)


def apply_filter(people: List[dict], filt: Optional[dict], base_match: Callable[[dict, dict], bool]) -> List[dict]:
    """Todas las condiciones deben cumplirse (igual que la ruleta). Sin condiciones devuelve a todos."""
    conds = (filt or {}).get("conditions") or []
    return [p for p in people if all(condition_met(p, c, base_match) for c in conds)]


def summarize(people: List[dict]) -> dict:
    """Totales para mostrar arriba de la lista."""
    done = sum(1 for p in people if p.get("preprinted_at"))
    return {"total": len(people), "preprinted": done, "pending": len(people) - done}
