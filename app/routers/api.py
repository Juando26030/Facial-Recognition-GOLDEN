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
from app.models import User, AccessLog, Tenant
from app.biometrics import BiometricEngine
from app.reports import ReportManager

router = APIRouter()

CURRENT_TENANT = "golden_hq"
KNOWN_FACES_DIR = os.path.join('data', CURRENT_TENANT, 'known_people')
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

def get_tenant(db: Session):
    tenant = db.query(Tenant).filter(Tenant.id == CURRENT_TENANT).first()
    if not tenant:
        tenant = Tenant(id=CURRENT_TENANT, name="Golden Logísticas")
        db.add(tenant)
        db.commit()
    return tenant

@router.get("/users")
async def get_all_users(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.tenant_id == CURRENT_TENANT).all()
    result = []
    
    for u in users:
        logs = db.query(AccessLog).filter(AccessLog.user_id == u.id, AccessLog.tenant_id == CURRENT_TENANT).all()
        status = "No registrado"
        if logs:
            if any(log.record_type == "Nuevo" for log in logs):
                status = "Nuevo"
            else:
                status = "Registrado"
                
        result.append({
            "id": u.id, "first_name": u.first_name, "last_name": u.last_name, 
            "role": u.role, "company": u.company, "phone": u.phone, 
            "email": u.email, "opt_1": u.opt_1, "opt_2": u.opt_2, "status": status
        })
        
    return result

@router.post("/recognize")
async def recognize(file: UploadFile = File(...), db: Session = Depends(get_db)):
    get_tenant(db)
    img_array = BiometricEngine.process_image_stream(await file.read())
    unknown_enc = BiometricEngine.extract_encoding(img_array)
    
    if not unknown_enc:
        return {"result": "NO", "details": "Rostro no detectado"}

    users = db.query(User).filter(User.tenant_id == CURRENT_TENANT).all()
    for user in users:
        known_enc = user.get_encoding()
        if known_enc and BiometricEngine.compare(known_enc, unknown_enc):
            log = AccessLog(tenant_id=CURRENT_TENANT, user_id=user.id, record_type="Existente")
            db.add(log)
            db.commit()
            return {"result": "SÍ", "data": {
                "id": user.id, "first_name": user.first_name, "last_name": user.last_name, 
                "role": user.role, "company": user.company, "phone": user.phone,
                "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
            }}
            
    return {"result": "NO", "details": "Denegado"}

@router.patch("/users/{user_id}")
async def update_user(user_id: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.tenant_id == CURRENT_TENANT).first()
    if user:
        for key, value in data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        log = AccessLog(tenant_id=CURRENT_TENANT, user_id=user.id, record_type="Actualizado")
        db.add(log)
        db.commit()
        return {"message": "Actualizado correctamente"}
    return {"error": "Usuario no encontrado"}

@router.delete("/users/{user_id}/logs")
async def delete_user_logs(user_id: str, db: Session = Depends(get_db)):
    db.query(AccessLog).filter(AccessLog.user_id == user_id, AccessLog.tenant_id == CURRENT_TENANT).delete()
    db.commit()
    return {"message": "Registros eliminados. Estado regresado a No Registrado."}

@router.post("/register")
async def manual_register(
    id: str = Form(...), first_name: str = Form(...), last_name: str = Form(...), 
    role: str = Form(""), company: str = Form(""), phone: str = Form(""), 
    email: str = Form(""), file: UploadFile = File(...), db: Session = Depends(get_db)
):
    get_tenant(db)
    existing = db.query(User).filter(User.id == id, User.tenant_id == CURRENT_TENANT).first()
    if existing:
        return {"error": "El usuario ya está registrado en la base de datos."}
        
    img_array = BiometricEngine.process_image_stream(await file.read())
    encodings = BiometricEngine.extract_encoding(img_array, is_registration=True)
    
    if not encodings:
        return {"error": "No se detectó un rostro en la fotografía."}
        
    face_enc_json = json.dumps(encodings)
    
    user = User(
        id=id, tenant_id=CURRENT_TENANT, first_name=first_name.strip(), last_name=last_name.strip(), 
        role=role, company=company, phone=phone, email=email, face_encoding=face_enc_json
    )
    db.add(user)
    
    log = AccessLog(tenant_id=CURRENT_TENANT, user_id=id, record_type="Nuevo")
    db.add(log)
    db.commit()
    
    img_path = os.path.join(KNOWN_FACES_DIR, f"{id}.jpg")
    Image.fromarray(img_array).save(img_path)
    
    return {"message": "Usuario registrado exitosamente como Nuevo."}

@router.post("/bulk_register")
async def bulk_register(zip_file: UploadFile = File(...), csv_file: UploadFile = File(...), db: Session = Depends(get_db)):
    get_tenant(db)
    
    zip_path = os.path.join(KNOWN_FACES_DIR, 'temp.zip')
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
                    Image.fromarray(img_array).save(os.path.join(KNOWN_FACES_DIR, basename))
                except: pass
    if os.path.exists(zip_path): os.remove(zip_path)
    
    content = await csv_file.read()
    decoded_content = content.decode('utf-8-sig')
    delimiter = ';' if ';' in decoded_content else ','
    reader = csv.DictReader(io.StringIO(decoded_content), delimiter=delimiter)
    
    count = 0
    for row in reader:
        clean_row = {k.strip().lower() if k else '': v.strip() for k, v in row.items() if k}
        identificador = clean_row.get('id', '') or clean_row.get('identificación', '')
        
        if identificador:
            face_enc_json = None
            img_path = os.path.join(KNOWN_FACES_DIR, f"{identificador}.jpg")
            if os.path.exists(img_path):
                known_image = face_recognition.load_image_file(img_path)
                encodings = face_recognition.face_encodings(known_image, num_jitters=25)
                if encodings:
                    face_enc_json = json.dumps(encodings[0].tolist())
            
            user = db.query(User).filter(User.id == identificador, User.tenant_id == CURRENT_TENANT).first()
            if not user:
                user = User(id=identificador, tenant_id=CURRENT_TENANT)
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
            count += 1
            
    db.commit()
    return {"message": f"Sincronización masiva exitosa: {count} perfiles cargados."}

@router.get("/report")
async def download_report(db: Session = Depends(get_db)):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    ReportManager.generate_excel_report(db, CURRENT_TENANT, temp_file.name)
    return FileResponse(temp_file.name, filename="Golden_Reporte_Eventos.xlsx")