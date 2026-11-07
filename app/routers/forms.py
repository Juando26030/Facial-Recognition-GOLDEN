"""Formularios Web — lado del coordinador (Sprint 5): crear/editar formularios de un evento, estados y calendario, cupo,
plantillas, respuestas, archivos, invitaciones, reporte y carga a la base. Todo coordinador+ (comercial incluida).
La página pública que llena la gente vive en `forms_public.py` (`/f/<evento>/<formulario>`, sin login)."""
import io
import json
import os
import re
import secrets
from datetime import datetime
from app.timeutil import utcnow
from app.roster_columns import MAX_OPTIONAL_FIELDS
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import audit_actions, bulk_jobs, formlib, formsvc, heavy, ops, optionvalues, publicurl, variant_table, warmup, wompi
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.mailer import send_mail
from app.models import Event, EventAttendee, FormClientUser, FormDiscountCode, FormEvent, FormInvite, FormPayment, FormPerson, FormRefund, FormSubmission, SavedFormTemplate, StaffUser, User, WebForm
from app.routers import parametros
from app.routers.badges import ALLOWED_IMAGE_EXT
from app.storage import badge_asset_key, form_file_key, get_storage
from app.timeutil import to_local

router = APIRouter()
STAFF = require_role("coordinador")
ADMIN = require_role("admin")


# ------------------------------------------------------------------ utilidades
def _get_form(db: Session, event: Event, form_id: int) -> WebForm:
    form = db.query(WebForm).filter(WebForm.id == form_id, WebForm.event_id == event.id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    return form


def _not_archived(form: WebForm) -> None:
    if form.archived_at is not None:
        raise HTTPException(status_code=400, detail="El formulario está archivado: restáuralo para modificarlo")


def _base_url(request: Request) -> str:
    return publicurl.base(str(request.base_url))


def _urls(request: Request, form: WebForm) -> dict:
    base = f"{_base_url(request)}/f/{form.event_id}/{form.slug}"
    return {"public_url": base, "test_url": f"{base}?k={form.test_key}"}


def _unique_slug(db: Session, event_id: int, wanted: str, exclude_id: Optional[int] = None) -> str:
    base = formlib.slugify(wanted)
    slug, n = base, 2
    while True:
        q = db.query(WebForm).filter(WebForm.event_id == event_id, WebForm.slug == slug)
        if exclude_id:
            q = q.filter(WebForm.id != exclude_id)
        if not q.first():
            return slug
        slug, n = f"{base}-{n}", n + 1


def _optional_keys(event: Event) -> set:
    return set(event.get_optional_labels().keys())


def _allocate_event_fields(event: Event, design: dict) -> dict:
    """Campos marcados «guardar también en Parámetros del Evento» (`sync`) y sin vínculo: se les asigna el primer
    `opcional_N` libre y se rotula con su nombre — mismo mecanismo que «agregar campo» en Parámetros."""
    labels = event.get_optional_labels()
    for f in design["fields"].values():
        if f["type"] in formlib.INPUT_TYPES and f.get("sync") and not f.get("key"):
            used = {int(k.split("_")[1]) for k in labels}
            slot = next((n for n in range(1, MAX_OPTIONAL_FIELDS + 1) if n not in used), None)
            if slot is None:
                raise HTTPException(status_code=400, detail=f"Se alcanzó el techo técnico de {MAX_OPTIONAL_FIELDS} campos opcionales del evento")
            key = f"opcional_{slot}"
            labels[key] = f["label"]
            f["key"], f["sync"] = key, False
    event.set_optional_labels(labels)
    return design


def _summary(db: Session, form: WebForm, request: Request) -> dict:
    real = formsvc.real_submissions(db, form).count()
    tests = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == True, FormSubmission.status == "confirmed").count()  # noqa: E712
    return {
        "id": form.id, "archived": form.archived_at is not None, "archived_at": form.archived_at.isoformat() if form.archived_at else None,
        "name": form.name, "slug": form.slug, "manual_status": form.manual_status, "use_schedule": form.use_schedule,
        "status": formsvc.status_of(form), "public_state": formsvc.public_state(db, form), "capacity": form.capacity,
        "submissions": real, "test_submissions": tests,
        "preregistered": (marks := formsvc.mark_counts(db, form))["block"], "registered_hold": marks["hold"],      # «ya registradas»: solo bloquean | además ocupan cupo (ya van dentro de `submissions`) "created_at": to_local(form.created_at).strftime("%Y-%m-%d %H:%M"),
        "feed": formsvc.get_settings(form)["feed"], **_urls(request, form),
    }


def _detail(db: Session, form: WebForm, request: Request) -> dict:
    return {**_summary(db, form, request), "design": formsvc.get_design(form), "settings": formsvc.get_settings(form),
            "schedule": formsvc.get_schedule(form), "test_key": form.test_key, "fed_at": form.fed_at.isoformat() if form.fed_at else None,
            "quota_status": formsvc.quota_status(db, form),
            "digital_badge_enabled": bool(getattr(db.query(Event).filter(Event.id == form.event_id).first(), "digital_badge_enabled", False)),
            "payments": {"has_field": bool(formlib.payment_field(formsvc.get_design(form))), "sandbox_configured": bool(wompi.config(True)), "production_configured": bool((wompi.config(False) or {}).get("test") is False)}}


