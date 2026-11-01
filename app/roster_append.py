"""«Solo agregar personas nuevas» a un evento (pista Eventos en curso, pedido A).

La carga normal (`_bulk_register_impl`) PISA los datos de quien ya existe y, con una cédula repetida en la hoja, deja la última fila. Este modo hace lo contrario y es una rama aparte
(la carga normal no se toca):
  * cédula YA inscrita en el evento -> no se toca nada (ni datos, ni foto, ni consentimiento, ni accesos): se cuenta como «ya existía»;
  * cédula que existe en el cliente pero no en este evento -> solo se la INSCRIBE en el evento (la persona queda tal cual estaba);
  * cédula nueva -> se crea la persona y su inscripción con lo que trae la hoja (lo que la hoja no trae queda vacío);
  * repetida dentro de la hoja -> se procesa la primera y las demás se cuentan;
  * columnas que no son un campo del evento -> se ignoran y se informan (nunca se crean campos ni categorías);
  * cédulas suprimidas (habeas data) -> no se recrean, como en la carga normal.
No estorba al registro en vivo: lotes de `APPEND_ROWS` (200) filas con un commit por lote (lo hace `app/bulk_steps.py`), consultas de solo lectura y un INSERT múltiple por lote, un SAVEPOINT
por fila si el lote falla, ningún bloqueo de tabla, ningún `UPDATE` sobre `events` salvo uno al final, y ninguna fila de `users` ya existente se modifica (se leen solo columnas sueltas).
Si el quiosco crea la misma cédula mientras corre la carga, el choque cuenta como «ya existía», no como error. Fotos (zip) no admitidas. Nada de datos personales en logs ni en el informe:
solo conteos y números de fila."""
import contextlib
import logging
import os
import re

from sqlalchemy.exc import SQLAlchemyError

from app import consent as consent_mod
from app import minors, roster_columns
from app.models import AuditConsentLog, EventAttendee, SuppressedPerson, User

log = logging.getLogger("golden.bulk_append")
APPEND_ROWS = int(os.getenv("BULK_APPEND_ROWS", "200"))          # filas por lote Y por commit
MAX_MESSAGES = 200                                                # observaciones con número de fila que se guardan; los conteos siempre son exactos
ZIP_REJECTED = "«Solo agregar personas nuevas» no admite fotos (zip): sube únicamente el archivo de la base (Excel o CSV)."
SOURCE_REJECTED = "«Solo agregar personas nuevas» no admite traer personas de otro evento: sube únicamente el archivo de la base (Excel o CSV)."
NEEDS_FILE = "Sube el archivo de la base (Excel o CSV) con las personas nuevas."
COUNTERS = ("created", "existing", "enrolled_existing", "duplicates", "suppressed", "errors", "warnings", "unknown_category_rows")


def new_state() -> dict:
    return {"counters": {k: 0 for k in COUNTERS}, "messages": [], "unknown_categories": []}


def duplicate_rows(row_infos: list) -> list:
    """Números de fila que repiten una cédula ya vista antes en la hoja (la primera es la que se procesa)."""
    seen, dup = set(), []
    for info in row_infos:
        ident = info["identificador"]
        if not ident:
            continue
        if ident in seen:
            dup.append(info["row_num"])
        seen.add(ident)
    return dup


def _note(state: dict, text: str) -> None:
    if len(state["messages"]) < MAX_MESSAGES:
        state["messages"].append(text)


def _lookups(db, event, ids: list, chunk: int) -> tuple:
    """(suprimidas, {cédula: ¿tiene rostro guardado?} de las que ya existen en el cliente, {cédula} ya inscritas en ESTE evento). Solo lectura, una consulta por cada `chunk` cédulas."""
    from app.routers.api import _chunks
    suppressed, known, enrolled = set(), {}, set()
    hash_by_id = {i: consent_mod.cedula_hash(i) for i in ids}
    id_by_hash = {}
    for i, h in hash_by_id.items():
        id_by_hash.setdefault(h, []).append(i)
    for part in _chunks(list(id_by_hash), chunk):
        for (h,) in db.query(SuppressedPerson.cedula_hash).filter(SuppressedPerson.tenant_id == event.tenant_id, SuppressedPerson.cedula_hash.in_(part)):
            suppressed.update(id_by_hash.get(h, []))
    for part in _chunks(ids, chunk):
        for uid, has_face in db.query(User.id, User.face_encoding.isnot(None)).filter(User.tenant_id == event.tenant_id, User.id.in_(part)):
            known[uid] = bool(has_face)
        for (uid,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part)):
            enrolled.add(uid)
    return suppressed, known, enrolled


