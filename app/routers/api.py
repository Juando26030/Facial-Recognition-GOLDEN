import os
import re
import json
import zipfile
import tempfile
import csv
import io
import face_recognition
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, AccessLog, EventAttendee, StaffUser
from app.biometrics import BiometricEngine
from app.reports import ReportManager
from app.auth import get_current_staff, get_event_for_staff, require_event_in_progress, require_role


def _read_roster_rows(filename: str, content: bytes):
    """Lee un roster en .csv o .xlsx y devuelve (header_columns, rows): filas normalizadas
    (claves en minúscula, sin espacios) sin importar el formato de origen, y un mapeo
    {header: 'A'|'B'|...} de en qué columna venía cada campo — así bulk_register puede señalar
    la celda exacta (ej. "B7") de un error, sea el archivo .xlsx o .csv."""
    filename = (filename or "").lower()
    if filename.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h).strip().lower() if h is not None else "" for h in next(rows_iter, [])]
        header_columns = {h: get_column_letter(i + 1) for i, h in enumerate(headers) if h}
        rows = []
        for row in rows_iter:
            if row is None or all(cell is None for cell in row):
                continue
            rows.append({
                headers[i]: (str(cell).strip() if cell is not None else "")
                for i, cell in enumerate(row) if i < len(headers) and headers[i]
            })
        return header_columns, rows
    else:
        decoded = content.decode("utf-8-sig")
        delimiter = ";" if ";" in decoded.split("\n", 1)[0] else ","
        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
        headers = [h.strip().lower() if h else "" for h in (reader.fieldnames or [])]
        header_columns = {h: get_column_letter(i + 1) for i, h in enumerate(headers) if h}
        rows = [
            {k.strip().lower() if k else "": (v or "").strip() for k, v in row.items() if k}
            for row in reader
        ]
        return header_columns, rows

MAX_OPTIONAL_FIELDS = 30
_OPTIONAL_FIELD_RE = re.compile(r"^opcional[\s_]*([0-9]{1,2})$")


def _normalize_optional_key(raw_key: str):
    """Reconoce cualquier variante de encabezado 'opcional 1'..'opcional 30' (con espacio, guion
    bajo, o pegado — 'opcional1') y la normaliza a la forma canónica 'opcional_N' que usamos para
    guardar en User.extra_fields y Event.optional_field_labels. None si no matchea o el número
    está fuera de rango."""
    if not raw_key:
        return None
    match = _OPTIONAL_FIELD_RE.match(raw_key.strip())
    if not match:
        return None
    n = int(match.group(1))
    return f"opcional_{n}" if 1 <= n <= MAX_OPTIONAL_FIELDS else None


_ID_KEYS = ('id', 'identificación', 'cedula', 'cédula')
_FLOAT_LOOKING_ID_RE = re.compile(r'^(\d+)\.0+$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^[\d\s+()\-]+$')


def _field_lookup(clean_row: dict, header_columns: dict, row_num: int, *keys: str):
    """Busca el primer valor no vacío entre varios encabezados alternativos (ej. 'nombres' o
    'nombre') y devuelve (valor, referencia_de_celda) — ej. ('Juan', 'B7'). Si ninguno tiene
    valor pero al menos uno de esos encabezados sí vino en el archivo, igual devuelve su celda
    (útil para señalar dónde falta el dato); si el archivo ni siquiera trae esa columna, la
    referencia es None y quien llama debe caer de vuelta a "fila N"."""
    for key in keys:
        val = clean_row.get(key, '')
        if val:
            col = header_columns.get(key)
            return val, (f"{col}{row_num}" if col else None)
    for key in keys:
        if key in header_columns:
            return '', f"{header_columns[key]}{row_num}"
    return '', None


