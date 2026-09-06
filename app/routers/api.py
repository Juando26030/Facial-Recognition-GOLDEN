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
            return {"result": "SÍ", "data": {"id": user.id, "nombre": user.name, "empresa": user.company, "telefono": user.phone}}
            
    return {"result": "NO", "details": "Denegado"}

@router.patch("/users/{user_id}")
async def update_user(user_id: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.tenant_id == CURRENT_TENANT).first()
    if user:
        for key, value in data.items():
            setattr(user, key, value)
        log = AccessLog(tenant_id=CURRENT_TENANT, user_id=user.id, record_type="Actualizado")
        db.add(log)
        db.commit()
        return {"message": "Actualizado correctamente"}
    return {"error": "Usuario no encontrado"}

@router.post("/bulk_register")
async def bulk_register(zip_file: UploadFile = File(...), csv_file: UploadFile = File(...), db: Session = Depends(get_db)):
    get_tenant(db)
    
    # 1. Guardar fotos extraídas
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
    
    # 2. Leer CSV y subir todo a PostgreSQL
    content = await csv_file.read()
    decoded_content = content.decode('utf-8-sig')
    delimiter = ';' if ';' in decoded_content else ','
    reader = csv.DictReader(io.StringIO(decoded_content), delimiter=delimiter)
    
    count = 0
    for row in reader:
        clean_row = {k.strip().lower() if k else '': v.strip() for k, v in row.items() if k}
        identificador = clean_row.get('id', '')
        
        if identificador:
            # Extraer vector facial de la foto para guardarlo en SQL
            face_enc_json = None
            img_path = os.path.join(KNOWN_FACES_DIR, f"{identificador}.jpg")
            if os.path.exists(img_path):
                known_image = face_recognition.load_image_file(img_path)
                encodings = face_recognition.face_encodings(known_image, num_jitters=10)
                if encodings:
                    face_enc_json = json.dumps(encodings[0].tolist())
            
            # Crear o actualizar usuario
            user = db.query(User).filter(User.id == identificador, User.tenant_id == CURRENT_TENANT).first()
            if not user:
                user = User(id=identificador, tenant_id=CURRENT_TENANT)
                db.add(user)
            
            user.name = clean_row.get('nombre', '')
            user.role = clean_row.get('cargo', '')
            user.company = clean_row.get('empresa', '')
            user.phone = clean_row.get('telefono', '')
            user.email = clean_row.get('correo', '')
            user.opt_1 = clean_row.get('opcional_1', '')
            user.opt_2 = clean_row.get('opcional_2', '')
            if face_enc_json:
                user.face_encoding = face_enc_json
            count += 1
            
    db.commit()
    return {"message": f"Sincronización masiva exitosa: {count} perfiles cargados en SQL."}

@router.get("/report")
async def download_report(db: Session = Depends(get_db)):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    ReportManager.generate_excel_report(db, CURRENT_TENANT, temp_file.name)
    return FileResponse(temp_file.name, filename="Golden_Reporte_Eventos.xlsx")