def _apply(db, event, info: dict, header_columns: dict, birth_used: bool, dup_rows: set, state: dict, look: tuple, pending: list) -> None:
    """Una fila. No hace flush: eso lo decide quien la llama. La inscripción NO se agrega a la sesión: queda en `pending` y se agrega DESPUÉS de enviar a las personas nuevas (la llave foránea
    exige que la persona exista antes; sin relación entre los modelos, el orden de envío no es fiable)."""
    from app.routers.api import (_BIRTH_KEYS, _EMAIL_RE, _PHONE_RE, _clean_categories, _field_lookup, _normalize_optional_key, _truthy)
    suppressed, known, enrolled = look
    c, row_num, ident, row = state["counters"], info["row_num"], info["identificador"], info["clean_row"]
    if not ident:
        c["errors"] += 1
        _note(state, f"❌ Fila {row_num}: sin ID/cédula, se omitió esta fila.")
        return
    if row_num in dup_rows:
        c["duplicates"] += 1
        _note(state, f"ℹ️ Fila {row_num}: la cédula está repetida en la hoja; solo se procesó su primera aparición.")
        return
    if ident in suppressed:
        c["suppressed"] += 1
        _note(state, f"⚠️ Fila {row_num}: esta persona solicitó la supresión de sus datos — se omitió (no se volvió a crear).")
        return
    if ident in enrolled:
        c["existing"] += 1
        return                                                    # ya está en el evento: no se toca NADA de ella

    raw_categories = next((row[k] for k in ("categoria", "categorias", "categoría", "categorías") if row.get(k)), None)
    cats = _clean_categories(event, raw_categories, auto_add=False) if raw_categories else None          # solo las que el evento ya tiene: las demás se ignoran
    if raw_categories:
        known_cats = {k.lower() for k in event.get_categories()}
        missing = [x for x in (y.strip() for y in re.split(r"[,;|]", raw_categories)) if x and x.lower() not in known_cats]
        if missing:
            c["unknown_category_rows"] += 1
            for name in missing:
                if name not in state["unknown_categories"] and len(state["unknown_categories"]) < 20:
                    state["unknown_categories"].append(name)
    certificate = _truthy(row.get("certificado")) if row.get("certificado") else None

    if ident in known:                                            # existe en el cliente (otro evento): solo se inscribe aquí, sin tocar a la persona
        c["enrolled_existing"] += 1
        if known[ident] and not db.query(AuditConsentLog.id).filter(AuditConsentLog.tenant_id == event.tenant_id, AuditConsentLog.event_id == event.id, AuditConsentLog.user_id == ident).first():
            db.info.setdefault("faces_no_bump", set()).add((event.tenant_id, ident))          # sin aceptación en este evento no entra a la matriz: no hace falta reconstruirla
    else:
        nombres, _ = _field_lookup(row, header_columns, row_num, "nombres", "nombre")
        apellidos, _ = _field_lookup(row, header_columns, row_num, "apellidos", "apellido")
        correo, _ = _field_lookup(row, header_columns, row_num, "correo", "e-mail corporativo")
        telefono, _ = _field_lookup(row, header_columns, row_num, "telefono", "tel. celular")
        for ok, what in ((bool(nombres), "falta el nombre"), (bool(apellidos), "falta el apellido"), (not correo or bool(_EMAIL_RE.match(correo)), "el correo no parece válido"),
                         (not telefono or bool(_PHONE_RE.match(telefono)), "el teléfono tiene caracteres raros")):
            if not ok:
                c["warnings"] += 1
                _note(state, f"⚠️ Fila {row_num}: {what} (se guardó igual, revísalo).")
        birth_raw = next((row[k] for k in _BIRTH_KEYS if row.get(k)), "") if birth_used else ""
        birth = minors.parse_birth(birth_raw)
        if birth_raw and birth is None:
            c["warnings"] += 1
            _note(state, f"⚠️ Fila {row_num}: la fecha de nacimiento no es válida (usa AAAA-MM-DD, DD/MM/AAAA o una fecha de Excel).")
        user = User(id=ident, tenant_id=event.tenant_id, first_name=nombres, last_name=apellidos, role=row.get("cargo", ""), entity=row.get("entidad", "") or row.get("empresa", ""),
                    phone=telefono, email=correo, opt_1=row.get("tipo de asistente", "") or row.get("tipo_asistente", ""))
        if birth is not None:
            user.birth_date = birth
            user.is_biometric_enabled = not minors.is_minor(birth)
        user.set_extras({norm: (v or "").strip() for k, v in row.items() if (norm := _normalize_optional_key(k)) and (v or "").strip()})
        db.add(user)
        c["created"] += 1
    att = EventAttendee(event_id=event.id, user_id=ident, tenant_id=event.tenant_id, origin="base")
    if certificate is not None:
        att.certificate = certificate
    if cats:
        att.set_categories(cats)
    pending.append(att)


