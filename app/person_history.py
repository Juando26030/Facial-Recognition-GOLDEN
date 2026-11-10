"""Historial de datos modificados por persona (Fase 10, bloque E · docs/FASE_10_AJUSTES_NOV10.md).

Además del registro inicial (quién y cuándo se escaneó), cada vez que se CAMBIA un dato de una persona que ya existía (la ciudad, el correo, el cargo…) queda una fila por campo en `person_change_log`:
campo, valor anterior, valor nuevo, quién lo cambió, cuándo y por dónde (`source`).

Uso en cada punto donde se edita una persona (siempre el mismo patrón, sin commit propio):
    before = person_history.snapshot(user)          # ANTES de tocar nada
    ... se cambian los campos ...
    person_history.record(db, user, before, event_id=event.id, staff_id=staff.id, source="edit")

* Solo datos de texto de la persona: first_name, last_name, role, entity, phone, email, opt_1 y los opcionales (`opcional_N`). NUNCA rostro, foto, vector ni consentimiento. La fecha de nacimiento
  ya tiene su propio historial (`person_changes`, kind «birth_date») y no se repite aquí.
* La persona de prueba (cédula PRUEBA) no deja historial. Una persona recién creada tampoco (eso es el registro inicial, no un cambio).
* Privacidad: el historial vive en la base, jamás en los logs (aquí no se escribe ningún valor ni cédula en logs). Se borra con la persona (`privacy.erase_person`, «Eliminar del evento») y con el evento.
  Como no guarda biometría, la purga biométrica (7 días / 180 días) no necesita tocarlo.
* Pura la comparación (`diff`), por eso se prueba sin base de datos.
"""
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app import testperson
from app.models import PersonChangeLog, User
from app.timeutil import to_local, utcnow

USER_FIELDS = ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1")
USER_LABELS = {"id": "Cédula", "first_name": "Nombres", "last_name": "Apellidos", "role": "Cargo", "entity": "Entidad", "phone": "Teléfono", "email": "Correo", "opt_1": "Tipo de asistente"}
SOURCES = {"edit": "Edición", "outbox": "Edición sin conexión", "bulk": "Carga masiva", "form": "Formulario web", "register": "Registro", "autoregistro": "Autorregistro"}
MAX_VALUE = 500
EXTRA_RE = re.compile(r"^opcional_\d+$")
HISTORY_PAGE_MAX = 200


def _norm(v) -> str:
    return "" if v is None else str(v).strip()


def snapshot(user: User) -> dict:
    """Los datos de texto de la persona tal como están ahora (para comparar antes/después). Los opcionales van con su llave `opcional_N`."""
    out = {k: _norm(getattr(user, k, None)) for k in USER_FIELDS}
    try:
        extras = user.get_extras()
    except Exception:                    # JSON dañado: no impide guardar un cambio
        extras = {}
    for k, v in (extras or {}).items():
        if EXTRA_RE.match(str(k)):
            out[str(k)] = _norm(v)
    return out


def diff(before: dict, after: dict) -> list:
    """[(campo, anterior, nuevo)] de lo que cambió de verdad (vacío = None = espacios). PURA. Orden estable: campos fijos y luego opcionales por número."""
    def order(k):
        if k in USER_FIELDS:
            return (0, USER_FIELDS.index(k))
        m = re.search(r"(\d+)$", k)
        return (1, int(m.group(1)) if m else 0)
    changes = []
    for key in sorted(set(before) | set(after), key=order):
        old, new = _norm(before.get(key)), _norm(after.get(key))
        if old != new:
            changes.append((key, old[:MAX_VALUE], new[:MAX_VALUE]))
    return changes


def record(db: Session, user: User, before: dict, *, event_id: Optional[int], staff_id: Optional[int] = None, source: str = "edit", at=None) -> int:
    """Guarda una fila por campo que cambió entre `before` y el estado actual de `user`. No hace commit (lo hace quien llama, en la misma transacción que el cambio). Devuelve cuántas filas agregó."""
    if user is None or testperson.is_test(user.id):
        return 0
    changes = diff(before or {}, snapshot(user))
    when = at or utcnow()
    for key, old, new in changes:
        db.add(PersonChangeLog(tenant_id=user.tenant_id, event_id=event_id, user_id=user.id, field_key=key, old_value=old or None, new_value=new or None,
                               changed_by_id=staff_id, source=source if source in SOURCES else "edit", changed_at=when))
    return len(changes)