def _extract_identificador(clean_row: dict, header_columns: dict, row_num: int):
    """Saca la cédula/ID de la fila (probando los encabezados alternativos de siempre) y de paso
    corrige el problema clásico de Excel de convertir una columna de cédulas en números, que
    entonces llegan como '1020304050.0' en vez de '1020304050'. Devuelve (identificador_limpio,
    celda, nota_o_None) — la nota, si existe, se le muestra al usuario explicando la corrección."""
    raw_val, cell_ref = _field_lookup(clean_row, header_columns, row_num, *_ID_KEYS)
    val = raw_val.strip()
    note = None
    match = _FLOAT_LOOKING_ID_RE.match(val)
    if match:
        corrected = match.group(1)
        where = cell_ref or f"fila {row_num}"
        note = f"ℹ️ Fila {row_num} ({where}): la cédula venía como '{val}' — Excel la convirtió a número. Se corrigió automáticamente a '{corrected}'."
        val = corrected
    return val, cell_ref, note


router = APIRouter()


def _known_faces_dir(tenant_id: str) -> str:
    path = os.path.join('data', tenant_id, 'known_people')
    os.makedirs(path, exist_ok=True)
    return path


def _upsert_attendee(db: Session, event_id: int, user_id: str, tenant_id: str) -> None:
    """Asegura que esta persona quede en la lista del evento, se haya precargado o no (ej. un
    'Nuevo' dado de alta sobre la marcha el día del evento) — ver EventAttendee en models.py."""
    exists = db.query(EventAttendee).filter_by(event_id=event_id, user_id=user_id).first()
    if not exists:
        db.add(EventAttendee(event_id=event_id, user_id=user_id, tenant_id=tenant_id))


def _already_checked_in(db: Session, event_id: int, user_id: str) -> bool:
    """True si esta persona ya tiene al menos un AccessLog para ESTE evento — o sea, ya se
    acreditó hoy por cualquier método (facial, cédula o alta manual). Se usa para pedir
    confirmación antes de dejarla entrar una segunda vez por error/duplicado."""
    return db.query(AccessLog).filter(
        AccessLog.event_id == event_id, AccessLog.user_id == user_id
    ).first() is not None


def _duplicate_warning(user: "User") -> dict:
    return {"result": "DUPLICADO", "details": "Esta persona ya había sido registrada en este evento", "data": {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "company": user.company, "phone": user.phone,
        "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
    }}


@router.get("/users")
async def get_all_users(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)
):
    """Cualquier staff autenticado con acceso al evento puede VER el directorio (digitador y
    cliente incluidos) — get_event_for_staff abajo hace el chequeo real de autorización.
    El directorio es de ESTE evento: roster precargado (EventAttendee) unido con quien de hecho
    se presentó (AccessLog filtrado por event_id) — ya no todos los User del tenant sin distinguir
    entre eventos distintos del mismo cliente."""
    event = get_event_for_staff(event_id, db, staff)

    attendee_ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == event_id)}
    log_ids = {l.user_id for l in db.query(AccessLog).filter(AccessLog.event_id == event_id)}
    all_ids = attendee_ids | log_ids
    if not all_ids:
        return []

    users = db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(all_ids)).all()
    event_logs = db.query(AccessLog).filter(AccessLog.event_id == event_id).all()
    logs_by_user = {}
    for log in event_logs:
        logs_by_user.setdefault(log.user_id, []).append(log)

    result = []
    for u in users:
        logs = logs_by_user.get(u.id, [])
        status = "No registrado"
        if logs:
            status = "Nuevo" if any(log.record_type == "Nuevo" for log in logs) else "Registrado"

        result.append({
            "id": u.id, "first_name": u.first_name, "last_name": u.last_name,
            "role": u.role, "company": u.company, "phone": u.phone,
            "email": u.email, "opt_1": u.opt_1, "opt_2": u.opt_2, "status": status
        })

    return result

