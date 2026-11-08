"""Plantilla de evento: la parte que toca la base (cargar, guardar con bloqueo optimista, historial, y preparar la creación de un evento). La lógica pura está en app/event_template.py.

Sin SET de sesión ni advisory locks (pooler de Neon en modo transacción): el bloqueo optimista usa `version` y `SELECT … FOR UPDATE`, que sí se puede."""
import json
import logging

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import event_template as et
from app.models import EventFieldConfig, EventTemplate, EventTemplateRevision, StaffUser
from app.timeutil import utcnow

log = logging.getLogger("golden.event_template")
KEEP_REVISIONS = 50


def _row(db: Session, scope: str = et.SCOPE_GLOBAL, lock: bool = False):
    q = db.query(EventTemplate).filter(EventTemplate.scope == scope)
    return (q.with_for_update() if lock else q).first()


def from_row(db: Session, row) -> dict:
    """La plantilla vigente como dict: {fields, creation_layout, calendar_layout, version, updated_at, updated_by, is_default}. Sin fila = la de fábrica (versión 0)."""
    if row is None:
        tpl = et.default_template()
        tpl.update(version=0, updated_at=None, updated_by=None, is_default=True)
        return tpl
    try:
        tpl = {"fields": json.loads(row.fields_json), "creation_layout": json.loads(row.creation_layout_json), "calendar_layout": json.loads(row.calendar_layout_json)}
        tpl = et.merge_missing_base(tpl)
    except (ValueError, KeyError, TypeError):
        log.error("plantilla de evento ilegible (id=%s): se usa la de fábrica", row.id)
        tpl = et.default_template()
    by = db.get(StaffUser, row.updated_by_id) if row.updated_by_id else None
    tpl.update(version=row.version, updated_at=row.updated_at.isoformat() if row.updated_at else None,
               updated_by=(by.full_name or by.username) if by else None, is_default=False)
    return tpl


def load(db: Session, scope: str = et.SCOPE_GLOBAL) -> dict:
    return from_row(db, _row(db, scope))


def people(db: Session) -> dict:
    """Personal activo que se puede elegir en los campos «Comercial» y «Coordinador» (solo id y nombre): sirve a quien crea el evento y al calendario para escribir el nombre de un id.
    Es lo mismo que ya se ve en cada evento (nombre del coordinador y de la comercial)."""
    out = {}
    for role in ("commercial", "coordinator"):
        db_role = "comercial" if role == "commercial" else "coordinador"
        rows = (db.query(StaffUser.id, StaffUser.full_name, StaffUser.username)
                .filter(StaffUser.is_active == True, or_(StaffUser.role == db_role, StaffUser.secondary_role == db_role))      # noqa: E712
                .order_by(StaffUser.full_name, StaffUser.username).limit(500).all())
        out[role] = [{"id": r[0], "name": r[1] or r[2]} for r in rows]
    return out


def public_view(db: Session, tpl: dict = None) -> dict:
    tpl = tpl or load(db)
    return {**tpl, "scope": et.SCOPE_GLOBAL, "catalog": et.catalog(), "people": people(db)}


