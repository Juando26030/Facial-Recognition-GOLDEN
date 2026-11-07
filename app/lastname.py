"""¿El apellido es obligatorio en este evento? (Fase 2, regla de Juan David).

«Si en la base no se usa el campo de apellido (todo va en nombres), el apellido NO es obligatorio y se puede desmarcar; si se usaron nombres y apellidos por separado, ambos son obligatorios.»

Se decide solo al cargar la base del evento (`detect`: la columna de apellidos existe Y al menos la mitad de las personas tiene apellido) y se guarda en `app_settings`
(clave `last_name_req:<evento>`, SIN migración):
  {"auto": bool|null, "manual": bool|null, "total": n, "with_last": n, "updated": iso}
`manual` (lo que el coordinador/admin eligió en Parámetros) MANDA sobre `auto`; `manual = null` vuelve al automático. Evento sin dato guardado: se comporta como siempre (apellido opcional).
El valor efectivo se inyecta como `required` del campo `last_name` en `parametros.field_configs_for_event`, de modo que la pantalla de registro, el editor, el formulario de persona diseñado y su copia
sin red (versionada) lo vean igual; el servidor lo vuelve a comprobar (`missing_message`)."""
import json
from typing import Optional

from app.models import AppSetting
from app.timeutil import utcnow

MIN_SHARE = 0.5               # proporción mínima de filas con apellido para decir que el evento usa apellido
_ID_KEYS = ("id", "identificación", "cedula", "cédula")
_LAST_KEYS = ("apellidos", "apellido")
MISSING_MSG = "El apellido es obligatorio en este evento. Escríbelo (o desmarca «Apellido obligatorio» en Parámetros del evento)."


def setting_key(event_id: int) -> str:
    return f"last_name_req:{int(event_id)}"


def detect(rows: list, header_columns: Optional[dict] = None) -> Optional[dict]:
    """Mira las filas de la base cargada (claves ya canónicas) y dice si usa apellido. None si no hay filas con cédula (no se puede decidir)."""
    people = [r for r in rows if any(str(r.get(k) or "").strip() for k in _ID_KEYS)]
    if not people:
        return None
    has_column = any(k in (header_columns or {}) for k in _LAST_KEYS) or any(k in r for r in people for k in _LAST_KEYS)
    with_last = sum(1 for r in people if any(str(r.get(k) or "").strip() for k in _LAST_KEYS))
    total = len(people)
    return {"uses": bool(has_column and with_last / total >= MIN_SHARE), "total": total, "with_last": with_last}


def _load(db, event_id: int) -> dict:
    row = db.get(AppSetting, setting_key(event_id))
    if row is None or not row.value:
        return {}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _bool_or_none(v):
    return v if isinstance(v, bool) else None


def state(db, event_id: int) -> dict:
    """{required, source: manual|auto|default, auto, manual, total, with_last}. Sin dato guardado: no obligatorio (comportamiento de siempre)."""
    data = _load(db, event_id)
    auto, manual = _bool_or_none(data.get("auto")), _bool_or_none(data.get("manual"))
    if manual is not None:
        required, source = manual, "manual"
    elif auto is not None:
        required, source = auto, "auto"
    else:
        required, source = False, "default"
    return {"required": required, "source": source, "auto": auto, "manual": manual, "total": data.get("total"), "with_last": data.get("with_last")}


def is_required(db, event_id: int) -> bool:
    return state(db, event_id)["required"]


def _save(db, event, data: dict) -> None:
    before = is_required_from(_load(db, event.id))
    row = db.get(AppSetting, setting_key(event.id))
    if row is None:
        row = AppSetting(key=setting_key(event.id))
        db.add(row)
    data["updated"] = utcnow().isoformat()
    row.value = json.dumps(data, ensure_ascii=False)
    row.updated_at = utcnow()
    if before != is_required_from(data):
        _bump_person_form(db, event)
    db.flush()


def is_required_from(data: dict) -> bool:
    manual, auto = _bool_or_none(data.get("manual")), _bool_or_none(data.get("auto"))
    return manual if manual is not None else bool(auto)


def _bump_person_form(db, event) -> None:
    """Si el evento tiene formulario de persona diseñado, sube su versión: las copias sin red (quioscos que no han vuelto a sincronizar) quedan como «anteriores» y su alta no se pierde por la regla nueva."""
    from app import personform
    stored = personform.load_raw(db, event)
    if not stored:
        return
    stored["form_version"] = int(stored.get("form_version") or 1) + 1
    row = db.get(AppSetting, personform.setting_key(event.id))
    row.value = json.dumps(stored, ensure_ascii=False)
    row.updated_at = utcnow()


def record_detection(db, event, result: Optional[dict]) -> Optional[bool]:
    """Guarda lo detectado en la carga (`auto`). No toca lo manual. El commit lo hace quien llama. Devuelve el `auto` guardado (o None si no había qué decidir)."""
    if not result:
        return None
    data = _load(db, event.id)
    data.update({"auto": bool(result["uses"]), "total": int(result["total"]), "with_last": int(result["with_last"])})
    _save(db, event, data)
    return data["auto"]


def set_manual(db, event, value: Optional[bool]) -> dict:
    """`True`/`False` = lo decide la persona; `None` = volver al automático. El commit lo hace quien llama."""
    data = _load(db, event.id)
    data["manual"] = value
    _save(db, event, data)
    return state(db, event.id)


def missing_message(required: bool, last_name) -> Optional[str]:
    """El error en español si el apellido es obligatorio y viene vacío; None si todo bien."""
    if required and not str(last_name or "").strip():
        return MISSING_MSG
    return None
