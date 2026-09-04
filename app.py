import os
import json
import zipfile
import csv
import face_recognition
from flask import Flask, request, jsonify, render_template
from PIL import Image, ImageOps
import numpy as np

app = Flask(__name__)

# ARQUITECTURA MULTI-TENANT: Preparamos el sistema para aislar clientes
CURRENT_TENANT = 'golden_hq' 
KNOWN_FACES_DIR = os.path.join('data', CURRENT_TENANT, 'known_people')
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

def procesar_imagen_segura(file_stream):
    img = Image.open(file_stream)
    img = ImageOps.exif_transpose(img)
    img = img.convert('RGB')
    return np.array(img)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    file = request.files.get('file')
    data = request.form.to_dict()
    identificador = data.get('id', data.get('nombre', 'desconocido')).strip()
    
    if not file: return jsonify({'error': 'Falta la foto'}), 400
    
    img_array = procesar_imagen_segura(file)
    Image.fromarray(img_array).save(os.path.join(KNOWN_FACES_DIR, f"{identificador}.jpg"))
    
    with open(os.path.join(KNOWN_FACES_DIR, f"{identificador}.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    return jsonify({'message': f'Perfil guardado exitosamente en el tenant {CURRENT_TENANT}.'})

@app.route('/bulk_register', methods=['POST'])
def bulk_register():
    try:
        zip_file = request.files.get('zip_file')
        csv_file = request.files.get('csv_file')
        
        if not zip_file or not csv_file: 
            return jsonify({'error': 'Faltan archivos'}), 400
        
        zip_path = os.path.join(KNOWN_FACES_DIR, 'temp.zip')
        zip_file.save(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for filename in zip_ref.namelist():
                if filename.startswith('__MACOSX') or filename.startswith('.') or filename.endswith('/'): continue
                basename = os.path.basename(filename)
                if not basename: continue
                with zip_ref.open(filename) as source:
                    try:
                        img_array = procesar_imagen_segura(source)
                        Image.fromarray(img_array).save(os.path.join(KNOWN_FACES_DIR, basename))
                    except: pass
        if os.path.exists(zip_path): os.remove(zip_path)
        
        csv_path = os.path.join(KNOWN_FACES_DIR, 'temp.csv')
        csv_file.save(csv_path)
        
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
            
        headers = [h.strip().lower() for h in lines[0].split(',') if h.strip()]
        count = 0
        for line in lines[1:]:
            if not line.strip(): continue
            values = [v.strip() for v in line.split(',')]
            row_data = {headers[i]: values[i] for i in range(len(headers)) if i < len(values)}
            identificador = row_data.get('id', '')
            if identificador:
                count += 1
                with open(os.path.join(KNOWN_FACES_DIR, f"{identificador}.json"), 'w', encoding='utf-8') as jf:
                    json.dump(row_data, jf, ensure_ascii=False, indent=4)
                    
        if os.path.exists(csv_path): os.remove(csv_path)
        return jsonify({'message': f'Sincronización masiva exitosa: {count} perfiles en {CURRENT_TENANT}.'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/recognize', methods=['POST'])
def recognize():
    file = request.files.get('file')
    if not file: return jsonify({'result': 'NO', 'details': 'Sube foto'}), 400
    
    unknown_image = procesar_imagen_segura(file)
    try: unknown_encoding = face_recognition.face_encodings(unknown_image)[0]
    except: return jsonify({'result': 'NO', 'details': 'Rostro no detectado en cámara'})

    for known_file in os.listdir(KNOWN_FACES_DIR):
        if not known_file.endswith('.jpg'): continue
            
        known_image = face_recognition.load_image_file(os.path.join(KNOWN_FACES_DIR, known_file))
        known_encodings = face_recognition.face_encodings(known_image, num_jitters=10)
        if not known_encodings: continue
        
        distancia = face_recognition.face_distance([known_encodings[0]], unknown_encoding)[0]
        if distancia < 0.68:
            identificador = known_file.replace('.jpg', '')
            user_data = {"id": identificador, "nombre": "Autorizado", "cargo": "N/A", "empresa": "Golden Logísticas"}
            json_path = os.path.join(KNOWN_FACES_DIR, f"{identificador}.json")
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
            return jsonify({'result': 'SÍ', 'data': user_data})
            
    return jsonify({'result': 'NO', 'details': 'Acceso Denegado - Perfil Desconocido'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)