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

    # Carga masiva (bulk_register, 2026-09-23): medido en local con fotos reales de 7-12 MP, cada foto
    # costaba ~9s a 25 jitters a resolución completa (x2 antes de quitar el encoding duplicado). A 10
    # jitters (los mismos del escaneo en vivo) y con la foto reducida a 1024 px de lado mayor baja a
    # ~2.6s; la diferencia contra el encoding "completo" fue <0.11 de distancia (umbral de match: 0.55).
    BULK_JITTERS = 10
    BULK_MAX_SIDE = 1024

    @staticmethod
    def extract_encoding(image_array: np.ndarray, is_registration: bool = False, jitters=None, max_side=None):
        # Aumentamos el re-muestreo a 25 solo cuando es registro inicial
        if jitters is None:
            jitters = 25 if is_registration else 10
        if max_side and max(image_array.shape[:2]) > max_side:
            scale = max_side / max(image_array.shape[:2])
            small = Image.fromarray(image_array).resize(
                (int(image_array.shape[1] * scale), int(image_array.shape[0] * scale)), Image.LANCZOS)
            image_array = np.array(small)
        encodings = face_recognition.face_encodings(image_array, num_jitters=jitters)
        return encodings[0].tolist() if encodings else None

    @staticmethod
    def compare(known_encoding: list, unknown_encoding: list, tolerance=0.55) -> bool:
        # Redujimos la tolerancia de 0.68 a 0.55. Es mucho más estricto.
        dist = face_recognition.face_distance([np.array(known_encoding)], np.array(unknown_encoding))[0]
        return dist < tolerance