"""Rutas del inventario «lo define la base», la base de dependientes y el bloqueo de la configuración del digitador (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md).
La lógica vive en app/inv_assign.py, app/dependents.py y app/config_lock.py; aquí solo permisos, validación de entrada y respuestas."""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import config_lock, dependents, event_archive, event_lease, inv_assign, node_precheck, uploads
from app import inv_assign_core as core
from app.auth import effective_roles, get_event_for_staff, require_event_in_progress, require_role_excluding
from app.database import get_db
from app.models import StaffUser

log = logging.getLogger("golden.inv_base")
router = APIRouter()
CONFIG_ROLE = require_role_excluding("coordinador", ("comercial",))
OPERATE_ROLE = require_role_excluding("digitador", ("comercial",))


def _event(db, event_id, staff, *, write=False):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    if write:
        event_lease.assert_writable_by(event, staff)
    return event


# ------------------------------------------------------------------------------------------------ configuración (Parámetros)
def _assign_state(db, event) -> dict:
    return {
        "config": inv_assign.get_config(event),
        "holder_fields": inv_assign.holder_fields(event),
        "dependent_columns": inv_assign.dependent_columns(db, event),
        "has_dependents": dependents.has_dependents(db, event.id),
        "summary": inv_assign.summary(db, event) if inv_assign.mode(event) == core.MODE_ASSIGNED else None,
        "over_deliveries": inv_assign.over_deliveries(db, event)[:100] if inv_assign.mode(event) == core.MODE_ASSIGNED else [],
    }


