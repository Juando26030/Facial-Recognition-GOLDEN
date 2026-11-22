"""Vista previa de una carga de la base de personas (21-nov-2026, pedido de Juan David; docs/25_INVENTARIO_POR_BASE.md): ANTES de cargar, además del resumen de siempre,
se muestran hasta 10 personas repartidas por todo el archivo (no solo las primeras) tal como quedarían en «Editar persona», y cómo cambia la base del evento.

Sirve para la carga normal (`normal`: pisa los datos de quien ya existe) y para «solo agregar personas nuevas» (`append`: no toca a nadie que ya esté). La base de dependientes
tiene la suya (app/dependents.py analyze). No escribe nada: solo consultas de lectura. Lo que se muestra es lo que la propia persona que carga trae en su archivo."""
from app import inv_assign_core as core
from app import consent as consent_mod
from app.models import EventAttendee, SuppressedPerson, User

FIXED = (("first_name", ("nombres", "nombre")), ("last_name", ("apellidos", "apellido")), ("role", ("cargo",)), ("entity", ("entidad", "empresa")),
         ("phone", ("telefono", "tel. celular")), ("email", ("correo", "e-mail corporativo")), ("opt_1", ("tipo de asistente", "tipo_asistente")))
CATEGORY_KEYS = ("categoria", "categorias", "categoría", "categorías")
BIRTH_KEYS = ("fecha de nacimiento", "fecha_nacimiento", "fecha nacimiento", "nacimiento", "birth_date")
CODE_KEYS = ("codigo", "código")


def _first(row: dict, keys) -> str:
    for k in keys:
        v = str(row.get(k) or "").strip()
        if v:
            return v
    return ""


def incoming_values(row: dict, birth_used: bool, code_enabled: bool) -> dict:
    """Lo que la carga guardaría de una fila, por clave de campo del evento (mismas columnas que lee la carga, app/routers/api.py)."""
    from app.routers.api import _normalize_optional_key
    out = {k: _first(row, keys) for k, keys in FIXED}
    out["categories"] = _first(row, CATEGORY_KEYS)
    if birth_used:
        out["birth_date"] = _first(row, BIRTH_KEYS)
    if code_enabled:
        out["code"] = _first(row, CODE_KEYS)
    for raw_key, value in row.items():
        norm = _normalize_optional_key(raw_key)
        if norm and str(value or "").strip():
            out[norm] = str(value).strip()
    return out


def current_values(user: User, attendee) -> dict:
    out = {k: (getattr(user, k, None) or "") for k, _ in FIXED}
    out["birth_date"] = user.birth_date.isoformat() if user.birth_date else ""
    out["categories"] = ", ".join(attendee.get_categories()) if attendee is not None and hasattr(attendee, "get_categories") else ""
    out["code"] = (attendee.code or "") if attendee is not None else ""
    out.update({k: str(v) for k, v in user.get_extras().items()})
    return out


def _field_list(db, event, labels: dict, unnamed: list) -> list:
    """(clave, etiqueta) en el orden de «Editar persona»; los campos nuevos que trae el archivo, al final."""
    from app.routers.parametros import field_configs_for_event
    fields = [(c["key"], c["label"]) for c in field_configs_for_event(db, event) if c["key"] not in ("certificate", "digital_contact")]
    have = {k for k, _ in fields}
    for key, label in sorted(labels.items(), key=lambda kv: int(kv[0].split("_")[1]) if kv[0].split("_")[-1].isdigit() else 0):
        if key not in have:
            fields.append((key, f"{label} (campo nuevo)"))
            have.add(key)
    for key in unnamed:
        if key not in have:
            fields.append((key, f"{key} (campo nuevo: te preguntaremos el nombre al cargar)"))
    if "categories" not in have:
        fields.append(("categories", "Categoría"))
    return fields


