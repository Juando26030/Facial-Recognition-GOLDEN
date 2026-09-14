import os
import json
import zipfile
import tempfile
import csv
import io
import face_recognition
from PIL import Image
from fastapi import APIRouter, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, AccessLog, EventAttendee, StaffUser
from app.biometrics import BiometricEngine
from app.reports import ReportManager
from app.auth import get_current_staff, get_event_for_staff, require_event_in_progress, require_role

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
    event_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
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
    event_id: int = Form(...), cedula: str = Form(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    """Acreditación por cédula (lector de código de barras) — mismo shape de respuesta que
    /recognize (result SÍ/NO + data), para reusar el mismo patrón de frontend. Si la persona ya
    es conocida en el tenant (estuviera o no precargada para este evento puntual), se acredita
    directo como 'Existente' y de paso queda asociada a este evento. Si la cédula no existe en
    absoluto, el frontend debe ofrecer el alta manual (POST /register, sin foto)."""
    cedula = cedula.strip()
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)

    user = db.query(User).filter(User.id == cedula, User.tenant_id == event.tenant_id).first()
    if not user:
        return {"result": "NO", "details": "Cédula no encontrada"}

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
    email: str = Form(""), file: UploadFile = File(None), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    """file es OPCIONAL: el alta manual la puede disparar tanto el flujo facial (con foto, para
    poder reconocer a esta persona después) como el de cédula (sin foto, solo identidad)."""
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    existing = db.query(User).filter(User.id == id, User.tenant_id == event.tenant_id).first()
    if existing:
        return {"error": "El usuario ya está registrado en la base de datos."}

    face_enc_json = None
    img_array = None
    if file is not None:
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
    event_id: int = Form(...), csv_file: UploadFile = File(...), zip_file: UploadFile = File(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Carga la base de asistentes esperados para el evento — sirve para CUALQUIER método de
    registro (cédula, facial, QR futuro), no es exclusiva de facial. zip_file es OPCIONAL: solo
    hace falta si además quieres que estas personas se puedan reconocer por cara (las fotos del
    zip, nombradas <cédula>.jpg, se procesan a encoding biométrico). Sin zip, solo se cargan datos
    de identidad + se asocian al evento (EventAttendee) — suficiente para acreditar por cédula.
    Los errores de fila no abortan la carga completa, se reportan al final."""
    event = get_event_for_staff(event_id, db, staff)
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

    content = await csv_file.read()
    decoded_content = content.decode('utf-8-sig')
    delimiter = ';' if ';' in decoded_content else ','
    reader = csv.DictReader(io.StringIO(decoded_content), delimiter=delimiter)

    count = 0
    errors = []
    for row_num, row in enumerate(reader, start=2):  # fila 1 es el encabezado
        try:
            clean_row = {k.strip().lower() if k else '': (v or '').strip() for k, v in row.items() if k}
            identificador = clean_row.get('id', '') or clean_row.get('identificación', '') or clean_row.get('cedula', '') or clean_row.get('cédula', '')

            if not identificador:
                errors.append(f"Fila {row_num}: sin ID/cédula, se omitió")
                continue

            face_enc_json = None
            img_path = os.path.join(known_faces_dir, f"{identificador}.jpg")
            if os.path.exists(img_path):
                known_image = face_recognition.load_image_file(img_path)
                encodings = face_recognition.face_encodings(known_image, num_jitters=25)
                if encodings:
                    face_enc_json = json.dumps(encodings[0].tolist())

            user = db.query(User).filter(User.id == identificador, User.tenant_id == event.tenant_id).first()
            if not user:
                user = User(id=identificador, tenant_id=event.tenant_id)
                db.add(user)

            user.first_name = clean_row.get('nombres', '') or clean_row.get('nombre', '')
            user.last_name = clean_row.get('apellidos', '') or clean_row.get('apellido', '')
            user.role = clean_row.get('cargo', '')
            user.company = clean_row.get('empresa', '')
            user.phone = clean_row.get('telefono', '') or clean_row.get('tel. celular', '')
            user.email = clean_row.get('correo', '') or clean_row.get('e-mail corporativo', '')
            user.opt_1 = clean_row.get('opcional_1', '') or clean_row.get('tipo de empresa', '')
            user.opt_2 = clean_row.get('opcional_2', '') or clean_row.get('cantidad de empl', '')

            if face_enc_json:
                user.face_encoding = face_enc_json

            _upsert_attendee(db, event.id, identificador, event.tenant_id)
            count += 1
        except Exception as e:
            errors.append(f"Fila {row_num}: {e}")

    db.commit()
    message = f"Carga completa: {count} perfiles cargados."
    if errors:
        message += f" {len(errors)} fila(s) con error."
    return {"message": message, "count": count, "errors": errors}

@router.get("/report")
async def download_report(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    event = get_event_for_staff(event_id, db, staff)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    ReportManager.generate_excel_report(db, event.tenant_id, temp_file.name)
    return FileResponse(temp_file.name, filename="Golden_Reporte_Eventos.xlsx")
