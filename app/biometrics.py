import face_recognition
from PIL import Image, ImageOps
import numpy as np
import io

class BiometricEngine:
    @staticmethod
    def process_image_stream(file_stream: bytes) -> np.ndarray:
        image = Image.open(io.BytesIO(file_stream))
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGB')
        return np.array(image)

    @staticmethod
    def extract_encoding(image_array: np.ndarray, is_registration: bool = False):
        # Aumentamos el re-muestreo a 25 solo cuando es registro inicial
        jitters = 25 if is_registration else 10 
        encodings = face_recognition.face_encodings(image_array, num_jitters=jitters)
        return encodings[0].tolist() if encodings else None

    @staticmethod
    def compare(known_encoding: list, unknown_encoding: list, tolerance=0.55) -> bool:
        # Redujimos la tolerancia de 0.68 a 0.55. Es mucho más estricto.
        dist = face_recognition.face_distance([np.array(known_encoding)], np.array(unknown_encoding))[0]
        return dist < tolerance