@router.get("/events/{event_id}/inventory-assign")
def get_inventory_assign(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    return _assign_state(db, _event(db, event_id, staff))


@router.put("/events/{event_id}/inventory-assign")
def put_inventory_assign(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Guarda «¿Quién decide qué se le entrega a cada persona?» y las columnas. En «La base lo define» crea de una vez los productos que faltan (con el stock = lo asignado)."""
    event = _event(db, event_id, staff, write=True)
    inv_assign.set_config(db, event, data or {})
    if inv_assign.mode(event) == core.MODE_ASSIGNED:
        inv_assign.sync_items(db, event, staff)
    db.commit()
    return _assign_state(db, event)


@router.post("/events/{event_id}/inventory-assign/sync")
def sync_inventory_assign(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """«Actualizar productos desde la base»: crea los productos nuevos que pide la base (el stock de los que ya existen no se toca)."""
    event = _event(db, event_id, staff, write=True)
    if inv_assign.mode(event) != core.MODE_ASSIGNED:
        raise HTTPException(status_code=400, detail="Esto solo aplica cuando «La base lo define»")
    out = inv_assign.sync_items(db, event, staff)
    db.commit()
    return out


@router.post("/events/{event_id}/inventory-assign/match-stock")
def match_inventory_stock(event_id: int, data: dict = None, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """«Igualar el stock a lo asignado»: sube la cantidad inicial de un producto (o de todos los que faltan) hasta lo que pide la base. Nunca la baja."""
    event = _event(db, event_id, staff, write=True)
    item_id = (data or {}).get("item_id")
    try:
        item_id = int(item_id) if item_id not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Producto no válido")
    n = inv_assign.match_stock(db, event, item_id)
    db.commit()
    return {"changed": n, "summary": inv_assign.summary(db, event)}


# ------------------------------------------------------------------------------------------------ entrega (puesto de inventario)
def _find(db, event, cedula: str):
    from app.routers.areas_inventory import _find_person
    return _find_person(db, event, str(cedula or "").strip())


@router.get("/events/{event_id}/inventory/assigned")
def assigned_for_person(event_id: int, cedula: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Lo que le corresponde a una persona según la base: lo suyo, lo de sus dependientes y lo que le asignaron como dependiente de otro titular."""
    event = _event(db, event_id, staff)
    if not inv_assign.is_assigned(event):
        raise HTTPException(status_code=400, detail="En este evento la persona elige lo que recibe (no lo define la base)")
    user = _find(db, event, cedula)
    lines = inv_assign.person_lines(db, event, user)
    return {"person": {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "entity": user.entity},
            "registered": dependents.is_registered(db, event, user.id), "lines": lines,
            "pending": sum(1 for ln in lines if ln["pending"] > 0 and not ln["problem"])}


@router.post("/events/{event_id}/inventory/deliver-assigned")
def deliver_assigned(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Entrega lo asignado: `{cedula, keys: [...]}` (las asignaciones elegidas) o `{cedula, all: true}` (todo lo pendiente). Solo a personas REGISTRADAS."""
    event = _event(db, event_id, staff, write=True)
    require_event_in_progress(event)
    if not inv_assign.is_assigned(event):
        raise HTTPException(status_code=400, detail="En este evento la persona elige lo que recibe: usa «Entregar» de siempre")
    user = _find(db, event, (data or {}).get("cedula"))
    warning = ""

    def precheck(uid, keys):
        nonlocal warning
        ans = node_precheck.ask(event, uid, keys=keys)
        if ans is None:
            warning = node_precheck.OFFLINE_WARNING
            return {}
        return ans.get("keys") or {}

    out = inv_assign.deliver(db, event, staff, user, (data or {}).get("keys"), everything=bool((data or {}).get("all")), precheck=precheck)
    out["lines"] = inv_assign.person_lines(db, event, user)
    out["person"] = {"id": user.id, "first_name": user.first_name, "last_name": user.last_name}
    if warning:
        out["warning"] = warning
    return out


# ------------------------------------------------------------------------------------------------ base de dependientes
@router.get("/events/{event_id}/dependents")
def list_dependents(event_id: int, holder: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Los dependientes de un titular (para «Editar persona»): agrupados por persona, con sus datos."""
    event = _event(db, event_id, staff)
    people = dependents.people_of(db, event, str(holder or "").strip())
    return {"count": len(people), "people": [{"label": p["label"], "doc": p["doc"], "rows": [r["data"] for r in p["rows"]]} for p in people]}


@router.get("/events/{event_id}/dependents/search")
def search_dependents(event_id: int, q: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Buscar a un dependiente por su nombre o documento (mínimo 3 caracteres): devuelve a qué titular está asociado."""
    return {"results": dependents.search(db, _event(db, event_id, staff), q)}


@router.get("/events/{event_id}/dependents/summary")
def dependents_summary(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = _event(db, event_id, staff)
    counts = dependents.counts_by_holder(db, event)
    from app.models import EventDependent
    rows = db.query(EventDependent.id).filter(EventDependent.event_id == event.id).count()
    return {"rows": rows, "dependents": sum(counts.values()), "holders": sum(1 for v in counts.values() if v)}


def _read_upload(event_id: int, roster_file, roster_upload):
    up = uploads.fetch(roster_upload, "bulk_roster", {"e": event_id})
    content = up.content if up else (roster_file.file.read() if (roster_file is not None and roster_file.filename) else None)
    if content is None:
        raise HTTPException(status_code=400, detail="Sube el archivo de dependientes (Excel o CSV).")
    return up, (up.filename if up else roster_file.filename), content


def _dep_load_guard(event):
    if event.status == "finalizado":
        raise HTTPException(status_code=400, detail="El evento ya finalizó: no se puede cargar la base de dependientes.")


def _public_analysis(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


@router.post("/events/{event_id}/dependents/preview")
def preview_dependents(event_id: int, roster_file: UploadFile = File(None), roster_upload: str = Form(None), mode: str = Form("replace"),
                       db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Vista previa SIN escribir nada: columnas reconocidas, filas que entran y las que no (y por qué), cómo cambia el campo «Dependientes» y 10 titulares de muestra."""
    event = _event(db, event_id, staff, write=True)
    _dep_load_guard(event)
    _up, name, content = _read_upload(event_id, roster_file, roster_upload)
    titles, rows = dependents.read_file(name, content)
    cfg = inv_assign.get_config(event)
    out = _public_analysis(dependents.analyze(db, event, titles, rows, mode, cfg.get("dep_product")))
    db.rollback()
    return out


@router.post("/events/{event_id}/dependents/load")
def load_dependents(event_id: int, roster_file: UploadFile = File(None), roster_upload: str = Form(None), mode: str = Form("replace"),
                    db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Carga la base de dependientes (reemplazar o agregar). Vuelve a leer el archivo y a planear aquí mismo (no se confía en la vista previa del navegador)."""
    event = _event(db, event_id, staff, write=True)
    _dep_load_guard(event)
    up, name, content = _read_upload(event_id, roster_file, roster_upload)
    titles, rows = dependents.read_file(name, content)
    cfg = inv_assign.get_config(event)
    analysis = dependents.analyze(db, event, titles, rows, mode, cfg.get("dep_product"))
    out = dependents.apply(db, event, staff, analysis)
    if inv_assign.is_assigned(event):
        out["inventory"] = inv_assign.sync_items(db, event, staff)
    from app import audit_actions
    audit_actions.record(db, staff, "load", "event_dependents", event.id, event.name, f"modo {mode}; {out['inserted']} nuevas, {out['deleted']} borradas, {out['kept']} conservadas")
    db.commit()
    uploads.discard(up)
    out["message"] = (f"Base de dependientes cargada: {out['dependents']} dependientes de {out['holders']} titulares "
                      f"({out['inserted']} filas nuevas, {out['deleted']} borradas, {out['kept']} sin cambios" + (f", {out['skipped']} filas no se cargaron" if out["skipped"] else "") + ").")
    return out


@router.delete("/events/{event_id}/dependents")
def delete_dependents(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Borra la base de dependientes (lo ya entregado se conserva). Pide escribir BORRAR."""
    event = _event(db, event_id, staff, write=True)
    if str((data or {}).get("confirm") or "").strip().upper() != "BORRAR":
        raise HTTPException(status_code=400, detail="Para confirmar escribe BORRAR")
    out = dependents.delete_all(db, event)
    from app import audit_actions
    audit_actions.record(db, staff, "delete", "event_dependents", event.id, event.name, f"{out['deleted']} filas borradas, {out['kept_delivered']} conservadas por tener entregas")
    db.commit()
    return {**out, "message": f"Se borraron {out['deleted']} filas de dependientes" + (f"; se conservaron {out['kept_delivered']} que ya tienen entregas." if out["kept_delivered"] else ".")}


@router.put("/events/{event_id}/dependents-badge")
def set_dependents_badge(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """«Imprimir escarapela también a los dependientes» (apagada por defecto)."""
    event = _event(db, event_id, staff, write=True)
    value = (data or {}).get("enabled")
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="enabled debe ser verdadero o falso")
    event.dependents_badge = value
    db.commit()
    return {"enabled": value}


# ------------------------------------------------------------------------------------------------ bloqueo de la configuración del digitador
@router.get("/events/{event_id}/config-lock")
def get_config_lock(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    return config_lock.admin_state(db, _event(db, event_id, staff))


@router.put("/events/{event_id}/config-lock")
def put_config_lock(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """`areas_locked`, `inventory_locked` (bool), `password` (texto nuevo) o `clear_password: true`. Solo lo que venga se cambia."""
    event = _event(db, event_id, staff, write=True)
    data = data or {}
    for key, col in (("areas_locked", "areas_config_locked"), ("inventory_locked", "inventory_config_locked")):
        if key in data:
            if not isinstance(data[key], bool):
                raise HTTPException(status_code=400, detail=f"{key} debe ser verdadero o falso")
            setattr(event, col, data[key])
    if data.get("clear_password") is True:
        config_lock.clear_password(event)
    elif data.get("password") not in (None, ""):
        try:
            config_lock.set_password(event, data["password"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    from app import audit_actions
    audit_actions.record(db, staff, "update", "event_config_lock", event.id, event.name,
                         f"zonas {'bloqueadas' if event.areas_config_locked else 'libres'}, inventario {'bloqueado' if event.inventory_config_locked else 'libre'}, contraseña {'definida' if event.config_unlock_hash else 'sin definir'}")
    db.commit()
    return config_lock.admin_state(db, event)


@router.post("/events/{event_id}/config-lock/unlock")
def unlock_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """El digitador escribe la contraseña para cambiar la configuración bloqueada de su pantalla. Cinco intentos fallidos = 5 minutos de espera."""
    event = _event(db, event_id, staff)
    scope = str((data or {}).get("scope") or "")
    if scope not in config_lock.SCOPES:
        raise HTTPException(status_code=400, detail="Pantalla no válida")
    if not config_lock.locked(db, event, scope, effective_roles(staff)):
        return {"ok": True, "locked": False}
    problem = config_lock.check(event, staff.id, (data or {}).get("password"))
    if problem:
        raise HTTPException(status_code=403, detail=problem)
    return {"ok": True}
