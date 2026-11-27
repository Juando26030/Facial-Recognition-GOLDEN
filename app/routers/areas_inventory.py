"""Control de Áreas y Control de Inventario (reunión 2026-09-21, ítem 9) — funcionalidad genérica por
evento, cada módulo con su switch en Parámetros del Evento.

Áreas: zonas del evento; entrada/salida por cédula/QR (el QR trae el ID) o reconocimiento facial, con el
mismo patrón que el Registro: con "Modo autoregistro" ON el match guarda el movimiento solo; OFF pide
confirmar ("Acreditar"). Por zona, "permitir reingresos"; apagado = solo una entrada por persona (alerta roja).

Inventario: ítems con cantidad inicial; se entregan uno o varios a la vez (combos) a una persona y el
disponible se descuenta solo (disponible = inicial - entregado)."""
import io
import uuid
from datetime import datetime
from app.timeutil import utcnow

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_event_in_progress, require_role, require_role_excluding
from app import area_dwell_svc, audit_actions, event_history, faces, heavy, person_code, subcat
from app import event_archive
from app.database import get_db
from app.timeutil import to_local
from app.models import (
    AreaMovement, EventArea, EventAttendee, EventInventoryItem, InventoryDelivery, InventoryItem, StaffUser, User,
)

router = APIRouter()

CONFIG_ROLE = require_role_excluding("coordinador", ("comercial",))  # define zonas/ítems y baja reportes
OPERATE_ROLE = require_role_excluding("digitador", ("comercial",))  # registra movimientos / entregas
ARCHIVE_ROLE = require_role("coordinador")    # Fase 3 (cambio 7-nov): archivar y restaurar zonas / ítems = coordinador+ (incluye comercial)
HARD_DELETE_ROLE = require_role("super_admin")  # borrado definitivo: solo super_admin, de algo ya archivado y sin historial


def _only_active(query, model, include_archived: bool, staff: StaffUser):
    """Por defecto SOLO los activos; `include_archived=true` es de coordinador+ (pantalla «Ver archivados»)."""
    if include_archived:
        if staff.role not in ("coordinador", "comercial", "admin", "super_admin"):
            raise HTTPException(status_code=403, detail="No tienes permiso para ver los archivados")
        return query
    return query.filter(model.archived_at.is_(None))


def delete_event_modules(db: Session, event_id: int) -> None:
    """Borra los datos de Áreas/Inventario de un evento (lo usa delete_event)."""
    db.query(AreaMovement).filter(AreaMovement.event_id == event_id).delete()
    db.query(EventArea).filter(EventArea.event_id == event_id).delete()
    db.query(InventoryDelivery).filter(InventoryDelivery.event_id == event_id).delete()
    db.query(InventoryItem).filter(InventoryItem.event_id == event_id).delete()
    db.query(EventInventoryItem).filter(EventInventoryItem.event_id == event_id).delete()          # Fase 5: líneas del catálogo de inventario
    from app.models import EventDependent
    db.query(EventDependent).filter(EventDependent.event_id == event_id).delete()          # 0161: base de dependientes


