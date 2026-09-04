import os
import face_recognition
from flask import Flask, request, jsonify, render_template
from PIL import Image, ImageOps
import numpy as np

app = Flask(__name__)
KNOWN_FACES_DIR = 'known_people'
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

# Filtro de ingeniería para eliminar la rotación EXIF de los celulares
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
    name = request.form.get('name')
    if not file or not name: return jsonify({'error': 'Faltan datos'}), 400
    
    # Guardamos la imagen ya enderezada en la base de datos
    img_array = procesar_imagen_segura(file)
    Image.fromarray(img_array).save(os.path.join(KNOWN_FACES_DIR, f"{name}.jpg"))
    
    return jsonify({'message': f'Rostro de {name} guardado con rotación corregida.'})

@app.route('/recognize', methods=['POST'])
def recognize():
    file = request.files.get('file')
    if not file: return jsonify({'result': 'NO (Sube una foto)'}), 400
    
    unknown_image = procesar_imagen_segura(file)
    try:
        unknown_encoding = face_recognition.face_encodings(unknown_image)[0]
        print("📸 Rostro detectado por la webcam. Calculando biometría...", flush=True)
    except IndexError:
        print("❌ ERROR: La librería no encontró ningún rostro en la webcam.", flush=True)
        return jsonify({'result': 'NO (No hay rostro en la foto)'})

    for known_file in os.listdir(KNOWN_FACES_DIR):
        known_path = os.path.join(KNOWN_FACES_DIR, known_file)
        known_image = face_recognition.load_image_file(known_path)
        
        known_encodings = face_recognition.face_encodings(known_image, num_jitters=10)
        if not known_encodings:
            print(f"⚠️ ERROR LECTURA: No se detectó rostro en la bd para {known_file}", flush=True)
            continue
        
        face_distances = face_recognition.face_distance([known_encodings[0]], unknown_encoding)
        distancia = face_distances[0]
        print(f"📊 Distancia matemática con Jittering vs {known_file}: {distancia}", flush=True)

        if distancia < 0.68:
            nombre_limpio = known_file.split('_')[0].split('.')[0]
            print(f"✅ ¡MATCH ROBUSTO! Es {nombre_limpio}", flush=True)
            return jsonify({'result': f'SÍ (Es {nombre_limpio})'})
            
    print("⚠️ Rostro analizado, pero superó el umbral de tolerancia.", flush=True)
    return jsonify({'result': 'NO (Desconocido)'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)