@router.post("/recognize")
async def recognize(
    event_id: int = Form(...), file: UploadFile = File(...), force: bool = Form(False),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    img_array = BiometricEngine.process_image_stream(await file.read())
    unknown_enc = BiometricEngine.extract_encoding(img_array)

    if not unknown_enc:
        return {"result": "NO", "details": "Rostro no detectado"}

    users = db.query(User).filter(User.tenant_id == event.tenant_id).all()
    for user in users:
        known_enc = user.get_encoding()
        if known_enc and BiometricEngine.compare(known_enc, unknown_enc):
            if not force and _already_checked_in(db, event.id, user.id):
                return _duplicate_warning(user)
            log = AccessLog(
                tenant_id=event.tenant_id, user_id=user.id, record_type="Existente",
                event_id=event.id, registered_by_staff_id=staff.id,
            )
            db.add(log)
            _upsert_attendee(db, event.id, user.id, event.tenant_id)
            db.commit()
            return {"result": "SÍ", "data": {
                "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
                "role": user.role, "company": user.company, "phone": user.phone,
                "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
            }}

    return {"result": "NO", "details": "Denegado"}

@router.post("/checkin-cedula")
async def checkin_cedula(
    event_id: int = Form(...), cedula: str = Form(...), force: bool = Form(False),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """Acreditación por cédula (lector de código de barras) — mismo shape de respuesta que
    /recognize (result SÍ/NO + data), para reusar el mismo patrón de frontend. Si la persona ya
    es conocida en el tenant (estuviera o no precargada para este evento puntual), se acredita
    directo como 'Existente' y de paso queda asociada a este evento. Si la cédula no existe en
    absoluto, el frontend debe ofrecer el alta manual (POST /register, sin foto). Si ya tiene un
    AccessLog para este evento, se avisa (result: DUPLICADO) en vez de acreditar de nuevo, salvo
    que venga force=true (el operador ya confirmó que sí quiere repetirlo)."""
    cedula = cedula.strip()
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)

    user = db.query(User).filter(User.id == cedula, User.tenant_id == event.tenant_id).first()
    if not user:
        return {"result": "NO", "details": "Cédula no encontrada"}

    if not force and _already_checked_in(db, event.id, user.id):
        return _duplicate_warning(user)

    log = AccessLog(
        tenant_id=event.tenant_id, user_id=user.id, record_type="Existente",
        event_id=event.id, registered_by_staff_id=staff.id,
    )
    db.add(log)
    _upsert_attendee(db, event.id, user.id, event.tenant_id)
    db.commit()
    return {"result": "SÍ", "data": {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "company": user.company, "phone": user.phone,
        "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
    }}

@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, data: dict, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if user:
        for key, value in data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        log = AccessLog(
            tenant_id=event.tenant_id, user_id=user.id, record_type="Actualizado",
            event_id=event.id, registered_by_staff_id=staff.id,
        )
        db.add(log)
        db.commit()
        return {"message": "Actualizado correctamente"}
    return {"error": "Usuario no encontrado"}

@router.delete("/users/{user_id}/logs")
async def delete_user_logs(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("admin")),
):
    event = get_event_for_staff(event_id, db, staff)
    db.query(AccessLog).filter(AccessLog.user_id == user_id, AccessLog.tenant_id == event.tenant_id).delete()
    db.commit()
    return {"message": "Registros eliminados. Estado regresado a No Registrado."}