def build(db, event, prepared: dict, mode: str) -> dict:
    from app.routers.api import _LOOKUP_CHUNK, _chunks, _extract_identificador
    rows, header = prepared["rows"], prepared["header_columns"]
    infos = []
    for row_num, row in enumerate(rows, start=2):
        ident, _, _ = _extract_identificador(row, header, row_num)
        infos.append((row_num, ident, row))
    ids = list(dict.fromkeys(i for _, i, _ in infos if i))
    last_row_of, first_row_of = {}, {}
    for row_num, ident, _ in infos:
        if ident:
            last_row_of[ident] = row_num
            first_row_of.setdefault(ident, row_num)
    suppressed, users, attendees = set(), {}, {}
    hashes = {}
    for i in ids:
        hashes.setdefault(consent_mod.cedula_hash(i), []).append(i)
    for part in _chunks(list(hashes), _LOOKUP_CHUNK):
        for (h,) in db.query(SuppressedPerson.cedula_hash).filter(SuppressedPerson.tenant_id == event.tenant_id, SuppressedPerson.cedula_hash.in_(part)):
            suppressed.update(hashes.get(h, []))
    for part in _chunks(ids, _LOOKUP_CHUNK):
        for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(part)):
            users[u.id] = u
        for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part)):
            attendees[a.user_id] = a
    new = [i for i in ids if i not in suppressed and i not in users]
    enroll = [i for i in ids if i not in suppressed and i in users and i not in attendees]
    in_event = [i for i in ids if i not in suppressed and i in attendees]
    before = db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id).count()
    after = before + len(new) + len(enroll)

    labels = dict(prepared.get("labels") or event.get_optional_labels())
    fields = _field_list(db, event, labels, prepared.get("unnamed") or [])
    birth_used, code_enabled = bool(prepared.get("birth_used")), bool(event.code_enabled)
    samples = []
    for idx in core.sample_indices(len(infos)):
        row_num, ident, row = infos[idx]
        incoming = incoming_values(row, birth_used, code_enabled)
        user = users.get(ident)
        att = attendees.get(ident)
        old = current_values(user, att) if user is not None else {}
        if not ident:
            status, kind = "Sin cédula: esta fila no se carga", "skip"
        elif ident in suppressed:
            status, kind = "Pidió la supresión de sus datos: no se vuelve a crear", "skip"
        elif mode == "normal" and last_row_of.get(ident) != row_num:
            status, kind = f"Cédula repetida: queda la fila {last_row_of[ident]} (la última)", "skip"
        elif mode == "append" and first_row_of.get(ident) != row_num:
            status, kind = f"Cédula repetida: se usa la fila {first_row_of[ident]} (la primera)", "skip"
        elif att is not None and mode == "append":
            status, kind = "Ya está en el evento: no se toca nada", "keep"
        elif att is not None:
            status, kind = "Ya está en el evento: sus datos se reemplazan por los del archivo", "update"
        elif user is not None:
            status, kind = "Ya existe en el cliente: se inscribe en este evento" + (" con los datos del archivo" if mode == "normal" else " tal como está"), "enroll"
        else:
            status, kind = "Persona nueva", "new"
        shown = []
        show_old = kind in ("keep",) or (kind == "enroll" and mode == "append")
        for key, label in [("id", "Cédula")] + [f for f in fields if f[0] != "id"]:
            if key == "id":
                value = ident
            else:
                value = old.get(key, "") if show_old else incoming.get(key, "")
            prev = old.get(key, "") if kind in ("update", "enroll") and mode == "normal" and key != "id" else None
            changed = prev is not None and str(prev or "") != str(value or "")
            if not value and not changed:
                continue
            shown.append({"label": label, "value": value or "", "old": prev if changed else None, "cleared": changed and not value})
        samples.append({"row": row_num, "status": status, "kind": kind, "fields": shown})
    report = prepared.get("columns_report") or {}
    notes = []
    if mode == "normal" and in_event:
        notes.append(f"{len(in_event)} persona(s) que ya están en el evento quedarán con los datos del archivo: lo que el archivo traiga vacío en una columna que sí viene se borra.")
    if prepared.get("unnamed"):
        notes.append(f"El archivo trae {len(prepared['unnamed'])} columna(s) «opcional_N» sin nombre: al cargar te preguntaremos a qué corresponde cada una.")
    if prepared.get("birth_ignored_rows"):
        notes.append(f"{prepared['birth_ignored_rows']} fila(s) traen fecha de nacimiento y no se guardará (el evento no usa reconocimiento facial).")
    return {
        "mode": mode, "samples": samples, "sample_note": "Muestra de hasta 10 personas tomadas de punta a punta del archivo, tal como se verían en «Editar persona».",
        "impact": {"event_before": before, "event_after": after, "new": len(new), "enroll": len(enroll), "in_event": len(in_event),
                   "updated": len(in_event) if mode == "normal" else 0, "untouched": len(in_event) if mode == "append" else 0,
                   "suppressed": len([i for i in ids if i in suppressed]), "rows": len(infos), "without_id": sum(1 for _, i, _ in infos if not i),
                   "duplicates": len(infos) - sum(1 for _, i, _ in infos if not i) - len(ids)},
        "columns": {"recognized": report.get("recognized", []), "created": report.get("created", []), "unused": report.get("unused", [])},
        "notes": notes,
    }