@router.put("/events/{event_id}/modules")
def set_modules(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Switches por evento: `areas_enabled` / `inventory_enabled` (solo se cambian los que vengan)."""
    event = get_event_for_staff(event_id, db, staff)
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    if "areas_enabled" in data:
        event.areas_enabled = bool(data["areas_enabled"])
    if "inventory_enabled" in data:
        event.inventory_enabled = bool(data["inventory_enabled"])
    if "code_enabled" in data:          # 0140: el evento usa «código» (serial del QR distinto de la cédula)
        event.code_enabled = bool(data["code_enabled"])
    if "code_required" in data:
        event.code_required = bool(data["code_required"])
    # 0169 (26-nov-2026): cómo se busca a la persona en CADA pantalla. Las claves viejas (0166/0168) aplican a las tres, por compatibilidad.
    legacy = None
    if data.get("code_search_only"):
        legacy = "code_only"
    elif data.get("code_search_first"):
        legacy = "code_first"
    elif "code_search_first" in data or "code_search_only" in data:
        legacy = "id_first"
    for module, column in person_code.MODULES.items():
        mode = data.get(column, legacy)
        if mode is None:
            continue
        if mode not in person_code.SEARCH_MODES:
            raise HTTPException(status_code=400, detail="Modo de búsqueda no válido")
        setattr(event, column, mode)
    if not event.code_enabled:
        for column in person_code.MODULES.values():
            setattr(event, column, "id_first")
    if event.code_required and not event.code_enabled:
        raise HTTPException(status_code=400, detail="Para hacer el código obligatorio primero activa «Usar código»")
    _hr = event_history.record(db, event, _hb, staff, "switch")
    db.commit()
    event_history.kick_after(_hr)
    return {"areas_enabled": event.areas_enabled, "inventory_enabled": event.inventory_enabled, "code_enabled": event.code_enabled, "code_required": event.code_required, **{column: getattr(event, column) for column in person_code.MODULES.values()}}


def _person_data(user: User) -> dict:
    return {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "entity": user.entity, "opt_1": user.opt_1}


def _find_person(db: Session, event, cedula: str, module: str) -> User:
    """La persona debe estar en la base de ESTE evento (no cualquier persona del cliente). `module` = 'inventario' | 'zonas' (0169: cada pantalla con su modo de búsqueda)."""
    user, _via = person_code.find_user(db, event, cedula, module)
    in_event = user and db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
    if not in_event:
        raise HTTPException(status_code=404, detail="Esa persona no está en la base de este evento")
    return user


# ---------------------------------------------------------------------------------------- Áreas

def _area_json(db: Session, a: EventArea) -> dict:
    """Una zona (o un grupo: cuenta lo de todas sus subcategorías; «adentro» = personas cuya última marca en alguna subcategoría es una entrada)."""
    is_group = subcat.has_children(db, EventArea, a.id)
    ids = subcat.group_ids(db, EventArea, a) if is_group else [a.id]
    last_by_pair = {}
    for m in db.query(AreaMovement).filter(AreaMovement.area_id.in_(ids)).order_by(AreaMovement.timestamp, AreaMovement.id):
        last_by_pair[(m.area_id, m.user_id)] = m.direction
    inside = {u for (_a, u), d in last_by_pair.items() if d == "in"}
    visited = {u for (_a, u) in last_by_pair}
    return {
        "id": a.id, "name": a.name, "allow_reentry": a.allow_reentry,
        "inside": len(inside), "visited": len(visited),
        "archived": a.archived_at is not None,
        "parent_id": a.parent_id, "stats_enabled": bool(a.stats_enabled), "max_per_person": a.max_per_person, "is_group": is_group,
    }


def _get_area(db: Session, event, area_id: int, *, active_only: bool = False) -> EventArea:
    area = db.query(EventArea).filter(EventArea.id == area_id, EventArea.event_id == event.id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    if active_only and area.archived_at is not None:
        raise HTTPException(status_code=400, detail="La zona está archivada: restáurala para usarla")
    return area


@router.get("/events/{event_id}/areas")
def list_areas(event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    query = _only_active(db.query(EventArea).filter(EventArea.event_id == event.id), EventArea, include_archived, staff)
    return [_area_json(db, a) for a in query.order_by(EventArea.id)]


@router.post("/events/{event_id}/areas")
def create_area(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="La zona necesita un nombre")
    if db.query(EventArea).filter(EventArea.event_id == event.id, func.lower(EventArea.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="Ya existe una zona con ese nombre en este evento (si no la ves, está archivada: restáurala)")
    try:
        parent = subcat.validate_parent(db, EventArea, event.id, data.get("parent_id"))
        limit = subcat.clean_limit(data.get("max_per_person"))
    except subcat.SubcatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if parent is not None and db.query(AreaMovement.id).filter(AreaMovement.area_id == parent.id).first():
        raise HTTPException(status_code=400, detail="«%s» ya tiene movimientos registrados: no se le pueden agregar subcategorías (créala como zona nueva)" % parent.name)
    area = EventArea(event_id=event.id, name=name, allow_reentry=bool(data.get("allow_reentry", True)), created_at=utcnow(),
                     parent_id=parent.id if parent else None, stats_enabled=bool(data.get("stats_enabled", True)), max_per_person=limit)
    db.add(area)
    db.commit()
    return _area_json(db, area)


@router.patch("/events/{event_id}/areas/{area_id}")
def update_area(event_id: int, area_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    area = _get_area(db, event, area_id, active_only=True)
    if "name" in data and str(data["name"]).strip():
        area.name = str(data["name"]).strip()
    if "allow_reentry" in data:
        area.allow_reentry = bool(data["allow_reentry"])
    if "stats_enabled" in data:
        area.stats_enabled = bool(data["stats_enabled"])
    try:
        if "max_per_person" in data:
            area.max_per_person = subcat.clean_limit(data["max_per_person"])
        if "parent_id" in data:
            parent = subcat.validate_parent(db, EventArea, event.id, data["parent_id"], self_row=area)
            new_pid = parent.id if parent else None
            if new_pid != area.parent_id:
                if db.query(AreaMovement.id).filter(AreaMovement.area_id.in_([area.id] + ([new_pid] if new_pid else []))).first():
                    raise subcat.SubcatError("No se puede mover una zona con movimientos registrados (ni dentro de una con movimientos): crea una nueva")
                area.parent_id = new_pid
    except subcat.SubcatError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return _area_json(db, area)


@router.post("/events/{event_id}/areas/{area_id}/archive")
def archive_area(event_id: int, area_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    """Archivar = ocultar la zona (ya no se elige ni recibe movimientos). Los movimientos registrados y el reporte se conservan; un coordinador o superior la restaura."""
    area = _get_area(db, get_event_for_staff(event_id, db, staff), area_id)
    if area.archived_at is not None:
        raise HTTPException(status_code=400, detail="La zona ya está archivada")
    area.archived_at, area.archived_by_id = utcnow(), staff.id
    for child in subcat.active_children(db, EventArea, area.id):          # archivar un grupo archiva sus subcategorías
        child.archived_at, child.archived_by_id = area.archived_at, staff.id
    audit_actions.record(db, staff, "archive", "event_area", area.id, area.name, f"evento {area.event_id}")
    db.commit()
    return _area_json(db, area)


@router.post("/events/{event_id}/areas/{area_id}/restore")
def restore_area(event_id: int, area_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    area = _get_area(db, get_event_for_staff(event_id, db, staff), area_id)
    if area.archived_at is None:
        raise HTTPException(status_code=400, detail="La zona no está archivada")
    if area.parent_id:
        parent = db.get(EventArea, area.parent_id)
        if parent is not None and parent.archived_at is not None:
            raise HTTPException(status_code=400, detail="Primero restaura la zona principal «%s»" % parent.name)
    area.archived_at, area.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "event_area", area.id, area.name, f"evento {area.event_id}")
    db.commit()
    return _area_json(db, area)


@router.delete("/events/{event_id}/areas/{area_id}")
def delete_area(event_id: int, area_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(HARD_DELETE_ROLE)):
    """Borrado DEFINITIVO: solo super_admin, de una zona ya archivada y SIN movimientos (con historial solo se archiva)."""
    area = _get_area(db, get_event_for_staff(event_id, db, staff), area_id)
    if area.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva la zona; el borrado definitivo solo aplica a zonas archivadas")
    if subcat.has_children(db, EventArea, area.id):
        raise HTTPException(status_code=400, detail="La zona tiene subcategorías: bórralas primero")
    if db.query(AreaMovement).filter(AreaMovement.area_id == area.id).first():
        raise HTTPException(status_code=400, detail="La zona tiene movimientos registrados: se conserva archivada (el historial no se borra)")
    audit_actions.record(db, staff, "delete", "event_area", area.id, area.name, f"evento {area.event_id}")
    db.delete(area)
    db.commit()
    return {"message": "Zona eliminada"}


def _client_time(raw):
    """Hora real de un movimiento hecho SIN RED y enviado al volver la conexión (docs/28): ISO en UTC. Solo vale si no es futura ni tiene más de 7 días (lo que dura la bandeja del quiosco); si no, None (= ahora)."""
    try:
        when = datetime.fromisoformat(str(raw or "").strip().replace("Z", "")[:26])
    except ValueError:
        return None
    if when.tzinfo is not None:
        return None
    now = utcnow()
    return when if (now - when).total_seconds() >= 0 and (now - when).days < 7 else None


def _apply_movement(db: Session, event, area: EventArea, user: User, direction: str, confirm: bool, method: str, staff: StaffUser, when=None) -> dict:
    """Reglas de una entrada/salida. Devuelve el resultado (nunca lanza por reglas de negocio):
    OK (guardado) | FOUND_PENDING (autoregistro apagado y sin confirmar) | ALREADY_ENTERED (alerta roja:
    reingreso no permitido) | NOT_INSIDE (salida de alguien que no está adentro) | LIMIT (pasó el máximo de entradas por persona).
    Subcategorías (0140): la zona principal MANDA: si no permite reingresos, entrar por A bloquea B; si lo permite, A y luego B son dos entradas al grupo."""
    group = subcat.has_children(db, EventArea, area.id)
    if group:
        raise HTTPException(status_code=400, detail="«%s» tiene subcategorías: elige una de ellas" % area.name)
    parent = db.get(EventArea, area.parent_id) if area.parent_id else None
    if parent is not None and parent.archived_at is not None:
        raise HTTPException(status_code=400, detail="La zona principal «%s» está archivada: restáurala para usarla" % parent.name)
    if parent is not None:
        # turno por persona: las filas del grupo se bloquean en orden de id (dos puestos escaneando a la misma persona se esperan)
        locked = subcat.lock_rows(db, EventArea, [parent.id] + [a.id for a in subcat.active_children(db, EventArea, parent.id)])
    else:
        locked = {}
    last = db.query(AreaMovement).filter(AreaMovement.area_id == area.id, AreaMovement.user_id == user.id) \
        .order_by(AreaMovement.timestamp.desc(), AreaMovement.id.desc()).first()
    if direction == "auto":
        direction = "out" if (last and last.direction == "in") else "in"
    if direction not in ("in", "out"):
        raise HTTPException(status_code=400, detail="direction debe ser in, out o auto")
    data = _person_data(user)
    who = f"{user.first_name or ''} {user.last_name or ''}".strip()
    label = f"{parent.name}{subcat.SEP}{area.name}" if parent is not None else area.name

    if direction == "in":
        member_ids = [parent.id] + [a.id for a in locked.values() if a.parent_id == parent.id] if parent is not None else [area.id]
        no_reentry_group = parent is not None and not parent.allow_reentry
        if no_reentry_group or not area.allow_reentry:
            scope = member_ids if no_reentry_group else [area.id]
            already = db.query(AreaMovement.id).filter(
                AreaMovement.area_id.in_(scope), AreaMovement.user_id == user.id, AreaMovement.direction == "in").first()
            if already:
                where = parent.name if no_reentry_group else area.name
                return {"result": "ALREADY_ENTERED", "direction": "in", "area": label, "data": data,
                        "details": f"{who} YA había entrado a «{where}» y esta zona no permite reingresos"}
        problem = subcat.area_limit_problem(db, area, locked, user.id)
        if problem:
            return {"result": "LIMIT", "direction": "in", "area": label, "data": data, "details": f"{who}: {problem}"}
        from app import node_precheck
        if (no_reentry_group or not area.allow_reentry) and node_precheck.enabled(event):          # 0161: evento compartido: ¿ya entró por otro puesto?
            names = [parent.name] + [a.name for a in locked.values() if a.parent_id == parent.id] if no_reentry_group else [area.name]
            ans = node_precheck.ask(event, user.id, areas=names)
            if ans and any((ans.get("areas") or {}).get(n.strip().lower()) for n in names):
                where = parent.name if no_reentry_group else area.name
                return {"result": "ALREADY_ENTERED", "direction": "in", "area": label, "data": data,
                        "details": f"{who} YA había entrado a «{where}» por otro puesto y esta zona no permite reingresos"}
    if direction == "out" and not (last and last.direction == "in"):
        return {"result": "NOT_INSIDE", "direction": "out", "area": label, "data": data,
                "details": f"{who} no figura adentro de «{label}»"}

    if not event.auto_register and not event.areas_autoscan and not confirm:          # Fase 10: «escanear = ingreso automático» registra sin pulsar «Acreditar»
        return {"result": "FOUND_PENDING", "direction": direction, "area": label, "data": data}

    now = when or utcnow()
    db.add(AreaMovement(
        event_id=event.id, area_id=area.id, user_id=user.id, tenant_id=event.tenant_id, direction=direction,
        method=method, timestamp=now, registered_by_staff_id=staff.id,
    ))
    db.commit()
    return {"result": "OK", "direction": direction, "area": label, "data": data, "time": now.isoformat()}


@router.post("/events/{event_id}/areas/{area_id}/movement")
def area_movement(event_id: int, area_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Entrada/salida por cédula o QR (el QR trae el ID). `direction`: in | out | auto (alterna)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    require_event_in_progress(event)
    area = _get_area(db, event, area_id, active_only=True)
    user = _find_person(db, event, str(data.get("cedula") or ""), "zonas")
    return _apply_movement(db, event, area, user, data.get("direction", "auto"), bool(data.get("confirm")), "qr" if data.get("method") == "qr" else "cedula", staff,
                           when=_client_time(data.get("client_time")) if data.get("client_time") else None)


@router.post("/events/{event_id}/areas/{area_id}/movement-face")
def area_movement_face(
    event_id: int, area_id: int, file: UploadFile = File(...), direction: str = Form("auto"), confirm: bool = Form(False),
    db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE),
):
    """Entrada/salida por reconocimiento facial (solo eventos con biometría)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    require_event_in_progress(event)
    area = _get_area(db, event, area_id, active_only=True)
    try:
        status, uid = faces.identify(db, event, file.file.read())
    except faces.Busy:
        raise HTTPException(status_code=503, detail="Hay muchos escaneos en cola. Intenta de nuevo en unos segundos.", headers={"Retry-After": "3"})
    if status == "NO_FACE":
        return {"result": "NO", "details": "Rostro no detectado"}
    user = db.get(User, (uid, event.tenant_id)) if uid else None
    if user:
        return _apply_movement(db, event, area, user, direction, confirm, "facial", staff)
    return {"result": "NO", "details": "Ninguna persona de este evento coincide"}


@router.get("/events/{event_id}/areas/{area_id}/presence")
def area_presence(event_id: int, area_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Última situación de cada persona en la zona: verde = entró ('in'), rojo = salió ('out')."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    area = _get_area(db, event, area_id)
    ids = subcat.group_ids(db, EventArea, area) if subcat.has_children(db, EventArea, area.id) else [area.id]          # un grupo muestra a todos los de sus subcategorías
    last = {}
    for m in db.query(AreaMovement).filter(AreaMovement.area_id.in_(ids)).order_by(AreaMovement.timestamp, AreaMovement.id):
        last[m.user_id] = m
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(list(last.keys()) or [""])).all()}
    rows = [{
        "id": uid, "name": f"{users[uid].first_name or ''} {users[uid].last_name or ''}".strip(),
        "direction": m.direction, "time": m.timestamp.isoformat(),
    } for uid, m in last.items() if uid in users]
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