@router.post("/register")
async def manual_register(
    event_id: int = Form(...), id: str = Form(...), first_name: str = Form(...), last_name: str = Form(...),
    role: str = Form(""), company: str = Form(""), phone: str = Form(""),
    email: str = Form(""), file: UploadFile = File(None), force: bool = Form(False),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """file es OPCIONAL: el alta manual la puede disparar tanto el flujo facial (con foto, para
    poder reconocer a esta persona después) como el de cédula (sin foto, solo identidad).
    Si la cédula ya existe como User en el tenant (de este evento o de uno anterior — User vive
    a nivel de tenant, no de evento) no se rechaza de plano: si todavía no tiene AccessLog para
    ESTE evento, simplemente se le agrega (reutilizar a alguien de un evento pasado es válido);
    si ya lo tiene, se avisa (DUPLICADO) igual que recognize/checkin-cedula, salvo force=true."""
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    existing = db.query(User).filter(User.id == id, User.tenant_id == event.tenant_id).first()
    if existing:
        if not force and _already_checked_in(db, event.id, existing.id):
            return _duplicate_warning(existing)
        log = AccessLog(
            tenant_id=event.tenant_id, user_id=existing.id, record_type="Existente",
            event_id=event.id, registered_by_staff_id=staff.id,
        )
        db.add(log)
        _upsert_attendee(db, event.id, existing.id, event.tenant_id)
        db.commit()
        return {"message": "Esta persona ya existía en el sistema — registrada para este evento."}

    face_enc_json = None
    img_array = None
    # OJO: un <input type="file"> vacío igual manda una parte multipart (con filename=""), así
    # que `file is not None` es cierto incluso sin archivo real — hay que revisar `file.filename`
    # también, si no, `file.read()` da bytes vacíos y `Image.open()` truena (500) en vez de
    # tratarlo como "no se adjuntó foto" (CEDULA-08, bug real encontrado en testing 2026-09-21).
    if file is not None and file.filename:
        img_array = BiometricEngine.process_image_stream(await file.read())
        encodings = BiometricEngine.extract_encoding(img_array, is_registration=True)
        if not encodings:
            return {"error": "No se detectó un rostro en la fotografía."}
        face_enc_json = json.dumps(encodings)

    user = User(
        id=id, tenant_id=event.tenant_id, first_name=first_name.strip(), last_name=last_name.strip(),
        role=role, company=company, phone=phone, email=email, face_encoding=face_enc_json
    )
    db.add(user)

    log = AccessLog(
        tenant_id=event.tenant_id, user_id=id, record_type="Nuevo",
        event_id=event.id, registered_by_staff_id=staff.id,
    )
    db.add(log)
    _upsert_attendee(db, event.id, id, event.tenant_id)
    db.commit()

    if img_array is not None:
        img_path = os.path.join(_known_faces_dir(event.tenant_id), f"{id}.jpg")
        Image.fromarray(img_array).save(img_path)

    return {"message": "Usuario registrado exitosamente como Nuevo."}

@router.post("/bulk_register")
async def bulk_register(
    event_id: int = Form(...), roster_file: UploadFile = File(...), zip_file: UploadFile = File(None),
    field_labels: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Carga la base de asistentes esperados para el evento — sirve para CUALQUIER método de
    registro (cédula, facial, QR futuro), no es exclusiva de facial. roster_file acepta .csv o
    .xlsx (Historia 1.1: el negocio manda Excel). zip_file es OPCIONAL: solo hace falta si además
    quieres que estas personas se puedan reconocer por cara (las fotos del zip, nombradas
    <cédula>.jpg, se procesan a encoding biométrico). Sin zip, solo se cargan datos de identidad +
    se asocian al evento (EventAttendee) — suficiente para acreditar por cédula. Los errores de
    fila no abortan la carga completa, se reportan al final. No se permite cargar sobre un evento
    ya 'finalizado' (sí sobre 'creado' o 'en_proceso' — es preparación previa al evento).

    Campos dinámicos "opcional_1".."opcional_30" (2026-09-20): además de las columnas fijas
    (id, nombres, apellidos, cargo, empresa, telefono, correo, "tipo de asistente"), el roster
    puede traer hasta 30 columnas "opcional_N" — se interpretan las que de verdad vengan usadas
    (con al menos un valor no vacío en alguna fila), el resto se ignoran. Si el archivo trae
    columnas opcionales que este evento todavía no tiene rotuladas (Event.optional_field_labels),
    se devuelve {"result": "NEEDS_LABELS", "fields": [...]} SIN procesar nada — el frontend debe
    preguntarle al operador a qué corresponde cada una y reenviar la misma petición con
    field_labels (JSON, ej. {"opcional_1": "Talla de camisa"}) para que se guarden y se continúe
    con la carga."""
    event = get_event_for_staff(event_id, db, staff)
    if event.status == "finalizado":
        raise HTTPException(status_code=400, detail="No se puede cargar la base de un evento finalizado")

    content = await roster_file.read()
    header_columns, rows = _read_roster_rows(roster_file.filename, content)

    used_optional_keys = set()
    for row in rows:
        for raw_key, value in row.items():
            norm = _normalize_optional_key(raw_key)
            if norm and (value or "").strip():
                used_optional_keys.add(norm)

    existing_labels = event.get_optional_labels()
    missing = used_optional_keys - set(existing_labels.keys())

    if missing and not field_labels:
        return {"result": "NEEDS_LABELS", "fields": sorted(missing, key=lambda k: int(k.split("_")[1]))}

    if field_labels:
        try:
            provided = json.loads(field_labels)
        except (json.JSONDecodeError, TypeError):
            provided = {}
        merged = dict(existing_labels)
        for raw_key, label in (provided or {}).items():
            norm = _normalize_optional_key(raw_key)
            if norm and label and str(label).strip():
                merged[norm] = str(label).strip()
        for key in used_optional_keys - set(merged.keys()):
            merged[key] = f"Opcional {key.split('_')[1]}"
        event.set_optional_labels(merged)
        db.commit()

    known_faces_dir = _known_faces_dir(event.tenant_id)

    if zip_file is not None and zip_file.filename:
        zip_path = os.path.join(known_faces_dir, 'temp.zip')
        with open(zip_path, "wb") as buffer:
            buffer.write(await zip_file.read())

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for filename in zip_ref.namelist():
                if filename.startswith('__MACOSX') or filename.startswith('.') or filename.endswith('/'): continue
                basename = os.path.basename(filename)
                if not basename: continue
                with zip_ref.open(filename) as source:
                    try:
                        img_array = BiometricEngine.process_image_stream(source.read())
                        Image.fromarray(img_array).save(os.path.join(known_faces_dir, basename))
                    except: pass
        if os.path.exists(zip_path): os.remove(zip_path)

    # --- Pre-escaneo: identificar cédulas (con corrección del "Excel las volvió número"),
    # detectar cédulas repetidas dentro del mismo archivo, ANTES de tocar la base de datos.
    # Esto es lo que le permite al operador ver de una vez, con celda exacta, qué está mal en su
    # archivo en vez de enterarse fila por fila o con un error genérico. ---
    row_infos = []
    seen_rows_by_id = {}
    for row_num, clean_row in enumerate(rows, start=2):  # fila 1 es el encabezado
        identificador, id_cell, id_note = _extract_identificador(clean_row, header_columns, row_num)
        notes = [id_note] if id_note else []
        row_infos.append({
            "row_num": row_num, "clean_row": clean_row,
            "identificador": identificador, "id_cell": id_cell, "notes": notes,
        })
        if identificador:
            seen_rows_by_id.setdefault(identificador, []).append(row_num)

    id_col = next((header_columns[k] for k in _ID_KEYS if k in header_columns), None)
    errors = []
    for id_val, row_nums in seen_rows_by_id.items():
        if len(row_nums) > 1:
            cells = ", ".join(f"{id_col}{n}" if id_col else f"fila {n}" for n in row_nums)
            errors.append(
                f"⚠️ La cédula '{id_val}' aparece repetida en {len(row_nums)} filas ({cells}) — "
                f"se combinaron los datos y quedó lo de la última fila."
            )

    count = 0
    for info in row_infos:
        row_num, clean_row, identificador = info["row_num"], info["clean_row"], info["identificador"]
        errors.extend(info["notes"])

        if not identificador:
            where = info["id_cell"] or f"fila {row_num}"
            errors.append(f"❌ Fila {row_num} ({where}): sin ID/cédula, se omitió esta fila.")
            continue

        # Validaciones de calidad de dato — no bloquean la fila (se guarda igual), solo avisan
        # exactamente en qué celda está el problema para que el operador lo revise si quiere.
        nombres, nombres_cell = _field_lookup(clean_row, header_columns, row_num, 'nombres', 'nombre')
        if not nombres:
            errors.append(f"⚠️ Fila {row_num} ({nombres_cell or 'sin columna de nombres'}): falta el nombre.")
        apellidos, apellidos_cell = _field_lookup(clean_row, header_columns, row_num, 'apellidos', 'apellido')
        if not apellidos:
            errors.append(f"⚠️ Fila {row_num} ({apellidos_cell or 'sin columna de apellidos'}): falta el apellido.")
        correo, correo_cell = _field_lookup(clean_row, header_columns, row_num, 'correo', 'e-mail corporativo')
        if correo and not _EMAIL_RE.match(correo):
            errors.append(f"⚠️ Fila {row_num} ({correo_cell}): el correo '{correo}' no parece válido — se guardó igual, revísalo.")
        telefono, telefono_cell = _field_lookup(clean_row, header_columns, row_num, 'telefono', 'tel. celular')
        if telefono and not _PHONE_RE.match(telefono):
            errors.append(f"⚠️ Fila {row_num} ({telefono_cell}): el teléfono '{telefono}' tiene caracteres raros — se guardó igual, revísalo.")

        try:
            face_enc_json = None
            img_path = os.path.join(known_faces_dir, f"{identificador}.jpg")
            if os.path.exists(img_path):
                known_image = face_recognition.load_image_file(img_path)
                encodings = face_recognition.face_encodings(known_image, num_jitters=25)
                if encodings:
                    face_enc_json = json.dumps(encodings[0].tolist())

            # SAVEPOINT por fila (no solo un try/except de Python): con autoflush=False, una sola
            # fila con un problema real de base de datos (ej. una violación de llave) dejaba la
            # transacción completa "abortada" para Postgres, y el error solo aparecía hasta el
            # db.commit() final — tumbando TODA la carga con un 500, incluidas las filas que sí
            # habían "funcionado" en Python pero nunca llegaron a guardarse. Con begin_nested(),
            # si esta fila falla se revierte solo su savepoint (la transacción de afuera sigue
            # sana) y el flush() intermedio asegura que el INSERT de User ya se mandó a Postgres
            # antes del de EventAttendee (que depende de él por llave foránea).
            with db.begin_nested():
                user = db.query(User).filter(User.id == identificador, User.tenant_id == event.tenant_id).first()
                if not user:
                    user = User(id=identificador, tenant_id=event.tenant_id)
                    db.add(user)

                user.first_name = nombres
                user.last_name = apellidos
                user.role = clean_row.get('cargo', '')
                user.company = clean_row.get('empresa', '')
                user.phone = telefono
                user.email = correo
                user.opt_1 = clean_row.get('tipo de asistente', '') or clean_row.get('tipo_asistente', '')

                extras = {}
                for raw_key, value in clean_row.items():
                    norm = _normalize_optional_key(raw_key)
                    val = (value or "").strip()
                    if norm and val:
                        extras[norm] = val
                user.set_extras(extras)

                if face_enc_json:
                    user.face_encoding = face_enc_json

                db.flush()
                _upsert_attendee(db, event.id, identificador, event.tenant_id)
                db.flush()

            count += 1
        except Exception as e:
            where = info["id_cell"] or f"fila {row_num}"
            errors.append(f"❌ Fila {row_num} ({where}): no se pudo guardar — {e}")

    db.commit()
    message = f"Carga completa: {count} perfiles cargados."
    if errors:
        message += f" {len(errors)} observación(es) — revisa el detalle."
    return {"message": message, "count": count, "errors": errors, "optional_labels": event.get_optional_labels()}

@router.get("/report")
async def download_report(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    event = get_event_for_staff(event_id, db, staff)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    ReportManager.generate_excel_report(db, event.tenant_id, temp_file.name)
    return FileResponse(temp_file.name, filename="Golden_Reporte_Eventos.xlsx")