def _snapshot(state: dict) -> tuple:
    return dict(state["counters"]), len(state["messages"]), list(state["unknown_categories"])


def _restore(state: dict, snap: tuple) -> None:
    state["counters"] = dict(snap[0])
    del state["messages"][snap[1]:]
    state["unknown_categories"] = list(snap[2])


def run_step(db, event, staff, step: dict, row_infos: list, header_columns: dict, columns_report: dict, birth_used: bool, prepared: dict, state: dict, step_pos: int, step_end: int,
             row_total: int, progress=None) -> dict:
    """Procesa el grupo de filas de ESTE paso (≤ `APPEND_ROWS`). El commit lo hace quien llama (`app/bulk_steps.py`), junto con el avance de la tarea."""
    from app.routers.api import _LOOKUP_CHUNK
    ap = state.get("append") or new_state()
    dup_rows = set(prepared.get("dup_rows") or [])
    ids = list({i["identificador"] for i in row_infos if i["identificador"]})
    snap = _snapshot(ap)
    for isolate in (False, True):
        look = _lookups(db, event, ids, _LOOKUP_CHUNK)
        _restore(ap, snap)
        try:
            with (contextlib.nullcontext() if isolate else db.begin_nested()):
                pending = []
                for info in row_infos:
                    if not isolate:
                        _apply(db, event, info, header_columns, birth_used, dup_rows, ap, look, pending)
                        continue
                    row_snap = _snapshot(ap)
                    for attempt in (1, 2):
                        try:
                            one = []
                            with db.begin_nested():
                                _apply(db, event, info, header_columns, birth_used, dup_rows, ap, look, one)
                                db.flush()
                                db.add_all(one)
                                db.flush()
                            break
                        except SQLAlchemyError:
                            _restore(ap, row_snap)
                            if attempt == 1:          # carrera con el registro en vivo (la cédula apareció entre la consulta y el INSERT): se vuelve a mirar y se decide de nuevo, una vez
                                look = _lookups(db, event, [info["identificador"]], _LOOKUP_CHUNK)
                                continue
                            ap["counters"]["errors"] += 1
                            _note(ap, f"❌ Fila {info['row_num']}: no se pudo guardar esta fila.")
                if not isolate:
                    db.flush()
                    db.add_all(pending)
                    db.flush()
            break
        except SQLAlchemyError:
            if isolate:
                raise
            log.warning("carga «solo agregar»: un lote fue rechazado por la base; se repite fila por fila")
    db.info.pop("faces_no_bump", None)
    if progress:
        progress(f"Agregando personas ({step_end} de {row_total})", step_end, row_total)
    if step_end < row_total:
        return {"done": False, "state": {**state, "pos": step_end, "append": ap}}

    c = ap["counters"]
    if c["created"] + c["enrolled_existing"] and not event.roster_uploaded:
        event.roster_uploaded = True
    notes = []
    if ap["unknown_categories"]:
        notes.append(f"ℹ️ {c['unknown_category_rows']} fila(s) traían categorías que este evento no tiene (se ignoraron, no se crearon): {', '.join(ap['unknown_categories'])}.")
    for item in columns_report.get("unused", []):
        notes.append(f"ℹ️ Columna «{item['title']}» ignorada: {item['reason']}.")
    message = (f"Listo: {c['created']} personas nuevas creadas" + (f" y {c['enrolled_existing']} inscritas (ya existían en el cliente)" if c["enrolled_existing"] else "")
               + f"; {c['existing']} ya estaban en el evento (no se tocaron); {c['duplicates']} repetidas en la hoja; {c['errors']} con error.")
    report = {"created": c["created"], "enrolled_existing": c["enrolled_existing"], "existing": c["existing"], "duplicates": c["duplicates"], "suppressed": c["suppressed"],
              "errors": c["errors"], "warnings": c["warnings"], "columns_ignored": len(columns_report.get("unused", [])), "unknown_categories": ap["unknown_categories"]}
    return {"message": message, "count": c["created"] + c["enrolled_existing"], "errors": ap["messages"] + notes, "optional_labels": event.get_optional_labels(),
            "columns": columns_report, "append": report}