def record_id_change(db: Session, tenant_id: str, new_id: str, old_id: str, *, event_id: Optional[int], staff_id: Optional[int]) -> None:
    """Corrección de la cédula (`PUT /users/{id}/cedula`): queda como un cambio del campo «Cédula». Sin commit."""
    if testperson.is_test(old_id) or testperson.is_test(new_id):
        return
    db.add(PersonChangeLog(tenant_id=tenant_id, event_id=event_id, user_id=new_id, field_key="id", old_value=str(old_id)[:MAX_VALUE], new_value=str(new_id)[:MAX_VALUE],
                           changed_by_id=staff_id, source="edit", changed_at=utcnow()))


# ------------------------------------------------------------------ lectura
def labels_for(db: Session, event) -> dict:
    """{llave: etiqueta} de los campos de la persona con los nombres que usa ESTE evento (los opcionales tienen nombre propio por evento)."""
    labels = dict(USER_LABELS)
    if event is not None:
        try:
            from app.routers import parametros
            labels.update(parametros.field_labels_for_event(db, event))
        except Exception:                # sin etiquetas del evento se muestra la llave: nunca se cae la ficha
            pass
    return labels


def _row(r: PersonChangeLog, labels: dict, staff_names: dict) -> dict:
    return {"id": r.id, "field": r.field_key, "label": labels.get(r.field_key) or r.field_key, "old": r.old_value or "", "new": r.new_value or "", "by": staff_names.get(r.changed_by_id) or ("La persona" if r.changed_by_id is None else "Cuenta eliminada"),
            "by_id": r.changed_by_id, "source": r.source, "source_label": SOURCES.get(r.source, r.source), "at": r.changed_at.isoformat() if r.changed_at else None, "at_local": to_local(r.changed_at).strftime("%d/%m/%Y %H:%M") if r.changed_at else "", "event_id": r.event_id}


def staff_names(db: Session, ids: Iterable) -> dict:
    from app.models import StaffUser
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {s.id: (s.full_name or s.username) for s in db.query(StaffUser).filter(StaffUser.id.in_(ids))}


def history(db: Session, event, user_id: str, limit: int = 100) -> list:
    """Los cambios de una persona (los más recientes primero). Solo los de ESTE cliente; si el evento se da, los de ese evento y los hechos fuera de un evento."""
    limit = max(1, min(int(limit or 100), HISTORY_PAGE_MAX))
    rows = (db.query(PersonChangeLog).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.user_id == str(user_id))
            .order_by(PersonChangeLog.changed_at.desc(), PersonChangeLog.id.desc()).limit(limit).all())
    names = staff_names(db, (r.changed_by_id for r in rows))
    labels = labels_for(db, event)
    return [_row(r, labels, names) for r in rows]


def event_rows(db: Session, event) -> list:
    """TODOS los cambios de las personas de un evento, para la exportación a Excel (sin la persona de prueba), del más antiguo al más nuevo: [{cedula, label, old, new, by, at, source_label}]."""
    rows = (db.query(PersonChangeLog).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.event_id == event.id, PersonChangeLog.user_id != testperson.TEST_ID)
            .order_by(PersonChangeLog.changed_at.asc(), PersonChangeLog.id.asc()).all())
    names = staff_names(db, (r.changed_by_id for r in rows))
    labels = labels_for(db, event)
    people = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_({r.user_id for r in rows}))} if rows else {}
    out = []
    for r in rows:
        d = _row(r, labels, names)
        u = people.get(r.user_id)
        d["cedula"] = r.user_id
        d["name"] = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip() if u else ""
        out.append(d)
    return out


# ------------------------------------------------------------------ borrado
def delete_for_person(db: Session, tenant_id: str, user_id: str, event_id: Optional[int] = None) -> int:
    """Borra el historial de una persona (todo el del cliente, o solo el de un evento). Sin commit. Lo usan la supresión y «Eliminar del evento»."""
    q = db.query(PersonChangeLog).filter(PersonChangeLog.tenant_id == tenant_id, PersonChangeLog.user_id == str(user_id))
    if event_id is not None:
        q = q.filter(PersonChangeLog.event_id == event_id)
    return q.delete(synchronize_session=False)


def delete_for_event(db: Session, event_id: int) -> int:
    return db.query(PersonChangeLog).filter(PersonChangeLog.event_id == event_id).delete(synchronize_session=False)
