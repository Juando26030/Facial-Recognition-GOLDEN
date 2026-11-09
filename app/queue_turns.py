"""Turnos y filas (Fase 8): lógica PURA, sin base de datos (se prueba sola).

Un evento con «Turnos y filas» reparte turnos con letra + número (A1, A2… B1…). Cada letra es una FILA. Orden de los turnos:
  arrival  por llegada: la persona escanea el QR del evento y toma su turno en ese momento (como una máquina de tickets)
  form     por orden de inscripción en el formulario
  alpha    alfabético (apellido, nombre)
  manual   el que venga en un Excel (cédula, orden, fila opcional)
Cada fila se llama por `rank` (menor primero); «saltar» y «volver a la fila» solo cambian el `rank`, el turno (A12) no cambia nunca.
"""
import re
import unicodedata
from typing import Iterable, Optional

MODES = ("arrival", "form", "alpha", "manual")
MODE_LABELS = {"arrival": "Por llegada (la persona toma su turno al escanear el QR)", "form": "Por orden de inscripción en el formulario",
               "alpha": "Alfabético (apellido y nombre)", "manual": "Manual (Excel con el orden)"}
MAX_LANES = 8
MAX_LANE_NAME = 40
DEFAULT_CONFIG = {"mode": "arrival", "lanes": [{"letter": "A", "name": ""}], "show_name": False, "require_registered": True}
STATUSES = ("waiting", "called", "done", "skipped")
MAX_MANUAL_ROWS = 20000


class QueueError(ValueError):
    """Mensaje en español, listo para mostrar."""


def strip_accents(text) -> str:
    return unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode("ascii")


def clean_config(raw) -> dict:
    """Valida lo que manda Parámetros. `lanes` puede ser lista de letras o de {letter, name}. Devuelve la configuración normalizada o lanza QueueError."""
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode") or DEFAULT_CONFIG["mode"]).strip().lower()
    if mode not in MODES:
        raise QueueError("El orden de los turnos no es válido")
    lanes, seen = [], set()
    for item in (raw.get("lanes") if raw.get("lanes") is not None else DEFAULT_CONFIG["lanes"]):
        letter, name = (item.get("letter"), item.get("name")) if isinstance(item, dict) else (item, "")
        letter = strip_accents(letter).strip().upper()
        if not re.fullmatch(r"[A-Z]", letter):
            raise QueueError("Cada fila se identifica con UNA letra de la A a la Z")
        if letter in seen:
            raise QueueError(f"La letra {letter} está repetida")
        seen.add(letter)
        name = " ".join(str(name or "").split())[:MAX_LANE_NAME]
        lanes.append({"letter": letter, "name": name})
    if not lanes:
        raise QueueError("Hace falta al menos una fila")
    if len(lanes) > MAX_LANES:
        raise QueueError(f"Máximo {MAX_LANES} filas")
    return {"mode": mode, "lanes": lanes, "show_name": bool(raw.get("show_name", False)), "require_registered": bool(raw.get("require_registered", True))}


def label(lane: str, number: int) -> str:
    return f"{lane}{int(number)}"


def sort_key_name(first, last) -> tuple:
    return (strip_accents(last).lower().strip(), strip_accents(first).lower().strip())


def order_people(mode: str, people: Iterable[dict]) -> list:
    """`people`: dicts con user_id, first_name, last_name, arrived_at, registered_at (los que apliquen). Devuelve la lista en el orden de los turnos
    (estable: el empate se resuelve por cédula). Las personas sin la fecha que pide el modo van al final."""
    people = list(people)
    if mode == "alpha":
        return sorted(people, key=lambda p: (sort_key_name(p.get("first_name"), p.get("last_name")), str(p.get("user_id"))))
    field = {"form": "registered_at", "arrival": "arrived_at"}.get(mode)
    if field is None:
        return people
    far = "9999"
    return sorted(people, key=lambda p: (p.get(field) is None, str(p.get(field) or far), str(p.get("user_id"))))


def pick_lane(lanes: list, waiting_by_lane: dict) -> str:
    """Fila para una persona nueva (varias filas): la que menos gente espera; empata la primera de la lista."""
    return min((l["letter"] for l in lanes), key=lambda x: (waiting_by_lane.get(x, 0), [l["letter"] for l in lanes].index(x)))


def assign_numbers(people_ordered: list, lanes: list, start: Optional[dict] = None, explicit_lane: Optional[dict] = None) -> list:
    """Reparte las personas ya ordenadas entre las filas y les pone número. `start`: último número usado por fila (para seguir después de lo que ya hay).
    `explicit_lane`: {user_id: letra} (Excel manual con la columna de fila). Devuelve [{user_id, lane, number, rank}]. Sin `explicit_lane`, se reparte en turnos
    rotativos (1.ª persona fila A, 2.ª fila B…) para que las filas avancen parejas."""
    letters = [l["letter"] for l in lanes]
    last = {x: int((start or {}).get(x, 0)) for x in letters}
    out, rot = [], 0
    for p in people_ordered:
        uid = p["user_id"]
        lane = (explicit_lane or {}).get(uid)
        if lane not in letters:
            lane = letters[rot % len(letters)]
            rot += 1
        last[lane] += 1
        out.append({"user_id": uid, "lane": lane, "number": last[lane], "rank": last[lane]})
    return out