@router.get("/events/{event_id}/areas/movements/person")
def person_movements(event_id: int, cedula: str, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """26-nov-2026 (Juan David): historial COMPLETO de entradas y salidas de UNA persona en todas las zonas (buscador de «Personas en la zona»;
    solo coordinador en adelante, igual que el historial de Inventario). Quién registró va por su nombre de cuenta, nunca su usuario (es su cédula)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    user = _find_person(db, event, cedula, "zonas")
    area_rows = {a.id: a for a in db.query(EventArea).filter(EventArea.event_id == event.id)}
    rows = (db.query(AreaMovement).filter(AreaMovement.event_id == event.id, AreaMovement.user_id == user.id)
            .order_by(AreaMovement.timestamp.desc(), AreaMovement.id.desc()).all())
    sids = {r.registered_by_staff_id for r in rows if r.registered_by_staff_id}
    names = {sid: ((n or "").strip() or "Personal del evento") for sid, n in db.query(StaffUser.id, StaffUser.full_name).filter(StaffUser.id.in_(sids))} if sids else {}
    return {"person": {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "code": person_code.code_of(db, event, user.id) or ""},
            "movements": [{"time": r.timestamp.isoformat(), "area": subcat.label_of(area_rows, area_rows[r.area_id]) if r.area_id in area_rows else "",
                           "direction": r.direction, "by": names.get(r.registered_by_staff_id, "")} for r in rows]}


def _xlsx_response(sheets: dict, filename: str, widths: dict = None) -> StreamingResponse:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df in sheets.items():
            heavy.safe_frame(df).to_excel(writer, index=False, sheet_name=name)
            ws = writer.sheets[name]
            for cell in ws[1]:
                cell.fill = PatternFill(start_color="0A0E2E", end_color="0A0E2E", fill_type="solid")
                cell.font = Font(color="FFFFFF", bold=True)
            for idx, col in enumerate(df.columns, start=1):
                longest = max([len(str(col))] + [len(str(v)) for v in df[col]])
                ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(longest + 3, 45)
            ws.auto_filter.ref = ws.dimensions
            ws.freeze_panes = "A2"
    out.seek(0)
    return StreamingResponse(
        out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": heavy.content_disposition(filename)},
    )


@router.get("/events/{event_id}/areas-report")
def areas_report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Todos los movimientos con hora EXACTA (con segundos) y zona."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    area_rows = {a.id: a for a in db.query(EventArea).filter(EventArea.event_id == event.id)}
    areas = {i: subcat.label_of(area_rows, a) for i, a in area_rows.items()}          # «Salón A › Entrada A»
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id)}
    staff_names = {s.id: (s.full_name or s.username) for s in db.query(StaffUser)}
    rows = []
    for m in db.query(AreaMovement).filter(AreaMovement.event_id == event.id).order_by(AreaMovement.timestamp, AreaMovement.id):
        u = users.get(m.user_id)
        rows.append([
            to_local(m.timestamp).strftime("%Y-%m-%d"), to_local(m.timestamp).strftime("%H:%M:%S"), areas.get(m.area_id, ""), m.user_id,
            f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "", "Entrada" if m.direction == "in" else "Salida",
            m.method or "", staff_names.get(m.registered_by_staff_id, ""),
        ])
    df = pd.DataFrame(rows, columns=["Fecha", "Hora", "Zona", "Cédula", "Persona", "Movimiento", "Método", "Registrado por"])
    return _xlsx_response({"Movimientos por zona": df}, heavy.event_report_filename(event, "Reporte de áreas"))


# ------------------------------------------------------------------------------------ Inventario

def _delivered_by_item(db: Session, event_id: int) -> dict:
    rows = db.query(InventoryDelivery.item_id, func.sum(InventoryDelivery.qty)).filter(InventoryDelivery.event_id == event_id).group_by(InventoryDelivery.item_id).all()
    return {item_id: int(total or 0) for item_id, total in rows}


def _item_json(item: InventoryItem, delivered: int, children: list = None, delivered_map: dict = None) -> dict:
    """`children` (lista de InventoryItem) = es un grupo: lo entregado y lo disponible suman el de sus subcategorías."""
    is_group = bool(children)
    if is_group:
        dm = delivered_map or {}
        delivered = sum(dm.get(c.id, 0) for c in children) + delivered
        available = sum(c.initial_qty - dm.get(c.id, 0) for c in children if c.archived_at is None)
        initial = sum(c.initial_qty for c in children if c.archived_at is None)
    else:
        available, initial = item.initial_qty - delivered, item.initial_qty
    return {
        "id": item.id, "name": item.name, "initial_qty": initial, "allow_multiple": item.allow_multiple,
        "allow_repeat_delivery": item.allow_repeat_delivery is not False, "requires_dwell": bool(item.requires_dwell),
        "delivered": delivered, "available": available, "archived": item.archived_at is not None,
        "parent_id": item.parent_id, "stats_enabled": bool(item.stats_enabled), "max_per_person": item.max_per_person, "is_group": is_group,
    }


def _children_map(db: Session, event_id: int) -> dict:
    out = {}
    for i in db.query(InventoryItem).filter(InventoryItem.event_id == event_id, InventoryItem.parent_id.isnot(None)).order_by(InventoryItem.id):
        out.setdefault(i.parent_id, []).append(i)
    return out


def _get_item(db: Session, event, item_id: int, *, active_only: bool = False) -> InventoryItem:
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.event_id == event.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")
    if active_only and item.archived_at is not None:
        raise HTTPException(status_code=400, detail="El ítem está archivado: restáuralo para usarlo")
    return item


def multi_units_allowed(item, parent) -> bool:
    """¿Se pueden entregar varias unidades de este ítem en una misma entrega? 19-nov-2026: sí si lo marcaron «varias unidades a la vez»; si no, lo decide el límite: con «Máx. por persona» propio mayor que 1 sí
    (con 1, no), y sin límite propio, sí cuando el grupo permite más de 1 en total (el grupo igual manda: la suma de todas sus opciones no pasa de su máximo)."""
    if item.allow_multiple:
        return True
    if item.max_per_person is not None:
        return item.max_per_person > 1
    return parent is not None and parent.max_per_person is not None and parent.max_per_person > 1


def missing_required_choice(db: Session, event_id: int, user_id: str, wanted: dict, delivered: dict) -> str:
    """19-nov-2026: un grupo con «Máx. por persona = 1» es de ELEGIR UNA (ni dos ni ninguna): si la persona todavía no recibió nada del grupo y quedan opciones con disponible, la entrega debe traer una.
    Devuelve el mensaje del primer grupo sin elegir, o «» si todo está bien. (Más de 1 unidad ya lo frena subcat.inventory_limit_problem.)"""
    groups = db.query(InventoryItem).filter(InventoryItem.event_id == event_id, InventoryItem.archived_at.is_(None), InventoryItem.max_per_person == 1, InventoryItem.parent_id.is_(None)).order_by(InventoryItem.id).all()
    for g in groups:
        kids = [c for c in db.query(InventoryItem).filter(InventoryItem.parent_id == g.id, InventoryItem.archived_at.is_(None)).order_by(InventoryItem.id)]
        if not kids or not any(c.initial_qty - delivered.get(c.id, 0) > 0 for c in kids):
            continue
        if any(c.id in wanted for c in kids):
            continue
        if subcat.units_of(db, event_id, [g.id] + [c.id for c in kids], user_id) >= 1:
            continue
        return f"Elige una opción de «{g.name}» (es obligatorio elegir una): " + ", ".join(c.name for c in kids if c.initial_qty - delivered.get(c.id, 0) > 0)
    return ""


def _qty(value, minimum: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="La cantidad debe ser un número entero")
    if n < minimum:
        raise HTTPException(status_code=400, detail=f"La cantidad debe ser {minimum} o más")
    return n


@router.get("/events/{event_id}/inventory")
def list_inventory(event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    delivered = _delivered_by_item(db, event.id)
    query = _only_active(db.query(InventoryItem).filter(InventoryItem.event_id == event.id), InventoryItem, include_archived, staff)
    kids = _children_map(db, event.id)
    return [_item_json(i, delivered.get(i.id, 0), kids.get(i.id), delivered) for i in query.order_by(InventoryItem.id)]


@router.post("/events/{event_id}/inventory")
def create_item(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El ítem necesita un nombre")
    if db.query(InventoryItem).filter(InventoryItem.event_id == event.id, func.lower(InventoryItem.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="Ya existe un ítem con ese nombre en este evento (si no lo ves, está archivado: restáuralo)")
    try:
        parent = subcat.validate_parent(db, InventoryItem, event.id, data.get("parent_id"))
        limit = subcat.clean_limit(data.get("max_per_person"))
    except subcat.SubcatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if parent is not None and db.query(InventoryDelivery.id).filter(InventoryDelivery.item_id == parent.id).first():
        raise HTTPException(status_code=400, detail="«%s» ya tiene entregas registradas: no se le pueden agregar subcategorías (créala como ítem nuevo)" % parent.name)
    item = InventoryItem(event_id=event.id, name=name, initial_qty=_qty(data.get("initial_qty", 0)), allow_multiple=bool(data.get("allow_multiple")),
                         parent_id=parent.id if parent else None, stats_enabled=bool(data.get("stats_enabled", True)), max_per_person=limit,
                         allow_repeat_delivery=bool(data.get("allow_repeat_delivery", False)), requires_dwell=bool(data.get("requires_dwell", False)), created_at=utcnow())      # D7: los ítems NUEVOS no repiten la entrega a la misma persona salvo que se pida
    db.add(item)
    db.commit()
    return _item_json(item, 0)


@router.patch("/events/{event_id}/inventory/{item_id}")
def update_item(event_id: int, item_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    item = _get_item(db, event, item_id, active_only=True)
    delivered = _delivered_by_item(db, event.id).get(item.id, 0)
    if "name" in data and str(data["name"]).strip():
        item.name = str(data["name"]).strip()
    if "initial_qty" in data:
        new_qty = _qty(data["initial_qty"])
        if new_qty < delivered:
            raise HTTPException(status_code=400, detail=f"Ya se entregaron {delivered}: la cantidad inicial no puede ser menor")
        item.initial_qty = new_qty
    if "allow_multiple" in data:
        item.allow_multiple = bool(data["allow_multiple"])
    if "allow_repeat_delivery" in data:
        if bool(data["allow_repeat_delivery"]) != bool(item.allow_repeat_delivery):
            audit_actions.record(db, staff, "update", "inventory_item", item.id, item.name,
                                 f"allow_repeat_delivery {bool(item.allow_repeat_delivery)} -> {bool(data['allow_repeat_delivery'])}; evento {item.event_id}")
        item.allow_repeat_delivery = bool(data["allow_repeat_delivery"])
    if "requires_dwell" in data:          # Fase 10: solo se entrega a quien llegó al porcentaje de estadía del evento
        item.requires_dwell = bool(data["requires_dwell"])
    if "stats_enabled" in data:
        item.stats_enabled = bool(data["stats_enabled"])
    try:
        if "max_per_person" in data:
            item.max_per_person = subcat.clean_limit(data["max_per_person"])
        if "parent_id" in data:
            parent = subcat.validate_parent(db, InventoryItem, event.id, data["parent_id"], self_row=item)
            new_pid = parent.id if parent else None
            if new_pid != item.parent_id:
                if db.query(InventoryDelivery.id).filter(InventoryDelivery.item_id.in_([item.id] + ([new_pid] if new_pid else []))).first():
                    raise subcat.SubcatError("No se puede mover un ítem con entregas registradas (ni dentro de uno con entregas): crea uno nuevo")
                item.parent_id = new_pid
    except subcat.SubcatError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    kids = subcat.active_children(db, InventoryItem, item.id)
    return _item_json(item, delivered, kids, _delivered_by_item(db, event.id))


@router.post("/events/{event_id}/inventory/{item_id}/archive")
def archive_item(event_id: int, item_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    """Archivar = ocultar el ítem (ya no se entrega). Las entregas hechas y el reporte se conservan; un coordinador o superior lo restaura."""
    item = _get_item(db, get_event_for_staff(event_id, db, staff), item_id)
    if item.archived_at is not None:
        raise HTTPException(status_code=400, detail="El ítem ya está archivado")
    item.archived_at, item.archived_by_id = utcnow(), staff.id
    for child in subcat.active_children(db, InventoryItem, item.id):          # archivar un grupo archiva sus subcategorías
        child.archived_at, child.archived_by_id = item.archived_at, staff.id
    audit_actions.record(db, staff, "archive", "inventory_item", item.id, item.name, f"evento {item.event_id}")
    db.commit()
    return _item_json(item, _delivered_by_item(db, item.event_id).get(item.id, 0))


@router.post("/events/{event_id}/inventory/{item_id}/restore")
def restore_item(event_id: int, item_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    item = _get_item(db, get_event_for_staff(event_id, db, staff), item_id)
    if item.archived_at is None:
        raise HTTPException(status_code=400, detail="El ítem no está archivado")
    if item.parent_id:
        parent = db.get(InventoryItem, item.parent_id)
        if parent is not None and parent.archived_at is not None:
            raise HTTPException(status_code=400, detail="Primero restaura el ítem principal «%s»" % parent.name)
    item.archived_at, item.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "inventory_item", item.id, item.name, f"evento {item.event_id}")
    db.commit()
    return _item_json(item, _delivered_by_item(db, item.event_id).get(item.id, 0))


@router.delete("/events/{event_id}/inventory/{item_id}")
def delete_item(event_id: int, item_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(HARD_DELETE_ROLE)):
    """Borrado DEFINITIVO: solo super_admin, de un ítem ya archivado y SIN entregas (con entregas solo se archiva)."""
    event = get_event_for_staff(event_id, db, staff)
    item = _get_item(db, event, item_id)
    if item.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el ítem; el borrado definitivo solo aplica a ítems archivados")
    if subcat.has_children(db, InventoryItem, item.id):
        raise HTTPException(status_code=400, detail="El ítem tiene subcategorías: bórralas primero")
    if db.query(InventoryDelivery).filter(InventoryDelivery.item_id == item.id).first():
        raise HTTPException(status_code=400, detail="Este ítem ya tiene entregas registradas: se conserva archivado (el historial no se borra)")
    audit_actions.record(db, staff, "delete", "inventory_item", item.id, item.name, f"evento {item.event_id}")
    db.delete(item)
    db.commit()
    return {"message": "Ítem eliminado"}


@router.post("/events/{event_id}/inventory/deliver")
def deliver(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    """Entrega uno o varios ítems (combo) a una persona: `{cedula, items: [{item_id, qty}]}`. Todo o
    nada: si algún ítem no alcanza, no se entrega nada. El disponible se descuenta solo."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    require_event_in_progress(event)
    from app import inv_assign, node_precheck
    if inv_assign.is_assigned(event):          # 0161: con «La base lo define» no se elige: se entrega lo asignado (/inventory/deliver-assigned)
        raise HTTPException(status_code=400, detail=inv_assign.MODE_BLOCKS_CHOOSE)
    user = _find_person(db, event, str(data.get("cedula") or ""), "inventario")
    lines = data.get("items") or []
    if not lines:
        raise HTTPException(status_code=400, detail="Elige al menos un ítem para entregar")

    wanted = {}
    for line in lines:
        try:
            item_id = int(line.get("item_id"))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Uno de los ítems no es válido")
        wanted[item_id] = wanted.get(item_id, 0) + _qty(line.get("qty", 1), minimum=1)

    # Con lock de fila: dos digitadores entregando el último ítem a la vez no lo pueden vender dos veces.
    items = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.event_id == event.id, InventoryItem.id.in_(list(wanted))).order_by(InventoryItem.id).with_for_update().all()}
    # Subcategorías (0140): se bloquean también el grupo y sus hermanas (en orden de id) para que el límite por persona del grupo no se pase con dos puestos a la vez
    group_rows = {}
    parent_ids = {i.parent_id for i in items.values() if i.parent_id}
    if parent_ids:
        family = set(parent_ids) | {cid for (cid,) in db.query(InventoryItem.id).filter(InventoryItem.parent_id.in_(list(parent_ids)))}
        group_rows = subcat.lock_rows(db, InventoryItem, list(family))
        items.update({k: v for k, v in group_rows.items() if k in wanted})
    delivered = _delivered_by_item(db, event.id)
    # D7: «Permitir repetir la entrega a la misma persona» apagado -> un segundo intento para la misma persona e ítem es 409. Se comprueba con los ítems YA bloqueados
    # (FOR UPDATE): dos digitadores (o un doble clic) entregando el mismo ítem a la misma persona se turnan en ese candado y el segundo ve la entrega del primero.
    already = {r[0] for r in db.query(InventoryDelivery.item_id).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.user_id == user.id, InventoryDelivery.item_id.in_(list(wanted))).distinct()}
    for item_id, qty in wanted.items():
        item = items.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Uno de los ítems no existe en este evento")
        if item.archived_at is not None:
            raise HTTPException(status_code=400, detail=f"«{item.name}» está archivado: restáuralo para entregarlo")
        if subcat.has_children(db, InventoryItem, item.id):
            raise HTTPException(status_code=400, detail=f"«{item.name}» tiene subcategorías: elige cuál se entrega")
        if item.parent_id and group_rows.get(item.parent_id) is not None and group_rows[item.parent_id].archived_at is not None:
            raise HTTPException(status_code=400, detail=f"«{group_rows[item.parent_id].name}» está archivado: restáuralo para entregar «{item.name}»")
        # Hotfix 26-nov-2026: primero el límite por persona (el del grupo manda): así el motivo dice QUÉ recibió («ya recibió «Alimentación»: Mazorcada Corferias») antes que la regla de no repetir o las existencias.
        problem = subcat.inventory_limit_problem(db, event.id, item, qty, group_rows, user.id, {k: v for k, v in wanted.items() if k != item_id})
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        if item_id in already and item.allow_repeat_delivery is False:
            raise HTTPException(status_code=409, detail=f"Esta persona ya recibió «{item.name}» y no se le puede entregar otra vez. Si fue un error, un coordinador puede activar «Permitir repetir la entrega» en Parámetros.")
        if item.requires_dwell and area_dwell_svc.prize_active(event) and not area_dwell_svc.qualifies(db, event, user.id):
            raise HTTPException(status_code=409, detail=f"«{item.name}» solo se entrega a quien cumplió el {area_dwell_svc.threshold(event)} % de permanencia del evento y esta persona todavía no lo alcanza")
        if qty > 1 and not multi_units_allowed(item, group_rows.get(item.parent_id) if item.parent_id else None):
            raise HTTPException(status_code=400, detail=f"«{item.name}» solo se entrega de a 1 unidad por vez")
        available = item.initial_qty - delivered.get(item_id, 0)
        if qty > available:
            raise HTTPException(status_code=400, detail=f"No alcanza «{item.name}»: quedan {available} y se pidieron {qty}")

    missing = missing_required_choice(db, event.id, user.id, wanted, delivered)
    if missing:
        raise HTTPException(status_code=400, detail=missing)
    warning = ""
    no_repeat = [items[i].name for i in wanted if items[i].allow_repeat_delivery is False and i not in already]
    if no_repeat and node_precheck.enabled(event):          # 0161: evento compartido en un servidor local: ¿otro puesto ya se lo entregó?
        ans = node_precheck.ask(event, user.id, items=no_repeat)
        if ans is None:
            warning = node_precheck.OFFLINE_WARNING
        else:
            hit = next((n for n in no_repeat if (ans.get("items") or {}).get(n.strip().lower())), None)
            if hit:
                raise HTTPException(status_code=409, detail=f"Esta persona ya recibió «{hit}» en otro puesto y no se le puede entregar otra vez.")

    batch, now = uuid.uuid4().hex, utcnow()
    for item_id, qty in wanted.items():
        db.add(InventoryDelivery(
            event_id=event.id, item_id=item_id, batch_id=batch, user_id=user.id, tenant_id=event.tenant_id,
            qty=qty, delivered_at=now, delivered_by_staff_id=staff.id,
        ))
    db.commit()
    delivered = _delivered_by_item(db, event.id)
    return {
        "result": "OK", "data": _person_data(user), "batch_id": batch,
        "delivered": [{"name": items[i].name, "qty": q} for i, q in wanted.items()],
        "stock": [_item_json(items[i], delivered.get(i, 0)) for i in wanted],
        **({"warning": warning} if warning else {}),
    }