# ------------------------------------------------------------------ CRUD
@router.get("/events/{event_id}/forms")
def list_forms(event_id: int, request: Request, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Fase 3: por defecto SOLO los formularios no archivados; `include_archived=true` (admin+) devuelve los archivados («Ver archivados»)."""
    event = get_event_for_staff(event_id, db, staff)
    if include_archived and staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo un administrador puede ver los formularios archivados")
    q = db.query(WebForm).filter(WebForm.event_id == event.id)
    q = q.filter(WebForm.archived_at.isnot(None)) if include_archived else q.filter(WebForm.archived_at.is_(None))
    forms = q.order_by(WebForm.id.desc()).all()
    for f in forms:
        if f.archived_at is None:
            _maybe_feed_on_close(db, f)
    return [_summary(db, f, request) for f in forms]


@router.post("/events/{event_id}/forms")
def create_form(event_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Crea un formulario nuevo (con campos de partida) o, con `template_id`, a partir de una plantilla guardada."""
    event = get_event_for_staff(event_id, db, staff)
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="Ponle un nombre al formulario")
    if data.get("template_id"):
        tpl = db.query(SavedFormTemplate).filter_by(id=data["template_id"], tenant_id=event.tenant_id).first()
        if not tpl:
            raise HTTPException(status_code=404, detail="Plantilla no encontrada")
        design = json.loads(tpl.design_json)
        design["theme"]["title"] = design["theme"].get("title") or name
    else:
        design = formlib.default_design(name)
    try:
        design = formlib.sanitize_design(design, _optional_keys(event) | {f"opcional_{i}" for i in range(1, MAX_OPTIONAL_FIELDS + 1)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # un diseño importado puede traer campos opcional_N que este evento no tiene: se desvinculan (quedan como campos solo del formulario)
    valid = set(formlib.IDENTITY_KEYS) | _optional_keys(event)
    for f in design["fields"].values():
        if f.get("key") and f["key"] not in valid:
            f["key"] = None
    form = WebForm(
        event_id=event.id, name=name, slug=_unique_slug(db, event.id, name), manual_status="pruebas", design_json=json.dumps(design),
        settings_json=json.dumps(formlib.sanitize_settings({})), test_key=secrets.token_urlsafe(12), created_by_id=staff.id,
    )
    db.add(form)
    db.commit()
    return _detail(db, form, request)


@router.get("/events/{event_id}/forms/{form_id}")
def get_form(event_id: int, form_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    return _detail(db, _get_form(db, event, form_id), request)


@router.put("/events/{event_id}/forms/{form_id}")
def update_form(event_id: int, form_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Guarda nombre, dirección (slug), diseño y/o configuración. El diseño se valida completo en el servidor."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    _not_archived(form)
    quota_before = formsvc.quota_sig_map(form)
    if "name" in data:
        name = str(data["name"]).strip()[:120]
        if not name:
            raise HTTPException(status_code=400, detail="El formulario necesita un nombre")
        form.name = name
    if "slug" in data:
        slug = formlib.slugify(data["slug"])
        if db.query(WebForm).filter(WebForm.event_id == event.id, WebForm.slug == slug, WebForm.id != form.id).first():
            raise HTTPException(status_code=400, detail="Ya hay otro formulario con esa dirección en este evento")
        form.slug = slug
    try:
        if "design" in data:
            design = formlib.sanitize_design(data["design"], _optional_keys(event))
            design = _allocate_event_fields(event, design)
            form.design_json = json.dumps(design)
        if "settings" in data:
            form.settings_json = json.dumps(formlib.sanitize_settings(data["settings"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if ("design" in data or "settings" in data) and formsvc.get_settings(form)["block_repeats"]["enabled"] and not formsvc.repeat_target(formsvc.get_settings(form), formsvc.get_design(form)):
        db.rollback()
        raise HTTPException(status_code=400, detail="Para bloquear inscripciones repetidas elige el campo identificador (cédula, correo, teléfono u otro) o agrega un campo de cédula al formulario")
    if ("design" in data or "settings" in data) and formsvc.quota_sig_map(form) != quota_before:
        formsvc.invalidate_quota_keys(db, form)
        formsvc.rebuild_quota_keys(db, form, formsvc.quota_rules(form))          # se recalculan aquí, una vez y guardadas con este mismo guardado (no en cada visita pública)
    db.commit()
    formsvc.invalidate_public_cache()
    return _detail(db, form, request)


def _registered_parse(db: Session, event: Event, form: WebForm, file: UploadFile, with_data: bool = False) -> dict:
    """Lee el archivo de «Personas ya registradas»: columna de la cédula (o del campo identificador), filas que cuentan y, con `with_data`, los datos de los campos del formulario que trae
    (p. ej. la ciudad) para que cuenten en los cupos por variables. Lo comparten la vista previa y la carga: ven exactamente lo mismo."""
    from app import registered_list, roster_columns
    from app.routers.api import _read_roster_rows, _truthy
    settings, design = formsvc.get_settings(form), formsvc.get_design(form)
    probe = {**settings, "block_repeats": {**settings["block_repeats"], "enabled": True}}
    target = formsvc.repeat_target(probe, design)
    if not target:
        raise HTTPException(status_code=400, detail="Elige el campo identificador (cédula, correo, teléfono u otro) o agrega un campo de cédula al formulario antes de cargar la lista")
    try:
        header, rows = _read_roster_rows(file.filename, file.file.read())
    except Exception:  # noqa: BLE001 — archivo ilegible
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo (usa Excel .xlsx o CSV)")
    kind_of = {h: roster_columns._LOOKUP.get(roster_columns.norm(h)) for h in header}
    flag_col = next((h for h, k in kind_of.items() if k == "registrado en formulario"), None)
    field = design["fields"][target[1]]
    if target[0] == "cedula":
        col = next((h for h, k in kind_of.items() if k == "id"), None)
        if not col:
            raise HTTPException(status_code=400, detail="El archivo necesita una columna de cédula (id / cédula)")
    else:
        want = {"email": "correo", "phone": "telefono"}.get(field.get("key") or "")
        col = next((h for h in header if roster_columns.norm(h) == roster_columns.norm(field.get("label"))), None) or next((h for h, k in kind_of.items() if want and k == want), None)
        if not col:
            others = [h for h in header if h != flag_col]
            col = others[0] if len(others) == 1 else None
        if not col:
            raise HTTPException(status_code=400, detail=f"El archivo necesita una columna llamada «{field.get('label')}»")
    kept = [r for r in rows if not flag_col or _truthy(r.get(flag_col, ""))]
    values = [r.get(col, "") for r in kept]
    if not values:
        raise HTTPException(status_code=400, detail="El archivo no trae filas para cargar" + (" (ninguna con «sí» en «Registrado en formulario»)" if flag_col else ""))
    labels = {cfg["key"]: cfg["label"] for cfg in parametros.field_configs_for_event(db, event)}
    colmap = registered_list.match_columns(design, header, {h: k for h, k in kind_of.items() if k}, labels, skip={col, flag_col} - {None})
    colmap.pop(target[1], None)                      # el identificador ya va por su columna
    extras = {str(r.get(col, "")).strip(): registered_list.row_values(r, colmap) for r in kept} if with_data else None
    return {"target": target, "design": design, "settings": settings, "field": field, "values": values, "rows": kept, "col": col, "colmap": colmap, "extras": extras}


@router.post("/events/{event_id}/forms/{form_id}/registered/preview")
def preview_registered(event_id: int, form_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Antes de cargar: qué columnas del archivo corresponden a campos del formulario, cuáles de ellas definen cupos por variables (p. ej. la ciudad) y cuánto restaría cada cupo.
    No guarda nada. La pantalla usa esto para preguntar si las personas deben restar de esos cupos."""
    from app import registered_list
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    p = _registered_parse(db, event, form, file, with_data=True)
    rules = formsvc.quota_rules(form)
    qids = registered_list.quota_field_ids(rules)
    design = p["design"]
    in_file = [fid for fid in p["colmap"] if fid in qids]
    missing = [design["fields"][fid].get("label") or fid for fid in qids if fid not in p["colmap"] and fid in design["fields"] and fid != p["target"][1]]
    # solo las personas NUEVAS restan (las que ya están inscritas o marcadas no se duplican): se comparan por cédula
    existing = set()
    if p["target"][0] == "cedula":
        existing = {r[0] for r in db.query(FormSubmission.person_id).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == False,  # noqa: E712
                                                                            FormSubmission.person_id != None, FormSubmission.status.in_(("preregistered", "confirmed")))}  # noqa: E711
    new_rows, seen = [], set()
    for raw, row in zip(p["values"], p["rows"]):
        pid = str(raw or "").strip().replace(".", "").replace(" ", "")
        if not pid or pid in seen or pid in existing:
            continue
        seen.add(pid)
        new_rows.append({**(p["extras"].get(str(raw).strip()) or {}), p["target"][1]: pid})
    counts = formsvc.quota_counts(db, form, rules) if rules else {}
    return {"rows": len(p["values"]), "new": len(new_rows), "already": len(p["values"]) - len(new_rows),
            "columns": [{"field": fid, "label": design["fields"][fid].get("label") or fid, "column": col, "defines_quota": fid in qids} for fid, col in p["colmap"].items()],
            "quota_fields": [design["fields"][fid].get("label") or fid for fid in in_file], "quota_missing": missing,
            "impact": registered_list.impact(rules, new_rows, counts) if in_file else [],
            "unmatched": sum(1 for v in new_rows if in_file and not any(f in v for f in in_file))}


@router.get("/events/{event_id}/forms/{form_id}/registered/template")
def registered_template(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Plantilla de la lista de «Personas ya registradas» con las columnas de ESTE formulario (cédula y cada campo que se puede traer: nombres, ciudad, etc.). Los títulos son los del
    formulario, así la carga los reconoce y no se mezclan con la base del evento. Hoja «Instrucciones» con los valores válidos de cada lista."""
    from app import registered_list
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    design = formsvc.get_design(form)
    target = formsvc.repeat_target({**formsvc.get_settings(form), "block_repeats": {**formsvc.get_settings(form)["block_repeats"], "enabled": True}}, design)
    if not target:
        raise HTTPException(status_code=400, detail="Elige el campo identificador o agrega un campo de cédula al formulario antes de descargar la plantilla")
    cols = registered_list.template_columns(design, target[1])
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista"
    ws.append(cols)
    for c in range(1, len(cols) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = 26
    ws.freeze_panes = "A2"
    info = wb.create_sheet("Instrucciones")
    info.column_dimensions["A"].width = 38
    info.column_dimensions["B"].width = 90
    info.append(["Cómo llenar esta lista", ""])
    info["A1"].font = Font(bold=True)
    for line in ("Una fila por persona; la primera columna (cédula) es obligatoria.",
                 "No cambies los títulos de las columnas: así se reconocen y no se mezclan con la base del evento.",
                 "Las columnas que definen cupos (por ejemplo la ciudad) deben traer el valor EXACTO de la lista de opciones: sin él la persona no resta de ningún cupo.",
                 "Si una cédula ya está inscrita en este formulario NO se duplica ni se cambia su inscripción.",
                 "Para que resten de los cupos hay que elegir «Bloquear y ocupar cupo» y aceptar la pregunta de cupos al cargar."):
        info.append(["", line])
    qids = registered_list.quota_field_ids(formsvc.quota_rules(form))
    info.append([])
    info.append(["Valores válidos", ""])
    info.cell(row=info.max_row, column=1).font = Font(bold=True)
    for fid in qids:
        f = design["fields"].get(fid)
        if not f:
            continue
        vals = sorted({c.get("value") for r in formsvc.quota_rules(form) for c in r["conds"] if c["field"] == fid and isinstance(c.get("value"), str)})
        info.append([f.get("label") or fid, ", ".join(vals) if vals else (", ".join(f.get("options") or []) or "libre")])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="lista-ya-registradas.xlsx"', "Cache-Control": "no-store"})


@router.post("/events/{event_id}/forms/{form_id}/registered")
def upload_registered(event_id: int, form_id: int, file: UploadFile = File(...), mode: str = Form("add"), effect: str = Form("block"), enable: str = Form("1"), with_data: str = Form("0"),
                      db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Carga o recarga la lista de «Personas ya registradas» de ESTE formulario (cédula, o el campo identificador elegido; la columna «Registrado en formulario» es opcional: si viene, solo
    cuentan las filas con «sí»). `mode`: `add` (no quita nada) | `replace` (quita las marcas previas de este formulario). `effect`: `block` (solo bloquea; por defecto) | `hold` (ocupa cupo
    como una inscripción y bloquea). `enable` (por defecto sí): si el interruptor «Bloquear inscripciones repetidas» está apagado, lo enciende (las marcas solo bloquean con él encendido).
    `with_data` (sí): además de la cédula se guardan los datos de los campos del formulario que trae el archivo (p. ej. la ciudad) y, como ocupan cupo, restan de los cupos por variables.
    Una persona que ya está inscrita (o ya marcada) no se duplica."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    if mode not in ("add", "replace") or effect not in ("block", "hold"):
        raise HTTPException(status_code=400, detail="Modo no válido")
    data_on = with_data not in ("0", "false", "")
    if data_on:
        effect = "hold"             # para restar de los cupos tienen que contar como inscripciones confirmadas
    p = _registered_parse(db, event, form, file, with_data=data_on)
    settings, target, field = p["settings"], p["target"], p["field"]
    res = formsvc.apply_list(db, form, p["values"], target[0], target[1], field.get("type"), mode == "replace", effect == "hold", extras=p["extras"])
    turned_on = False
    if enable not in ("0", "false", "") and not settings["block_repeats"]["enabled"]:
        settings["block_repeats"] = {"enabled": True, "field": "" if target[0] == "cedula" else target[1]}
        form.settings_json = json.dumps(settings)
        turned_on = True
    over = []
    if data_on:
        for r, st in zip(formsvc.quota_rules(form), formsvc.quota_status(db, form)):
            if st["used"] > r["limit"]:
                over.append(f"«{r['label']}» ({st['used']} de {r['limit']})")
    db.commit()
    formsvc.invalidate_public_cache()
    formsvc.invalidate_held()
    msg = f"Lista cargada: {res['added']} nuevas" + (f", {res['converted']} pasaron a ocupar cupo" if res["converted"] else "") + f", {res['existing']} ya estaban"
    msg += f", {res['removed']} marcas anteriores quitadas." if res["removed"] else "."
    if data_on:
        msg += " Restan de los cupos por variables."
    if over:
        msg += " ATENCIÓN: con esta lista quedaron superados los cupos " + ", ".join(over) + "."
    if effect == "hold" and form.capacity is not None and formsvc.held_count(db, form) > form.capacity:
        msg += " ATENCIÓN: con esta lista el cupo del formulario quedó superado."
    if turned_on:
        msg += " Se activó «Bloquear inscripciones repetidas» en este formulario."
    elif not settings["block_repeats"]["enabled"]:
        msg += " OJO: «Bloquear inscripciones repetidas» está apagado: las marcas solo bloquean con ese interruptor encendido."
    return {**res, "message": msg, **formsvc.mark_counts(db, form), "turned_on": turned_on, "over": over}


@router.delete("/events/{event_id}/forms/{form_id}/registered")
def clear_registered(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """«Quitar todas las marcas»: borra las marcas «ya registrado» de este formulario (liberan el cupo las que lo ocupaban). No toca inscripciones reales."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    db.query(WebForm.id).filter(WebForm.id == form.id).with_for_update().first()
    n = formsvc.clear_marks(db, form)
    db.commit()
    formsvc.invalidate_public_cache()
    formsvc.invalidate_held()
    return {"removed": n, "message": f"Se quitaron {n} marcas de «ya registrado»."}


@router.post("/events/{event_id}/forms/{form_id}/archive")
def archive_form(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Fase 3: archivar = ocultar de las listas y cerrar al público (no recibe envíos). Conserva inscripciones, archivos y pagos: el contrato exige poder entregar esa base. Si estaba activo
    pasa a «cerrado» (y sin calendario) para que al restaurarlo NO se reabra solo; un administrador lo vuelve a abrir cuando quiera."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    if form.archived_at is not None:
        raise HTTPException(status_code=400, detail="El formulario ya está archivado")
    if form.manual_status == "activo" or form.use_schedule:
        form.manual_status, form.use_schedule = ("cerrado" if form.manual_status == "activo" else form.manual_status), False
    form.archived_at = utcnow()
    form.archived_by_id = staff.id
    audit_actions.record(db, staff, "archive", "form", form.id, form.name, f"evento {event.id}")
    db.commit()
    formsvc.invalidate_public_cache()
    formsvc.invalidate_held()
    return {"message": "Formulario archivado: ya no recibe envíos. Las respuestas y los pagos se conservan.", "archived": True}


@router.post("/events/{event_id}/forms/{form_id}/restore")
def restore_form(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    if form.archived_at is None:
        raise HTTPException(status_code=400, detail="El formulario no está archivado")
    form.archived_at = None
    form.archived_by_id = None
    audit_actions.record(db, staff, "restore", "form", form.id, form.name, f"evento {event.id}")
    db.commit()
    formsvc.invalidate_public_cache()
    return {"message": "Formulario restaurado (queda cerrado; ábrelo cuando quieras)", "archived": False}


@router.delete("/events/{event_id}/forms/{form_id}")
def delete_form(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Borrado DEFINITIVO: solo super_admin, solo de un formulario ya archivado y SIN inscripciones ni pagos (las marcas «ya registrado» de la base no cuentan); queda en `audit_actions`.
    Un formulario con respuestas o pagos no se borra nunca por aquí: se archiva."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    if form.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el formulario; el borrado definitivo solo aplica a formularios archivados")
    if db.query(FormSubmission.id).filter(FormSubmission.form_id == form.id, FormSubmission.status != formsvc.PREREGISTERED).first() or db.query(FormPayment.id).filter(FormPayment.form_id == form.id).first():
        raise HTTPException(status_code=409, detail="El formulario tiene inscripciones o pagos: se conservan (contrato). Déjalo archivado.")
    audit_actions.record(db, staff, "delete", "form", form.id, form.name, f"evento {event.id}")
    delete_form_rows(db, form)
    db.commit()
    formsvc.invalidate_public_cache()
    return {"message": "Formulario eliminado"}


def delete_form_rows(db: Session, form: WebForm) -> None:
    if db.query(FormPayment).filter(FormPayment.form_id == form.id, FormPayment.status.in_(("approved", "refunded")), FormPayment.is_test == False).first():  # noqa: E712
        raise HTTPException(status_code=409, detail=f"El formulario «{form.name}» tiene pagos aprobados: son registros financieros y no se pueden borrar. Ciérralo o finalízalo en su lugar.")
    db.query(FormRefund).filter(FormRefund.payment_id.in_(db.query(FormPayment.id).filter(FormPayment.form_id == form.id))).delete(synchronize_session=False)
    db.query(FormPayment).filter(FormPayment.form_id == form.id).delete()
    db.query(FormSubmission).filter(FormSubmission.form_id == form.id).delete()
    db.query(FormDiscountCode).filter(FormDiscountCode.form_id == form.id).delete()
    db.query(FormEvent).filter(FormEvent.form_id == form.id).delete()
    db.query(FormInvite).filter(FormInvite.form_id == form.id).delete()
    db.query(FormPerson).filter(FormPerson.form_id == form.id).delete()
    for grant in db.query(FormClientUser).filter(FormClientUser.form_id == form.id).all():       # accesos de cliente por formulario: la cuenta queda sin acceso a nada
        grant.staff_user.is_active = False
        db.delete(grant)
    db.flush()
    event = db.query(Event).filter(Event.id == form.event_id).first()
    if event:
        get_storage().delete_prefix(form_file_key(event.tenant_id, form.id))
    db.delete(form)


@router.post("/events/{event_id}/forms/{form_id}/duplicate")
def duplicate_form(event_id: int, form_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    src = _get_form(db, event, form_id)
    name = f"{src.name} (copia)"
    copy = WebForm(event_id=event.id, name=name, slug=_unique_slug(db, event.id, name), manual_status="pruebas", design_json=src.design_json,
                   settings_json=src.settings_json, capacity=src.capacity, test_key=secrets.token_urlsafe(12), created_by_id=staff.id)
    db.add(copy)
    db.commit()
    return _detail(db, copy, request)


# ------------------------------------------------------------------ estado, calendario y cupo
@router.put("/events/{event_id}/forms/{form_id}/status")
def set_status(event_id: int, form_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Estado manual, calendario por fechas y cupo (editable en caliente: no se pierde ninguna inscripción)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    _not_archived(form)
    was_active = form.manual_status == "activo"
    if "manual_status" in data:
        if data["manual_status"] not in formlib.STATUSES:
            raise HTTPException(status_code=400, detail=f"Estado inválido (uno de: {', '.join(formlib.STATUSES)})")
        form.manual_status = data["manual_status"]
    if "schedule" in data:
        try:
            form.schedule_json = json.dumps(formlib.parse_schedule(data["schedule"]))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if "use_schedule" in data:
        form.use_schedule = bool(data["use_schedule"])
        if form.use_schedule and not formsvc.get_schedule(form):
            raise HTTPException(status_code=400, detail="Para usar el calendario define al menos un tramo")
    if "capacity" in data:
        cap = data["capacity"]
        if cap in (None, ""):
            form.capacity = None
        else:
            try:
                cap = int(cap)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="El cupo debe ser un número")
            if cap < 1:
                raise HTTPException(status_code=400, detail="El cupo debe ser al menos 1")
            form.capacity = cap
    db.commit()
    formsvc.invalidate_public_cache()
    _maybe_feed_on_close(db, form)
    opened = form.manual_status == "activo" and not was_active and not form.use_schedule
    if opened:
        ops.record_system_event("form_opened", str(form.id))        # el precalentamiento mantiene «publico» caliente la hora siguiente
    if opened or "schedule" in data or "use_schedule" in data:
        warmup.kick()
    return _detail(db, form, request)


def _upsert():
    import functools
    from app.routers.api import _upsert_attendee
    return functools.partial(_upsert_attendee, origin="autoregistro")      # B1: lo que entra por un formulario web = «Autoregistro»


def _maybe_feed_on_close(db: Session, form: WebForm) -> None:
    """Modo «al cerrar»: cuando el formulario ya está cerrado/finalizado, se cargan solas todas las inscripciones
    pendientes (una vez; las que lleguen después —no debería— se cargan con «Cargar ahora»)."""
    if formsvc.get_settings(form)["feed"] == "on_close" and form.fed_at is None and formsvc.status_of(form) in ("cerrado", "finalizado"):
        formsvc.feed_pending(db, form, _upsert())


@router.post("/events/{event_id}/forms/{form_id}/feed-now")
def feed_now(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Carga a la base del evento todas las inscripciones reales aún no cargadas (quedan «No registrado»)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    return formsvc.feed_pending(db, form, _upsert())


# ------------------------------------------------------------------ campos del evento (Parámetros) y plantillas
@router.get("/events/{event_id}/form-event-fields")
def event_fields(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Campos del evento (Parámetros) disponibles para arrastrar al formulario: los de identidad y cada opcional."""
    event = get_event_for_staff(event_id, db, staff)
    out = []
    for cfg in parametros.field_configs_for_event(db, event):
        key = cfg["key"]
        if key in ("categories", "certificate", "digital_contact") or cfg["field_type"] == "signature":
            continue
        kind = {"boolean": "checkbox", "consent": "checkbox", "email": "email"}.get(cfg["field_type"], cfg["field_type"])
        if key == "email":
            kind = "email"
        if key == "phone":
            kind = "phone"
        out.append({"key": key, "label": cfg["label"], "type": kind if kind in formlib.INPUT_TYPES else "text_short", "options": cfg.get("options") or [], "required": bool(cfg.get("required")), "help": cfg.get("help_text") or ""})
    return out


@router.get("/events/{event_id}/field-values")
def field_values(event_id: int, key: str, scope: str = "event", db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Valores DISTINTOS que ya hay en la base para un campo NO identificante del evento (para armar opciones de lista). `scope`: «event» (las
    personas de este evento) o «client» (las de todos los eventos del mismo cliente). Solo valores con su conteo, nunca registros de personas."""
    event = get_event_for_staff(event_id, db, staff)
    label = next((c["label"] for c in parametros.field_configs_for_event(db, event) if c["key"] == key), None)
    if label is None:
        raise HTTPException(status_code=404, detail="Ese campo no existe en este evento")
    try:
        optionvalues.check_key(key, label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    q = db.query(EventAttendee, User).join(User, (User.id == EventAttendee.user_id) & (User.tenant_id == EventAttendee.tenant_id))
    if scope == "client":
        q = q.filter(EventAttendee.event_id.in_([e for (e,) in db.query(Event.id).filter(Event.tenant_id == event.tenant_id)]))
    else:
        q = q.filter(EventAttendee.event_id == event.id)
    counts: dict = {}
    seen: set = set()
    for att, user in q.limit(200000):
        if key != "categories":
            if user.id in seen:
                continue
            seen.add(user.id)
        found = att.get_categories() if key == "categories" else [user.get_extras().get(key) if key.startswith("opcional_") else getattr(user, key, None)]
        for v in found:
            v = str(v or "").strip()
            if v:
                counts[v] = counts.get(v, 0) + 1
    return {"key": key, "label": label, "scope": "client" if scope == "client" else "event", **optionvalues.group_values(counts)}


# ------------------------------------------------------------------ tabla de variantes en Excel (P11)
@router.post("/events/{event_id}/forms/{form_id}/variant-table/template")
def variant_table_template(event_id: int, form_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Genera el .xlsx (hojas «Tabla», «Instrucciones» y «Valores válidos») de la tabla de variantes que define el navegador; con las celdas que ya traiga es la descarga de una tabla armada.
    Mismos permisos que editar el diseño del formulario. No guarda nada."""
    event = get_event_for_staff(event_id, db, staff)
    _get_form(db, event, form_id)
    try:
        content = variant_table.build_template(data)
    except variant_table.ExcelRejected as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="tabla-de-variantes.xlsx"', "Cache-Control": "no-store"})


@router.post("/events/{event_id}/forms/{form_id}/variant-table/parse")
def variant_table_parse(event_id: int, form_id: int, file: UploadFile = File(...), spec: str = Form(...), mapping: str = Form(""), db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Lee un .xlsx subido y lo empareja con la tabla; devuelve las celdas y los problemas SIN guardar nada (el archivo se procesa en memoria: ni disco ni almacenamiento) y sin escribir su contenido en los logs."""
    event = get_event_for_staff(event_id, db, staff)
    _get_form(db, event, form_id)
    if len(spec) > 1_000_000:
        raise HTTPException(status_code=400, detail="La definición de la tabla es demasiado grande")
    try:
        spec_obj = json.loads(spec)
    except ValueError:
        raise HTTPException(status_code=400, detail="La definición de la tabla no es válida")
    if len(mapping) > 50_000:
        raise HTTPException(status_code=400, detail="La asignación de columnas es demasiado grande")
    try:
        mapping_obj = json.loads(mapping) if mapping else None
    except ValueError:
        raise HTTPException(status_code=400, detail="La asignación de columnas no es válida")
    raw = file.file.read(variant_table.MAX_FILE_BYTES + 1)
    try:
        # sin asignación: si algún encabezado no coincide, se devuelve el paso «Asignar columnas» (no se lee nada); con asignación, vale solo para esta lectura
        return variant_table.read_table(raw, file.filename or "", spec_obj, mapping=mapping_obj, ask=mapping_obj is None)
    except variant_table.ExcelRejected as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------------ descuentos: sugerencias de valores y códigos
@router.get("/events/{event_id}/forms/{form_id}/value-suggestions")
def value_suggestions(event_id: int, form_id: int, key: str = "", fid: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Los valores que ya existen para una variable, para ofrecerlos como lista en las condiciones de precio/descuento en vez de
    pedir escribirlos (si son pocos). `key`: campo del evento (base de asistentes); `fid`: campo del formulario (inscripciones hechas)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    values: dict = {}
    if key in ("role", "entity", "opt_1") or key.startswith("opcional_") or key == "categories":
        for att, user in db.query(EventAttendee, User).join(User, (User.id == EventAttendee.user_id) & (User.tenant_id == EventAttendee.tenant_id)).filter(EventAttendee.event_id == event.id).limit(20000):
            found = att.get_categories() if key == "categories" else [user.get_extras().get(key) if key.startswith("opcional_") else getattr(user, key, None)]
            for v in found:
                v = str(v or "").strip()
                if v:
                    values[v] = values.get(v, 0) + 1
    field = formsvc.get_design(form)["fields"].get(fid) if fid else None
    if field and field["type"] in ("text_short", "select", "radio", "number"):
        for sub in formsvc.real_submissions(db, form).limit(20000):
            v = json.loads(sub.data_json).get(fid)
            v = str(v or "").strip() if not isinstance(v, (dict, list)) else ""
            if v:
                values[v] = values.get(v, 0) + 1
    ordered = sorted(values, key=lambda x: (-values[x], x.lower()))
    return {"values": ordered[:200], "total": len(ordered)}


CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # sin 0/O/1/I/L: se dictan y se copian sin equivocarse
MAX_CODES_PER_FORM = 20000


def _discount_of(form: WebForm, discount_id: str) -> dict:
    for f in formsvc.get_design(form)["fields"].values():
        if f["type"] == formlib.PAYMENT_TYPE:
            for d in f["pay"].get("discounts", []):
                if d.get("id") == discount_id and d.get("how") == "code":
                    return d
    raise HTTPException(status_code=400, detail="Ese descuento no es «con código» o todavía no está guardado en el diseño. Guarda el diseño primero.")


def _code_rows(db: Session, form: WebForm) -> list:
    labels = {}
    for f in formsvc.get_design(form)["fields"].values():
        if f["type"] == formlib.PAYMENT_TYPE:
            labels = {d.get("id"): d["label"] for d in f["pay"].get("discounts", [])}
    out = []
    for c in db.query(FormDiscountCode).filter_by(form_id=form.id).order_by(FormDiscountCode.id):
        used = formsvc.code_uses(db, c)
        out.append({"id": c.id, "code": c.code, "discount_id": c.discount_id, "discount": labels.get(c.discount_id, "(descuento eliminado)"), "max_uses": c.max_uses, "used": used, "left": max(0, c.max_uses - used)})
    return out


@router.get("/events/{event_id}/forms/{form_id}/discount-codes")
def list_codes(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    return _code_rows(db, _get_form(db, event, form_id))


@router.post("/events/{event_id}/forms/{form_id}/discount-codes")
def create_codes(event_id: int, form_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Crea códigos para un descuento «con código»: `shared` = UN código válido `max_uses` veces (ej. 3000 y luego deja de servir);
    `unique` = `count` códigos distintos de un solo uso (uno por persona)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    disc = _discount_of(form, str(data.get("discount_id") or ""))
    mode = data.get("mode")
    if db.query(FormDiscountCode).filter_by(form_id=form.id).count() >= MAX_CODES_PER_FORM:
        raise HTTPException(status_code=400, detail=f"Un formulario admite hasta {MAX_CODES_PER_FORM} códigos")

    def number(key, lo, hi, what):
        try:
            n = int(data.get(key))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{what}: escribe un número")
        if not lo <= n <= hi:
            raise HTTPException(status_code=400, detail=f"{what}: entre {lo} y {hi:,}".replace(",", "."))
        return n

    def fresh(prefix=""):
        while True:
            code = prefix + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8 - len(prefix) if len(prefix) < 6 else 4))
            if not db.query(FormDiscountCode).filter_by(form_id=form.id, code=code).first() and code not in seen:
                seen.add(code)
                return code
    seen: set = set()
    made = []
    if mode == "shared":
        uses = number("max_uses", 1, 1_000_000, "Cuántas veces se puede usar")
        custom = formsvc.normalize_code(data.get("code"))
        if custom and not re.fullmatch(r"[A-Z0-9_-]{3,40}", custom):
            raise HTTPException(status_code=400, detail="El código solo puede llevar letras, números, guion y guion bajo (3 a 40 caracteres)")
        if custom and db.query(FormDiscountCode).filter_by(form_id=form.id, code=custom).first():
            raise HTTPException(status_code=409, detail="Ese código ya existe en este formulario")
        made.append(FormDiscountCode(form_id=form.id, discount_id=disc["id"], code=custom or fresh(), max_uses=uses))
    elif mode == "unique":
        count = number("count", 1, 5000, "Cuántos códigos")
        prefix = re.sub(r"[^A-Z0-9]", "", str(data.get("prefix") or "").upper())[:6]
        made = [FormDiscountCode(form_id=form.id, discount_id=disc["id"], code=fresh(prefix), max_uses=1) for _ in range(count)]
    else:
        raise HTTPException(status_code=400, detail="Elige si es un código con varios usos o códigos de un solo uso")
    db.add_all(made)
    db.commit()
    return {"created": len(made), "codes": [c.code for c in made[:50]]}


@router.delete("/events/{event_id}/forms/{form_id}/discount-codes/{code_id}")
def delete_code(event_id: int, form_id: int, code_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    code = db.query(FormDiscountCode).filter_by(id=code_id, form_id=form.id).first()
    if not code:
        raise HTTPException(status_code=404, detail="Código no encontrado")
    if db.query(FormSubmission).filter(FormSubmission.discount_code_id == code.id).first():
        raise HTTPException(status_code=409, detail="Ese código ya se usó: no se puede borrar (queda como registro). Si no quieres que se use más, quita el descuento del diseño.")
    db.delete(code)
    db.commit()
    return {"message": "Código eliminado"}


@router.get("/events/{event_id}/forms/{form_id}/discount-codes/export")
def export_codes(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Excel con todos los códigos y su uso, para repartirlos."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Códigos"
    ws.append(["Código", "Descuento", "Usos permitidos", "Usos", "Disponibles"])
    for c in _code_rows(db, form):
        ws.append([c["code"], c["discount"], c["max_uses"], c["used"], c["left"]])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2C3E50")
    for i, w in enumerate((18, 30, 16, 8, 12), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return heavy.workbook_response(wb, f"codigos_{form.slug}.xlsx")


@router.get("/form-id-docs")
def form_id_docs(staff: StaffUser = Depends(STAFF)):
    """Tipos de documento de identidad que se pueden ofrecer en un campo (con su regla de validación)."""
    return formlib.id_docs_public()


@router.get("/events/{event_id}/form-templates")
def list_templates(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    rows = db.query(SavedFormTemplate).filter_by(tenant_id=event.tenant_id).order_by(SavedFormTemplate.name).all()
    return [{"id": t.id, "name": t.name, "fields": len(json.loads(t.design_json)["fields"])} for t in rows]


@router.post("/events/{event_id}/forms/{form_id}/save-as-template")
def save_template(event_id: int, form_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="Ponle un nombre a la plantilla")
    tpl = db.query(SavedFormTemplate).filter_by(tenant_id=event.tenant_id, name=name).first()
    if tpl:
        tpl.design_json = form.design_json          # mismo nombre: se actualiza
    else:
        tpl = SavedFormTemplate(tenant_id=event.tenant_id, name=name, design_json=form.design_json)
        db.add(tpl)
    db.commit()
    return {"id": tpl.id, "name": tpl.name}


@router.delete("/events/{event_id}/form-templates/{template_id}")
def delete_template(event_id: int, template_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    tpl = db.query(SavedFormTemplate).filter_by(id=template_id, tenant_id=event.tenant_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    db.delete(tpl)
    db.commit()
    return {"message": "Plantilla eliminada de la librería"}


@router.post("/events/{event_id}/forms-upload-image")
def upload_image(event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="Usa una imagen PNG, JPG, WEBP o GIF")
    content = file.file.read(8_000_001)
    if len(content) > 8_000_000:
        raise HTTPException(status_code=400, detail="La imagen pesa más de 8 MB")
    from app import safe_limits
    try:
        safe_limits.check_design_image(content, ext)      # I6: tamaño, píxeles y formato real (no solo la extensión)
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    name = f"{secrets.token_hex(16)}{ext}"
    get_storage().put(badge_asset_key(event.tenant_id, name), content)
    return {"storage_path": f"{event.tenant_id}/{name}"}


# ------------------------------------------------------------------ respuestas y archivos
def _column_defs(design: dict) -> list:
    """(id, etiqueta) de los campos que guardan datos, en el orden en que aparecen en el formulario."""
    out = []
    for row in design["rows"]:
        for fid in row["items"]:
            f = design["fields"][fid]
            if f["type"] in formlib.INPUT_TYPES or f["type"] == formlib.COMPANIONS_TYPE:
                out.append((fid, f["label"], f["type"]))
                if len(f.get("doc_types") or []) > 1:
                    out.append((fid + "__tipo", f"{f['label']} — tipo de documento", "text_short"))
    return out


def _display(value):
    if isinstance(value, list) and value and isinstance(value[0], dict):      # acompañantes: «3: Ana Ruiz / a@x.com; Luis Paz; …»
        return f"{len(value)}: " + "; ".join(" / ".join(str(v) for v in d.values() if v) for d in value)
    if isinstance(value, dict):
        return value.get("filename", "")
    if isinstance(value, list):
        return ", ".join(value)
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return "" if value is None else value


@router.get("/events/{event_id}/forms/{form_id}/submissions")
def list_submissions(event_id: int, form_id: int, include_tests: bool = True, page: int = 1, page_size: int = formlib.ANSWERS_DEFAULT_PAGE_SIZE, q: str = "", quota: str = "",
                     db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Respuestas paginadas en el servidor (más recientes primero). `page_size`: 20, 50 o 100 (otro valor: 50; más de 100: 100). `q`: cédula (inicio) o nombre (inicio de cada palabra,
    sin tildes ni mayúsculas; ver `formlib.answers_parse_query`). `quota`: id de una regla de cupo (mismas llaves `quota_keys` con que se cuenta el cupo).
    `total` = con los filtros; `total_all` = todas las visibles (con o sin pruebas según `include_tests`), sin buscador ni cupo."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    design = formsvc.get_design(form)
    base = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed")
    if not include_tests:
        base = base.filter(FormSubmission.is_test == False)  # noqa: E712
    total_all = base.count()
    rules = formsvc.quota_rules(form)
    quotas = []
    filtered = base
    if rules:
        if db.query(FormSubmission.id).filter(FormSubmission.form_id == form.id, FormSubmission.quota_keys == None).first():  # noqa: E711
            formsvc.rebuild_quota_keys(db, form, rules)
            db.commit()
        groups = formlib.answers_quota_groups(rules, design)
        cols = [func.count(FormSubmission.id).filter(func.strpos(FormSubmission.quota_keys, f"|{formsvc.rule_sig(r)}|") > 0) for r in rules]
        counts = base.with_entities(*cols).one()
        quotas = [{"id": r["id"], "label": r.get("label") or r["id"], "group": groups[r["id"]], "count": counts[i]} for i, r in enumerate(rules)]
        if quota:
            rule = next((r for r in rules if r["id"] == quota), None)
            if rule is None:
                raise HTTPException(status_code=400, detail="Ese cupo ya no existe en el formulario")
            filtered = filtered.filter(func.strpos(FormSubmission.quota_keys, f"|{formsvc.rule_sig(rule)}|") > 0)
    parsed = formlib.answers_parse_query(q)
    if parsed is None:      # sin buscador: todo en SQL (conteo + OFFSET/LIMIT)
        total = filtered.count()
        pg = formlib.answers_paging(total, page, page_size)
        rows = filtered.order_by(FormSubmission.id.desc()).offset(pg["offset"]).limit(pg["page_size"]).all()
    else:
        # La búsqueda sin tildes/mayúsculas y por inicio de palabra no se puede expresar con ILIKE (las tildes), ni hay `unaccent` garantizado en Neon: se filtra en Python
        # leyendo solo (id, data_json, person_id) de las filas ya filtradas en SQL (con ~5.000 inscripciones son decenas de ms) y luego se trae la página completa.
        fields = formlib.answers_search_fields(design)
        hits = []
        for sid, raw, pid in filtered.with_entities(FormSubmission.id, FormSubmission.data_json, FormSubmission.person_id).order_by(FormSubmission.id.desc()).yield_per(1000):
            try:
                data = json.loads(raw or "{}")
            except ValueError:
                continue
            if formlib.answers_match(parsed, data, pid, fields):
                hits.append(sid)
        total = len(hits)
        pg = formlib.answers_paging(total, page, page_size)
        ids = hits[pg["offset"]:pg["offset"] + pg["page_size"]]
        rows = base.filter(FormSubmission.id.in_(ids)).order_by(FormSubmission.id.desc()).all() if ids else []
    paid = _approved_by_submission(db, form, [s.id for s in rows])
    known = formsvc.known_before(db, form, rows)
    return {"has_payment": bool(formlib.payment_field(design)), "columns": [{"id": i, "label": l, "type": t} for i, l, t in _column_defs(design)],
            "total": total, "total_all": total_all, "page": pg["page"], "page_size": pg["page_size"], "pages": pg["pages"], "quotas": quotas, "rows": [
        {"id": s.id, "created_at": to_local(s.created_at).strftime("%Y-%m-%d %H:%M:%S"), "is_test": s.is_test, "fed": s.fed, "known": s.id in known, "source": s.source or "",
         "paid": paid[s.id].amount_cents // 100 if s.id in paid else None, "data": {k: _display(v) for k, v in json.loads(s.data_json).items()}} for s in rows]}


@router.post("/events/{event_id}/forms/{form_id}/unify-values")
def unify_values(event_id: int, form_id: int, payload: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Unifica un campo que define cupos en las inscripciones ya guardadas: «Bogota», «BOGOTÁ» y los alias que se indiquen pasan al valor escrito en la regla («Bogotá»). El reporte,
    las respuestas y el conteo de cupos quedan con el mismo valor. Cuerpo: `{"field": id del campo, "aliases": {"Bogotá, D.C.": "Bogotá"}, "apply": false}`. Sin `apply` solo informa
    (cuántas se corregirían y por cuál valor, sin nombres ni cédulas). Con `apply` corrige y recalcula las llaves de cupo, con el formulario bloqueado para que ningún envío se cruce.
    Solo cambia el campo indicado y solo si coincide EXACTO (sin tildes/mayúsculas) con un valor de las reglas o con un alias dado; lo demás no se toca. Repetirlo no cambia nada."""
    from app import value_unify
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    design = formsvc.get_design(form)
    field_id = str(payload.get("field") or "")
    rules = formsvc.quota_rules(form)
    canon = value_unify.canonical_values(rules, field_id)
    if field_id not in design["fields"] or not canon:
        raise HTTPException(status_code=400, detail="Ese campo no define cupos en este formulario")
    try:
        aliases = value_unify.alias_map(payload.get("aliases") or {}, canon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    do_apply = payload.get("apply") is True
    db.query(WebForm.id).filter(WebForm.id == form.id).with_for_update().first()
    rows = db.query(FormSubmission.id, FormSubmission.data_json, FormSubmission.fed).filter(FormSubmission.form_id == form.id, FormSubmission.is_test == False).all()  # noqa: E712
    changes, unresolved, batch, fed_changed = {}, {}, [], 0
    for sid, raw, fed in rows:
        data = json.loads(raw or "{}")
        old = data.get(field_id)
        if not isinstance(old, str) or not old.strip():
            continue
        new = value_unify.resolve(old, canon, aliases)
        if new is None:
            unresolved[old.strip()] = unresolved.get(old.strip(), 0) + 1
        elif new != old:
            changes[(old, new)] = changes.get((old, new), 0) + 1
            fed_changed += 1 if fed else 0
            data[field_id] = new
            batch.append({"id": sid, "data_json": json.dumps(data), "quota_keys": formsvc.quota_keys_for(rules, data)})
    if do_apply and batch:
        for i in range(0, len(batch), 500):
            db.bulk_update_mappings(FormSubmission, batch[i:i + 500])
        formsvc.invalidate_held()
    db.commit()
    known = set(canon.values())
    return {"applied": do_apply and bool(batch), "changed": len(batch), "already_ok": sum(1 for _, raw, _f in rows if json.loads(raw or "{}").get(field_id) in known),
            "changes": [{"from": a, "to": b, "count": n} for (a, b), n in sorted(changes.items(), key=lambda x: -x[1])],
            "unresolved": [{"value": v, "count": n} for v, n in sorted(unresolved.items(), key=lambda x: -x[1])], "already_in_base": fed_changed}


@router.post("/events/{event_id}/forms/{form_id}/align-to-base")
def align_to_base(event_id: int, form_id: int, payload: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Lleva un campo con cupos de las inscripciones al valor que la BASE DEL EVENTO tiene para esa persona (p. ej. la ciudad asignada). Sirve cuando alguien escribió otra ciudad
    (un pueblo, o una ciudad que no tiene cupo) y el cupo la contó donde no era. Cuerpo: `{"field": id del campo (vinculado a un campo del evento), "apply": false, "detail": false,
    "not_in_base_label": "texto"}`. Cambia inscripciones reales de personas que están en la base y cuyo valor en la base es uno de los valores de los cupos de ese campo; sin valor o con
    un valor sin cupo no se toca. Con `keep_not_in_base` ({\"cédula\": \"valor de un cupo\"}) quienes no están en la base y se listan quedan con ESE valor (cuentan en su cupo; decisión explícita del cliente). Si se da `not_in_base_label`, las inscripciones de personas que NO están en la base quedan con ese texto (dejan de contar en cualquier cupo). Las marcas de
    «Personas ya registradas» nunca se tocan (su ciudad la dio quien cargó la lista). **Nunca deja un cupo por encima de su límite**: si alguna corrección lo haría, no aplica nada y
    lo informa (`would_exceed`, 409 al aplicar) salvo que se pida expresamente `allow_over: true`. Sin `apply` solo informa; con `detail` lista cédula, valor actual y nuevo."""
    from app import value_unify
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    design = formsvc.get_design(form)
    field_id = str(payload.get("field") or "")
    field = design["fields"].get(field_id) or {}
    rules = formsvc.quota_rules(form)
    canon = value_unify.canonical_values(rules, field_id)
    if not canon or not field.get("key"):
        raise HTTPException(status_code=400, detail="Ese campo no define cupos o no está vinculado a un campo de la base del evento")
    src_event = formsvc.source_event_id(form)
    if not src_event:
        raise HTTPException(status_code=400, detail="Este formulario no toma sus datos de la base de un evento")
    label = " ".join(str(payload.get("not_in_base_label") or "").split())[:100]
    keep_map = {str(k).strip(): v for k, v in (payload.get("keep_not_in_base") or {}).items()} if isinstance(payload.get("keep_not_in_base"), dict) else {}
    do_apply = payload.get("apply") is True
    db.query(WebForm.id).filter(WebForm.id == form.id).with_for_update().first()
    rows = db.query(FormSubmission.id, FormSubmission.person_id, FormSubmission.data_json).filter(
        FormSubmission.form_id == form.id, FormSubmission.is_test == False, FormSubmission.person_id != None,  # noqa: E712,E711
        or_(FormSubmission.source == None, FormSubmission.source.notin_(formsvc.MARK_SOURCES))).all()  # noqa: E711
    pids = sorted({r[1] for r in rows})
    base_value, in_base = {}, set()
    for i in range(0, len(pids), 1000):
        part = pids[i:i + 1000]
        attendees = {r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == src_event, EventAttendee.user_id.in_(part))}
        for uid, extras in db.query(User.id, User.extra_fields).filter(User.tenant_id == event.tenant_id, User.id.in_(attendees)):
            in_base.add(uid)
            try:
                base_value[uid] = (json.loads(extras) if extras else {}).get(field["key"])
            except (ValueError, TypeError):
                base_value[uid] = None
    batch, changes, detail, skipped = [], {}, [], {"not_in_base": 0, "base_empty": 0, "base_without_quota": 0}
    already_ok, marked, delta = 0, 0, {r["id"]: 0 for r in rules}

    def change(sid, pid, data, old, new):
        nonlocal marked
        old_label = (old or "").strip() if isinstance(old, str) and old.strip() else "(vacío)"
        changes[(old_label, new)] = changes.get((old_label, new), 0) + 1
        if payload.get("detail") is True:
            detail.append({"id": pid, "from": old_label, "to": new})
        new_data = {**data, field_id: new}
        for r in rules:
            delta[r["id"]] += int(formsvc.quota_match(r, new_data)) - int(formsvc.quota_match(r, data))
        batch.append({"id": sid, "data_json": json.dumps(new_data), "quota_keys": formsvc.quota_keys_for(rules, new_data)})

    for sid, pid, raw in rows:
        data = json.loads(raw or "{}")
        old = data.get(field_id)
        if pid not in in_base:
            skipped["not_in_base"] += 1
            keep = value_unify.resolve(keep_map.get(pid), canon, {}) if pid in keep_map else None
            target = keep or label
            if target and old != target:
                marked += 1
                change(sid, pid, data, old, target)
            continue
        want = value_unify.resolve(base_value.get(pid), canon, {})
        if want is None:
            skipped["base_empty" if not str(base_value.get(pid) or "").strip() else "base_without_quota"] += 1
            continue
        if old == want:
            already_ok += 1
            continue
        change(sid, pid, data, old, want)
    used = formsvc.quota_counts(db, form, rules)
    would_exceed = [{"quota": r["label"], "limit": r["limit"], "used": used[r["id"]], "after": used[r["id"]] + delta[r["id"]]} for r in rules
                    if delta[r["id"]] > 0 and used[r["id"]] + delta[r["id"]] > r["limit"]]
    allow_over = payload.get("allow_over") is True     # decisión explícita del cliente de pasarse del cupo; siempre queda dicho en `would_exceed`
    if do_apply and would_exceed and not allow_over:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se aplicó nada: " + "; ".join(f"«{w['quota']}» quedaría en {w['after']} de {w['limit']}" for w in would_exceed))
    if do_apply and batch:
        for i in range(0, len(batch), 500):
            db.bulk_update_mappings(FormSubmission, batch[i:i + 500])
        formsvc.invalidate_held()
    db.commit()
    out = {"applied": do_apply and bool(batch), "changed": len(batch), "moved_to_base": len(batch) - marked, "marked_not_in_base": marked, "already_ok": already_ok, "skipped": skipped,
           "would_exceed": would_exceed, "quota_change": [{"quota": r["label"], "change": delta[r["id"]]} for r in rules if delta[r["id"]]],
           "changes": [{"from": a, "to": b, "count": n} for (a, b), n in sorted(changes.items(), key=lambda x: -x[1])]}
    if payload.get("detail") is True:
        out["detail"] = detail
    return out


@router.delete("/events/{event_id}/forms/{form_id}/submissions/{submission_id}")
def delete_submission(event_id: int, form_id: int, submission_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Fase 3: borrar UNA inscripción es de admin+ (antes coordinador) y queda en `audit_actions` (id de la inscripción y del formulario, sin datos de la persona). Un formulario archivado conserva
    todas sus respuestas: no se borran desde aquí."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    sub = db.query(FormSubmission).filter_by(id=submission_id, form_id=form.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    _not_archived(form)
    audit_actions.record(db, staff, "delete", "form_submission", sub.id, None, f"formulario {form.id}, evento {event.id}")
    for v in json.loads(sub.data_json).values():
        if isinstance(v, dict) and v.get("stored"):
            get_storage().delete(form_file_key(event.tenant_id, form.id, v["stored"]))
    db.query(FormPayment).filter(FormPayment.submission_id == sub.id).update({"submission_id": None}, synchronize_session=False)
    db.delete(sub)
    formsvc.invalidate_held()
    db.commit()
    return {"message": "Inscripción eliminada (si tenía un pago, ese registro financiero se conserva)"}


@router.get("/events/{event_id}/forms/{form_id}/files/{submission_id}/{field_id}")
def download_file(event_id: int, form_id: int, submission_id: int, field_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    sub = db.query(FormSubmission).filter_by(id=submission_id, form_id=form.id).first()
    info = json.loads(sub.data_json).get(field_id) if sub else None
    if not isinstance(info, dict) or not info.get("stored"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return get_storage().response(form_file_key(event.tenant_id, form.id, info["stored"]), filename=info.get("filename") or os.path.basename(info["stored"]))


@router.get("/events/{event_id}/forms/{form_id}/report")
def report(event_id: int, form_id: int, include_tests: bool = False, request: Request = None, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Reporte Excel del formulario (mismas convenciones que `app/reports.py`: título arriba, encabezado oscuro,
    autofiltro). Por defecto SIN las inscripciones de prueba."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    design = formsvc.get_design(form)
    cols = _column_defs(design)
    q = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed")
    if not include_tests:
        q = q.filter(FormSubmission.is_test == False)  # noqa: E712
    subs = q.order_by(FormSubmission.id).all()
    has_pay = bool(formlib.payment_field(design))
    paid = _approved_by_submission(db, form) if has_pay else {}
    known = formsvc.known_before(db, form, subs)
    wb = Workbook()
    ws = wb.active
    ws.title = "Inscripciones"
    ws.append([f"{form.name} — {event.name} ({event.event_code})"])
    ws["A1"].font = Font(bold=True, size=13, color="0A0E2E")
    headers = ["N°", "Fecha", "Hora"] + [l for _, l, _ in cols] + ["Origen", "Prueba", "Persona en la base antes de inscribirse", "Cargada a la base del evento"] + (["Monto pagado (COP)", "Referencia de pago", "Método de pago", "ID transacción Wompi", "Reglas y descuentos", "Reembolsado (COP)", "Comisión Wompi estimada (COP)", "Neto estimado de comisión (COP)"] if has_pay else [])
    ws.append(headers)
    for c in ws[2]:
        c.font = Font(color="FFFFFF", bold=True)
        c.fill = PatternFill(start_color="0A0E2E", end_color="0A0E2E", fill_type="solid")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for n, s in enumerate(subs, start=1):
        data = json.loads(s.data_json)
        local = to_local(s.created_at)
        ws.append([n, local.strftime("%Y-%m-%d"), local.strftime("%H:%M:%S")] + [_display(data.get(fid)) for fid, _, _ in cols] + [s.source or "Directo", "Sí" if s.is_test else "No", ("Sí" if s.id in known else "No (nueva)") if formsvc.sub_person_id(design, s) else "Sin cédula", "Sí" if s.fed else "No"] + (_pay_cells(paid.get(s.id)) if has_pay else []))
    ws.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{max(ws.max_row, 2)}"
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 24 if i > 3 else 10
    ws.freeze_panes = "A3"
    return heavy.workbook_response(wb, f"Formulario_{form.slug}.xlsx")


def _approved_by_submission(db: Session, form: WebForm, submission_ids: Optional[list] = None) -> dict:
    """Pagos aprobados por inscripción. Con `submission_ids` solo los de esas inscripciones (la página de respuestas); sin ellos, todos (reportes)."""
    q = db.query(FormPayment).filter(FormPayment.form_id == form.id, FormPayment.status == "approved", FormPayment.submission_id != None)  # noqa: E711
    if submission_ids is not None:
        if not submission_ids:
            return {}
        q = q.filter(FormPayment.submission_id.in_(submission_ids))
    return {p.submission_id: p for p in q}


def _pay_cells(p: Optional[FormPayment]) -> list:
    if not p:
        return ["", "", "", "", "", "", "", ""]
    applied = "; ".join(f"{a['label']} ({a['effect']})" for a in json.loads(p.breakdown_json or "{}").get("applied", []))
    return [p.amount_cents // 100, p.reference, p.payment_method or "", p.transaction_id or "", applied, (p.refunded_cents or 0) // 100,
            _fee_cop(p), _net_cop(p)]


def _fee_cop(p: FormPayment) -> int:
    """Comisión Wompi ESTIMADA de un pago, en pesos (ver wompi.estimate_fee)."""
    return wompi.estimate_fee(p.amount_cents, p.payment_method or "") // 100


def _net_cop(p: FormPayment) -> int:
    """Lo que queda de un pago aprobado: pagado − reembolsado − comisión estimada (la comisión no se devuelve al reembolsar)."""
    return p.amount_cents // 100 - (p.refunded_cents or 0) // 100 - _fee_cop(p)


def _auto_refund_possible(p: FormPayment) -> bool:
    """¿Hay reembolso automático por API para este pago? Tarjeta (anulación) siempre; otros medios solo con la API V2 (sandbox)."""
    if (p.payment_method or "").upper() == "CARD":
        return True
    cfg = wompi.config(p.is_test)
    return bool(cfg and wompi.refunds_v2_enabled(cfg))


def _auto_partial_possible(p: FormPayment) -> bool:
    """Reembolso parcial automático: solo con la API V2 y fuera de tarjeta (la anulación de tarjeta es solo por el valor completo)."""
    if (p.payment_method or "").upper() == "CARD":
        return False
    return _auto_refund_possible(p)


def _review_reason(p: FormPayment, confirmed_people: set) -> str:
    """C5: motivo visible de por qué un pago aprobado necesita revisión humana ('' si no). Pago aprobado sin inscripción: se conciliaba a mano; si la persona ya
    quedó inscrita con otro pago es un posible doble cobro (reembolsar uno)."""
    if p.status != "approved" or p.submission_id or (p.refunded_cents or 0):
        return ""
    if p.person_id and p.person_id in confirmed_people:
        return "Posible doble cobro: la persona ya está inscrita con otro pago. Reembolsa este."
    return "Aprobado sin inscripción: confirma con la persona o reembolsa."


def _pay_label(p: FormPayment) -> str:
    if p.status == "pending" and p.created_at < utcnow() - formsvc.PENDING_HOLD:
        return "abandoned"      # pendiente y ya pasó el tiempo de espera: la persona no terminó de pagar
    return p.status


# ------------------------------------------------------------------ pagos (campo «Pago», Wompi)
@router.get("/events/{event_id}/forms/{form_id}/payments")
def list_payments(event_id: int, form_id: int, include_tests: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Pagos del formulario con su referencia (evento + formulario + inscripción): la conciliación por evento vive aquí, no
    en el dashboard de Wompi. `orphan` = aprobado pero sin inscripción (revisar a mano)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    q = db.query(FormPayment).filter(FormPayment.form_id == form.id)
    if not include_tests:
        q = q.filter(FormPayment.is_test == False)  # noqa: E712
    rows = q.order_by(FormPayment.id.desc()).limit(2000).all()
    paid = [p for p in rows if p.status in ("approved", "refunded")]
    confirmed_people = {r[0] for r in db.query(FormSubmission.person_id).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed", FormSubmission.person_id != None).all()}  # noqa: E711
    refunds = {}
    for r in db.query(FormRefund).filter(FormRefund.payment_id.in_([p.id for p in rows] or [0])).order_by(FormRefund.id):
        refunds.setdefault(r.payment_id, []).append(r)
    return {
        "total_cop": (sum(p.amount_cents for p in paid) - sum(p.refunded_cents or 0 for p in paid)) // 100, "approved": len(paid),
        "wompi_status": wompi.service_status(), "fees_cop": sum(_fee_cop(p) for p in paid),
        "net_after_fees_cop": sum(_net_cop(p) for p in paid),
        "refunded_cop": sum(p.refunded_cents or 0 for p in paid) // 100,
        "rows": [{"id": p.id, "reference": p.reference, "amount": p.amount_cents // 100, "status": _pay_label(p), "method": p.payment_method or "", "transaction_id": p.transaction_id or "",
                  "person_id": p.person_id or "", "is_test": p.is_test, "submission_id": p.submission_id, "orphan": p.status in ("approved", "refunded") and not p.submission_id and not (p.refunded_cents or 0),
                  "review": _review_reason(p, confirmed_people),
                  "fee": _fee_cop(p) if p.status in ("approved", "refunded") else 0,
                  "net": _net_cop(p) if p.status in ("approved", "refunded") else 0,
                  "refunded": (p.refunded_cents or 0) // 100, "remaining": (p.amount_cents - (p.refunded_cents or 0)) // 100 if p.status == "approved" else 0,
                  "auto_refund": p.status == "approved" and _auto_refund_possible(p) and not p.refunded_cents, "auto_partial": p.status == "approved" and _auto_partial_possible(p),
                  "refunds": [{"amount": r.amount_cents // 100, "kind": r.kind, "status": r.status, "reason": r.reason, "note": r.note or "", "at": r.created_at.strftime("%Y-%m-%d %H:%M"), "id": r.id, "response": (r.wompi_response or "")[:600]} for r in refunds.get(p.id, [])],
                  "created_at": to_local(p.created_at).strftime("%Y-%m-%d %H:%M:%S"), "confirmed_at": to_local(p.confirmed_at).strftime("%Y-%m-%d %H:%M:%S") if p.confirmed_at else "",
                  "applied": json.loads(p.breakdown_json or "{}").get("applied", [])} for p in rows]}


# ------------------------------------------------------------------ base para pre-llenar y invitaciones
@router.post("/events/{event_id}/forms/{form_id}/people")
def upload_people(event_id: int, form_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Sube (Excel/CSV) la base que pre-llenará SOLO este formulario (fuente «base subida aparte»); reemplaza la anterior."""
    from app.routers.api import _read_roster_rows, _ID_KEYS, _normalize_optional_key
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    header, rows = _read_roster_rows(file.filename, file.file.read())
    id_col = next((k for k in header if formsvc.COLUMN_TO_KEY.get(k) == "id"), None)
    if not id_col:
        raise HTTPException(status_code=400, detail="El archivo necesita una columna de cédula (id / cédula)")
    db.query(FormPerson).filter(FormPerson.form_id == form.id).delete()
    seen, count = set(), 0
    for row in rows:
        person = {}
        for col, value in row.items():
            key = formsvc.COLUMN_TO_KEY.get(col) or _normalize_optional_key(col)
            if key and str(value).strip():
                person[key] = str(value).strip()
        pid = person.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            db.add(FormPerson(form_id=form.id, person_id=pid, data_json=json.dumps(person)))
            count += 1
    settings = formsvc.get_settings(form)
    settings["prefill"]["source"] = "upload"
    form.settings_json = json.dumps(settings)
    db.commit()
    return {"people": count, "message": f"{count} personas cargadas para pre-llenar este formulario"}


@router.get("/events/{event_id}/forms/{form_id}/invites")
def invites_status(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    rows = db.query(FormInvite).filter_by(form_id=form.id).all()
    return {"total": len(rows), "sent": sum(1 for r in rows if r.sent_at), "used": sum(1 for r in rows if r.used_at), "source_people": len(formsvc.source_people(db, form))}


@router.post("/events/{event_id}/forms/{form_id}/invites/send")
def send_invites(event_id: int, form_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Genera el enlace personal de cada persona de la fuente y lo manda por correo (a quien tenga correo) en segundo
    plano, con avance (`GET /api/bulk_jobs/{id}`). `only_unsent` (por defecto sí) no reenvía a quien ya lo recibió."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    if formsvc.get_settings(form)["prefill"]["mode"] != "invite":
        raise HTTPException(status_code=400, detail="Este formulario no usa enlaces personalizados por invitado (cámbialo en su configuración)")
    if bulk_jobs.active_job(db, event_id):
        raise HTTPException(status_code=409, detail="Ya hay un proceso en curso para este evento — espera a que termine")
    only_unsent = data.get("only_unsent", True)
    base = _base_url(request)
    job_id = bulk_jobs.create_job(db, event_id, staff.id)
    form_id_, slug, ev_id, ev_name, name = form.id, form.slug, event.id, event.name, form.name

    def work(job_db, reporter):
        f = job_db.query(WebForm).filter(WebForm.id == form_id_).first()
        people = formsvc.source_people(job_db, f)
        total = len(people)
        sent = skipped = failed = 0
        problems = []
        for i, p in enumerate(people, start=1):
            reporter(f"Enviando invitaciones ({i} de {total})", i, total)
            pid = str(p.get("id") or "")
            inv = job_db.query(FormInvite).filter_by(form_id=form_id_, person_id=pid).first()
            if not inv:
                inv = FormInvite(form_id=form_id_, person_id=pid, token=secrets.token_urlsafe(18), email=(p.get("email") or None))
                job_db.add(inv)
                job_db.commit()
            if not p.get("email"):
                skipped += 1
                continue
            if only_unsent and inv.sent_at:
                skipped += 1
                continue
            link = f"{base}/f/{ev_id}/{slug}?i={inv.token}"
            res = send_mail(p["email"], f"Tu inscripción — {ev_name}",
                            f"Hola {p.get('first_name') or ''}, te invitamos a completar tu inscripción a {ev_name} ({name}).\n\nAbre tu enlace personal (ya trae tus datos):\n{link}\n\nEs personal: no lo compartas.")
            if res.get("sent"):
                inv.sent_at = utcnow()
                job_db.commit()
                sent += 1
            else:
                failed += 1
                if len(problems) < 10:
                    problems.append(f"{p['email']}: {res.get('detail')}")
        return {"message": f"Invitaciones: {sent} enviadas, {skipped} omitidas (sin correo o ya enviadas), {failed} fallidas.", "sent": sent, "skipped": skipped, "failed": failed, "problems": problems}

    bulk_jobs.start(job_id, work)
    return {"background": True, "job_id": job_id}


# ------------------------------------------------------------------ analítica (módulo compartido, app/analytics.py)
def form_dashboard(db: Session, form: WebForm, include_tests: bool = False, net_fees: bool = False) -> dict:
    from collections import Counter
    from app import analytics as an

    design = formsvc.get_design(form)
    q_sub = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == "confirmed")
    q_evt = db.query(FormEvent).filter(FormEvent.form_id == form.id)
    if not include_tests:
        q_sub, q_evt = q_sub.filter(FormSubmission.is_test == False), q_evt.filter(FormEvent.is_test == False)  # noqa: E712
    subs = q_sub.order_by(FormSubmission.id).all()
    events = q_evt.all()
    views = {e.sid for e in events if e.kind == "view"}
    starts = {e.sid for e in events if e.kind == "start"}
    sent = {e.sid for e in events if e.kind == "submit"}
    abandoned = starts - sent
    durations = [(s.created_at - s.started_at).total_seconds() for s in subs if s.started_at and s.created_at >= s.started_at]

    state = formsvc.public_state(db, form)
    reason = {"cupo_lleno": "Cupo lleno", "cerrado": "Cerrado (manual o por fecha)", "finalizado": "Finalizado", "activo": "Abierto", "pruebas": "En pruebas"}[state]
    kpis = [
        an.kpi("Inscripciones", len(subs), "sin las de prueba" if not include_tests else "incluye pruebas", "good"),
        an.kpi("Estado", reason, "ahora mismo"),
        an.kpi("Visitas", len(views), "personas que abrieron el formulario"),
        an.kpi("Empezaron a llenarlo", len(starts), an.pct(len(starts), len(views)) + " de las visitas"),
        an.kpi("Lo enviaron", len(sent), an.pct(len(sent), len(views)) + " de las visitas (conversión)", "good"),
        an.kpi("Lo abandonaron", len(abandoned), an.pct(len(abandoned), len(starts)) + " de quienes empezaron", "warn" if abandoned else ""),
    ]
    if durations:
        durations.sort()
        kpis.append(an.kpi("Tiempo promedio", an.fmt_duration(sum(durations) / len(durations)), f"mediana {an.fmt_duration(durations[len(durations) // 2])}"))
    if form.capacity:
        kpis.append(an.kpi("Cupo", f"{len(subs) if include_tests else formsvc.real_submissions(db, form).count()} / {form.capacity}", "inscripciones reales / cupo", "warn" if formsvc.is_full(db, form) else ""))
    cf = next((fid for fid, f in design["fields"].items() if f["type"] == formlib.COMPANIONS_TYPE), None)
    if cf:
        total_c = sum(len(json.loads(x.data_json).get(cf) or []) for x in subs)
        kpis.append(an.kpi("Acompañantes", total_c, f"personas en total (inscritos + acompañantes): {len(subs) + total_c}"))
    if subs:
        known = formsvc.known_before(db, form, subs)
        has_id = sum(1 for x in subs if formsvc.sub_person_id(design, x))
        if has_id:
            kpis.insert(1, an.kpi("Ya estaban en la base", len(known), an.pct(len(known), len(subs)) + " de las inscripciones"))
            kpis.insert(2, an.kpi("Personas nuevas", has_id - len(known), "no estaban en la base del evento", "warn" if has_id - len(known) else ""))
        kpis.append(an.kpi("Última inscripción", an.fmt_local(subs[-1].created_at), "hora local"))

    charts = [an.time_series("timeline", "Inscripciones en el tiempo", [s.created_at for s in subs], label="Inscripciones"),
              an.hour_histogram("by_hour", "Inscripciones por hora del día", [s.created_at for s in subs], label="Inscripciones"),
              an.counter_chart("by_source", "¿De dónde llegaron? (enlaces con utm_source)", [s.source or "Directo" for s in subs], kind="pie", label="Inscripciones")]

    if formlib.payment_field(design):
        _payment_analytics(db, form, include_tests, kpis, charts, net_fees)

    # Campos con más y con menos respuesta (sobre las inscripciones, contando solo las que tenían el campo visible: aproximación por valor presente)
    if subs:
        answered = Counter()
        for s in subs:
            for fid, v in json.loads(s.data_json).items():
                if v not in (None, "", []):
                    answered[fid] += 1
        cols = _column_defs(design)
        rates = [(label, round(100 * answered.get(fid, 0) / len(subs))) for fid, label, _ in cols]
        if rates:
            rates.sort(key=lambda x: -x[1])
            charts.append(an.chart("response_rate", "Campos con más y menos respuesta (% de inscripciones que lo llenaron)", "bar", [r[0] for r in rates], [{"label": "% que respondió", "data": [r[1] for r in rates]}], horizontal=True,
                                   note="Un campo condicional solo lo ven algunos, por eso puede aparecer con menos respuestas."))
        # Distribución de cada campo marcado «genera estadísticas»
        for fid, label, kind in cols:
            f = design["fields"][fid]
            if not f.get("stats"):
                continue
            values = []
            for s in subs:
                v = json.loads(s.data_json).get(fid)
                if isinstance(v, list):
                    values += v
                elif v is True:
                    values.append("Sí")
                elif v is False:
                    values.append("No")
                elif isinstance(v, str) and kind in ("select", "radio", "checkbox", "number", "text_short", "email"):
                    values.append(v if kind != "email" else v.split("@")[-1])       # correo: por dominio, no por persona
            c = an.counter_chart(f"field_{fid}", f"{label}", values, kind="pie" if kind in ("select", "radio", "checkbox") else "bar", label="Inscripciones")
            if c:
                charts.append(c)
    return an.dashboard(f"Formulario: {form.name}", kpis, [c for c in charts if c])


def _payment_analytics(db: Session, form: WebForm, include_tests: bool, kpis: list, charts: list, net_fees: bool = False) -> None:
    """Ingresos del formulario (solo los pagos aprobados cuentan como ingreso) y cómo se resolvieron los intentos."""
    from collections import Counter, defaultdict
    from app import analytics as an

    q = db.query(FormPayment).filter(FormPayment.form_id == form.id)
    if not include_tests:
        q = q.filter(FormPayment.is_test == False)  # noqa: E712
    pays = q.order_by(FormPayment.id).all()
    if not pays:
        return
    pesos = lambda n: "$" + f"{n:,}".replace(",", ".")
    approved = [p for p in pays if p.status in ("approved", "refunded")]
    total = sum(p.amount_cents for p in approved) // 100
    refunded = sum(p.refunded_cents or 0 for p in approved) // 100
    failed = [p for p in pays if p.status in ("declined", "error", "voided")]
    abandoned = [p for p in pays if _pay_label(p) == "abandoned"]
    fees = sum(_fee_cop(p) for p in approved)
    if net_fees:
        kpis += [an.kpi("Comisión Wompi (estimada)", pesos(fees), "2,65 % + $700 + IVA por pago (QR 1 %); estimación según tu plan", "warn"),
                 an.kpi("Ingresos netos de comisión", pesos(total - refunded - fees), "aprobados − reembolsos − comisión estimada", "good")]
    kpis += [an.kpi("Ingresos (aprobados)", pesos(total), f"{len(approved)} pago(s) aprobado(s)", "good"),
             an.kpi("Pago promedio", pesos(total // len(approved) if approved else 0), "por inscripción pagada"),
             an.kpi("Pagos no completados", len(failed) + len(abandoned), f"{len(failed)} rechazados · {len(abandoned)} abandonados", "warn" if failed or abandoned else "")]
    if refunded:
        kpis += [an.kpi("Reembolsos", pesos(refunded), f"{sum(1 for p in approved if p.refunded_cents)} pago(s) reembolsado(s)", "warn"),
                 an.kpi("Ingresos netos", pesos(total - refunded), "aprobados menos reembolsos", "good")]
    orphans = sum(1 for p in pays if p.status == "approved" and not p.submission_id)
    if orphans:
        kpis.append(an.kpi("Pagos sin inscripción", orphans, "aprobados pero sin inscripción: revisar en la lista de pagos", "warn"))
    per_day = defaultdict(int)
    for p in approved:
        per_day[to_local(p.confirmed_at or p.created_at).strftime("%Y-%m-%d")] += (p.amount_cents // 100 - _fee_cop(p)) if net_fees else p.amount_cents // 100
    if per_day:
        days = sorted(per_day)
        charts.append(an.chart("revenue_by_day", "Ingresos por día (COP" + (", netos de comisión estimada)" if net_fees else ")"), "bar", days, [{"label": "Ingresos netos de comisión" if net_fees else "Ingresos aprobados", "data": [per_day[d] for d in days]}]))
    names = {"refunded": "Reembolsado", "approved": "Aprobado", "declined": "Rechazado", "error": "Error", "voided": "Anulado", "pending": "En espera", "abandoned": "Abandonado"}
    charts.append(an.counter_chart("payment_status", "Resultado de los intentos de pago", [names.get(_pay_label(p), _pay_label(p)) for p in pays], kind="pie", label="Pagos"))
    applied = Counter()
    for p in approved:
        for a in json.loads(p.breakdown_json or "{}").get("applied", []):
            applied[f"{a['label']} ({a['effect']})"] += 1
    if applied:
        charts.append(an.counter_chart("price_rules", "Reglas de precio y descuentos aplicados", list(applied.elements()), kind="bar", label="Pagos"))


@router.get("/events/{event_id}/forms/{form_id}/analytics")
def form_analytics(event_id: int, form_id: int, include_tests: bool = False, net_fees: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    return form_dashboard(db, _get_form(db, event, form_id), include_tests, net_fees)