def save(db: Session, staff: StaffUser, payload, scope: str = et.SCOPE_GLOBAL) -> dict:
    """Guarda la plantilla completa. `payload["version"]` = la versión que el administrador estaba editando: si otro guardó antes, 409 (nadie pisa a nadie en silencio)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="La plantilla debe ser un objeto")
    try:
        expected = int(payload.get("version"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Falta la versión de la plantilla que estás editando: recarga la pantalla")
    row = _row(db, scope, lock=True)
    current = row.version if row else 0
    if expected != current:
        raise HTTPException(status_code=409, detail=f"Otro administrador guardó la plantilla (versión {current}) mientras la editabas. Recarga la pantalla para ver sus cambios y vuelve a hacer los tuyos.")
    previous = from_row(db, row) if row else None
    try:
        clean = et.validate_template(payload, previous=previous)
    except et.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))      # noqa: E731
    now = utcnow()
    try:
        if row is None:
            row = EventTemplate(scope=scope, version=1, fields_json=dump(clean["fields"]), creation_layout_json=dump(clean["creation_layout"]),
                                calendar_layout_json=dump(clean["calendar_layout"]), updated_at=now, updated_by_id=staff.id)
            db.add(row)
        else:
            row.version = current + 1
            row.fields_json, row.creation_layout_json, row.calendar_layout_json = dump(clean["fields"]), dump(clean["creation_layout"]), dump(clean["calendar_layout"])
            row.updated_at, row.updated_by_id = now, staff.id
        db.flush()
        db.add(EventTemplateRevision(template_id=row.id, version=row.version, snapshot_json=dump(clean), saved_by_id=staff.id, saved_at=now))
        db.flush()
        old = db.query(EventTemplateRevision.id).filter(EventTemplateRevision.template_id == row.id).order_by(EventTemplateRevision.id.desc()).offset(KEEP_REVISIONS).all()
        if old:
            db.query(EventTemplateRevision).filter(EventTemplateRevision.id.in_([r[0] for r in old])).delete(synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Otro administrador guardó la plantilla al mismo tiempo. Recarga la pantalla y vuelve a intentarlo.")
    log.info("plantilla de evento guardada: versión %s por el usuario %s", row.version, staff.id)
    return public_view(db, from_row(db, row))


def revisions(db: Session, scope: str = et.SCOPE_GLOBAL, limit: int = 20) -> list:
    row = _row(db, scope)
    if row is None:
        return []
    out = []
    for r in db.query(EventTemplateRevision).filter(EventTemplateRevision.template_id == row.id).order_by(EventTemplateRevision.id.desc()).limit(limit):
        by = db.get(StaffUser, r.saved_by_id) if r.saved_by_id else None
        out.append({"version": r.version, "saved_at": r.saved_at.isoformat() if r.saved_at else None, "saved_by": (by.full_name or by.username) if by else None})
    return out


# ------------------------------------------------------------------------------------------------------------------------------------ crear un evento
def prepare_creation(db: Session, payload: dict, extra, waive=()) -> dict:
    """Valida lo que manda «Nuevo evento» con la plantilla vigente y la base (personal que existe y está activo). Devuelve
    {"columns": {bandana y interruptores, ya como columnas de events}, "extra": {personalizados}, "template": plantilla}. Lanza 400 con el motivo en español."""
    if extra is None:
        extra = {}
    if not isinstance(extra, dict):
        raise HTTPException(status_code=400, detail="Los campos adicionales llegaron en un formato inválido")
    tpl = load(db)
    res = et.evaluate_creation(tpl, et.raw_values_from_payload(payload, extra), waive=waive, extra_keys=list(extra))
    clean = res["clean"]
    errors = list(res["errors"])
    by_key = {f["key"]: f for f in tpl["fields"]}
    for k, v in clean.items():              # personal que debe existir (los campos base ya los valida create_event con su regla de siempre)
        f = by_key[k]
        if k in et.BOUND_KEYS or f["type"] not in ("commercial", "coordinator"):
            continue
        role = {"commercial": "comercial", "coordinator": "coordinador"}[f["type"]]          # el tipo del campo va en inglés; el rol en la base, en español
        ok = db.query(StaffUser.id).filter(StaffUser.id == v, StaffUser.is_active == True, or_(StaffUser.role == role, StaffUser.secondary_role == role)).first()      # noqa: E712
        if not ok:
            errors.append(f"«{f['title']}»: la persona elegida no es válida")
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    cols, extra_clean = et.split_clean(clean)
    if not et.extra_size_ok(extra_clean):
        raise HTTPException(status_code=400, detail="Los campos adicionales del evento son demasiado grandes")
    base_cols = {k: v for k, v in cols.items() if k in ("bandana_color", "bandana_color_name") or k in et.SWITCH_KEYS}
    return {"columns": base_cols, "extra": extra_clean, "template": tpl, "clean": clean}


def after_create(db: Session, event) -> None:
    """Efectos que «Parámetros del evento» ya tiene al prender una opción, para que prenderla al crear sea EXACTAMENTE igual (misma fuente, mismo resultado)."""
    if event.digital_badge_enabled:          # parametros.set_digital_badge_enabled: el campo del correo corporativo nace obligatorio
        if not db.query(EventFieldConfig).filter_by(event_id=event.id, field_key="digital_contact").first():
            db.add(EventFieldConfig(event_id=event.id, field_key="digital_contact", required=True, field_type="text_short"))


def merge_extra(db: Session, current: dict, patch: dict) -> dict:
    """Edición de un evento: aplica `patch` ({clave: valor}; null borra) sobre los valores personalizados guardados. Solo campos personalizados activos de la plantilla;
    los retirados no se editan (sus valores se conservan tal cual)."""
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="Los campos adicionales llegaron en un formato inválido")
    tpl = load(db)
    by_key = {f["key"]: f for f in tpl["fields"]}
    out, errors = dict(current or {}), []
    for k, v in patch.items():
        f = by_key.get(k)
        if f is None or k in et.BOUND_KEYS:
            errors.append(f"El campo «{k}» no existe en la plantilla")
        elif f["retired"]:
            errors.append(f"El campo «{f['title']}» fue retirado de la plantilla")
        else:
            try:
                clean = et.clean_value(f, v)
            except et.TemplateError as exc:
                errors.append(str(exc))
                continue
            if clean is None:
                if f["required"]:
                    errors.append(f"«{f['title']}» es obligatorio")
                out.pop(k, None)
            else:
                out[k] = clean
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    if not et.extra_size_ok(out):
        raise HTTPException(status_code=400, detail="Los campos adicionales del evento son demasiado grandes")
    return out