# ------------------------------------------------------------------------------------------------------------------------ estado de las filas (a partir de las filas de turnos)
def build_snapshot(lanes: list, turns: list, calls: list, show_name: bool = False) -> dict:
    """`turns`: dicts {token, user_id, lane, number, rank, status, desk, name}; `calls`: los últimos llamados [{label, lane, desk, at}] del más nuevo al más viejo.
    No lleva cédulas: solo lo que se puede mostrar en una pantalla pública."""
    letters = [l["letter"] for l in lanes]
    names = {l["letter"]: l["name"] for l in lanes}
    waiting = {x: sorted(t["rank"] for t in turns if t["lane"] == x and t["status"] == "waiting") for x in letters}
    serving = {}
    for x in letters:
        called = [t for t in turns if t["lane"] == x and t["status"] == "called"]
        if called:
            t = max(called, key=lambda c: c.get("called_seq") or 0)
            serving[x] = {"label": label(x, t["number"]), "desk": t.get("desk") or ""}
    tokens = {}
    for t in turns:
        ahead = sum(1 for r in waiting.get(t["lane"], []) if r < t["rank"]) if t["status"] == "waiting" else 0
        tokens[t["token"]] = {"label": label(t["lane"], t["number"]), "lane": t["lane"], "lane_name": names.get(t["lane"], ""), "status": t["status"], "ahead": ahead,
                              "name": (t.get("name") or "") if show_name else ""}
    by_user = {str(t["user_id"]): t["token"] for t in turns}
    return {"lanes": [{"letter": x, "name": names[x], "waiting": len(waiting[x]), "serving": serving.get(x)} for x in letters], "recent": list(calls)[:8],
            "tokens": tokens, "by_user": by_user}


def public_view(snap: dict, token: str) -> Optional[dict]:
    """Lo que ve la persona en su teléfono: su turno, cuántos faltan, a quién están llamando en su fila y si ya es su turno."""
    me = snap["tokens"].get(token)
    if me is None:
        return None
    lane = next((l for l in snap["lanes"] if l["letter"] == me["lane"]), None) or {}
    serving = (lane.get("serving") or {}).get("label", "")
    return {"label": me["label"], "lane": me["lane"], "lane_name": me["lane_name"], "status": me["status"], "ahead": me["ahead"], "name": me["name"],
            "serving": serving, "desk": (lane.get("serving") or {}).get("desk", "") if me["status"] == "called" else "", "your_turn": me["status"] == "called"}


def tv_view(snap: dict) -> dict:
    return {"lanes": snap["lanes"], "recent": snap["recent"]}


# ------------------------------------------------------------------------------------------------------------------------ Excel manual
HEADER_ALIASES = {"cedula": ("cedula", "documento", "id", "identificacion", "cc"), "order": ("orden", "turno", "posicion", "n", "numero", "#"), "lane": ("fila", "letra", "linea")}


def _norm_header(v) -> str:
    return re.sub(r"[^a-z0-9#]+", "", strip_accents(v).lower())


def map_headers(header_cells) -> dict:
    """{campo: índice de columna}. Acepta «Cédula/Documento/ID», «Orden/Turno/Posición» y «Fila/Letra». La cédula es obligatoria; si falta «Orden» se usa el orden del archivo."""
    found = {}
    for i, h in enumerate(header_cells):
        n = _norm_header(h)
        for field, names in HEADER_ALIASES.items():
            if n in names and field not in found:
                found[field] = i
    if "cedula" not in found:
        raise QueueError("El Excel necesita una columna «Cédula» (primera fila con los títulos)")
    return found


def clean_cedula(v) -> str:
    """Quita puntos, espacios y el «.0» que Excel agrega a un número; conserva letras (pasaporte)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = re.sub(r"[\s.]", "", str(v)).strip()
    return s.upper()


def parse_manual_rows(rows: list, lanes: list) -> dict:
    """`rows`: lista de filas (listas de celdas) con la primera = títulos. Devuelve {"people": [{user_id, lane?}] en el orden pedido, "errors": [texto], "duplicates": n}.
    Orden: por la columna «Orden» (numérica) si existe; si no, el del archivo. Cédulas repetidas: se queda la primera."""
    if not rows:
        raise QueueError("El Excel está vacío")
    if len(rows) - 1 > MAX_MANUAL_ROWS:
        raise QueueError(f"El Excel tiene demasiadas filas (máximo {MAX_MANUAL_ROWS})")
    cols = map_headers(rows[0])
    letters = {l["letter"] for l in lanes}
    items, errors, seen, dup = [], [], set(), 0
    for n, row in enumerate(rows[1:], start=2):
        cells = list(row) + [None] * 4
        ced = clean_cedula(cells[cols["cedula"]])
        if not ced:
            continue
        if ced in seen:
            dup += 1
            continue
        seen.add(ced)
        order = None
        if "order" in cols:
            raw = cells[cols["order"]]
            try:
                order = float(str(raw).replace(",", ".")) if raw not in (None, "") else None
            except ValueError:
                errors.append(f"Fila {n}: el orden «{str(raw)[:12]}» no es un número")
        lane = None
        if "lane" in cols and cells[cols["lane"]] not in (None, ""):
            lane = strip_accents(cells[cols["lane"]]).strip().upper()[:1]
            if lane not in letters:
                errors.append(f"Fila {n}: la fila «{lane}» no existe en la configuración")
                lane = None
        items.append({"user_id": ced, "lane": lane, "order": order, "pos": n})
    items.sort(key=lambda i: (i["order"] is None, i["order"] if i["order"] is not None else 0, i["pos"]))
    return {"people": [{"user_id": i["user_id"], "lane": i["lane"]} for i in items], "errors": errors[:20], "duplicates": dup}