@router.get("/events/{event_id}/inventory/deliveries")
def recent_deliveries(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    item_rows = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.event_id == event.id)}
    items = {k: subcat.label_of(item_rows, v) for k, v in item_rows.items()}
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id)}
    rows = db.query(InventoryDelivery).filter(InventoryDelivery.event_id == event.id).order_by(InventoryDelivery.delivered_at.desc(), InventoryDelivery.id.desc()).limit(60).all()
    return [{
        "time": r.delivered_at.isoformat(), "user_id": r.user_id, "batch_id": r.batch_id,
        "name": f"{users[r.user_id].first_name or ''} {users[r.user_id].last_name or ''}".strip() if r.user_id in users else "",
        "item": items.get(r.item_id, ""), "qty": r.qty,
    } for r in rows]


@router.get("/events/{event_id}/inventory/deliveries/person")
def person_deliveries(event_id: int, cedula: str, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """26-nov-2026 (Juan David): el historial COMPLETO de entregas de UNA persona (buscador de «Últimas entregas»; solo coordinador en adelante).
    `cedula` = la identificación de la persona que eligió la pantalla (o su código). Quién entregó va por su nombre de cuenta, nunca su usuario (es su cédula)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    user = _find_person(db, event, cedula, "inventario")
    item_rows = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.event_id == event.id)}
    rows = (db.query(InventoryDelivery).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.user_id == user.id)
            .order_by(InventoryDelivery.delivered_at.desc(), InventoryDelivery.id.desc()).all())
    sids = {r.delivered_by_staff_id for r in rows if r.delivered_by_staff_id}
    names = {sid: ((n or "").strip() or "Personal del evento") for sid, n in db.query(StaffUser.id, StaffUser.full_name).filter(StaffUser.id.in_(sids))} if sids else {}
    return {"person": {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "code": person_code.code_of(db, event, user.id) or ""},
            "deliveries": [{"time": r.delivered_at.isoformat(), "user_id": r.user_id, "batch_id": r.batch_id, "item": subcat.label_of(item_rows, item_rows[r.item_id]) if r.item_id in item_rows else "",
                            "qty": r.qty, "by": names.get(r.delivered_by_staff_id, "")} for r in rows]}


@router.get("/events/{event_id}/inventory-report")
def inventory_report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG_ROLE)):
    """Hoja 'Entregas' (hora, a quién, qué se le entregó) + hoja 'Inventario' (inicial / entregado / disponible)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    items = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.event_id == event.id).order_by(InventoryItem.id)}
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id)}
    staff_names = {s.id: (s.full_name or s.username) for s in db.query(StaffUser)}
    labels = {k: subcat.label_of(items, v) for k, v in items.items()}          # «Comida › Perro»
    deliveries = []
    for r in db.query(InventoryDelivery).filter(InventoryDelivery.event_id == event.id).order_by(InventoryDelivery.delivered_at, InventoryDelivery.id):
        u = users.get(r.user_id)
        deliveries.append([
            to_local(r.delivered_at).strftime("%Y-%m-%d"), to_local(r.delivered_at).strftime("%H:%M:%S"), r.user_id,
            f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "", labels.get(r.item_id, ""),
            r.qty, staff_names.get(r.delivered_by_staff_id, ""),
        ])
    delivered = _delivered_by_item(db, event.id)
    kids = {}
    for i in items.values():
        if i.parent_id:
            kids.setdefault(i.parent_id, []).append(i)
    stock = []
    for i in items.values():
        if i.id in kids:          # grupo: suma de sus subcategorías
            ini = sum(c.initial_qty for c in kids[i.id]); ent = sum(delivered.get(c.id, 0) for c in kids[i.id])
        else:
            ini, ent = i.initial_qty, delivered.get(i.id, 0)
        stock.append([labels[i.id] + (" (total del grupo)" if i.id in kids else ""), ini, ent, ini - ent])
    return _xlsx_response({
        "Entregas": pd.DataFrame(deliveries, columns=["Fecha", "Hora", "Cédula", "Persona", "Ítem", "Cantidad", "Entregado por"]),
        "Inventario": pd.DataFrame(stock, columns=["Ítem", "Cantidad inicial", "Entregado", "Disponible"]),
    }, heavy.event_report_filename(event, "Reporte de inventario"))
