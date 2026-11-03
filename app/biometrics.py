"""Motor biométrico (dlib vía `face_recognition`).

`face_recognition` se importa SOLO cuando hace falta (`_fr()`): los servicios «web» y «publico» (ver app/main.py, APP_MODE) nunca cargan dlib ni sus
modelos (~100 MB de memoria y varios segundos de arranque); solo el servicio de biometría lo hace."""
import io
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

from app import safe_limits

_fr_module = None


def _fr():
    """Importa `face_recognition` la primera vez que se usa."""
    global _fr_module
    if _fr_module is None:
        import face_recognition
        _fr_module = face_recognition
    return _fr_module


class BiometricEngine:
    @staticmethod
    def process_image_stream(file_stream: bytes) -> np.ndarray:
        safe_limits.check_image_dimensions(file_stream)
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
    def extract_encoding(image_array: np.ndarray, is_registration: bool = False, jitters=None, max_side=None, largest_face: bool = False) -> Optional[list]:
        """Encoding (128 números) del rostro de la foto, o None si no hay ninguno.

        `max_side`: reduce la foto (lado mayor) antes de procesarla. `largest_face`: si hay varios rostros, se queda con el más grande (el de quien está
        frente al kiosco) en vez del primero que encuentre dlib; además detecta primero sin sobremuestrear (más rápido) y solo reintenta con
        sobremuestreo si no encontró nada."""
        # Aumentamos el re-muestreo a 25 solo cuando es registro inicial
        if jitters is None:
            jitters = 25 if is_registration else 10
        if max_side and max(image_array.shape[:2]) > max_side:
            scale = max_side / max(image_array.shape[:2])
            small = Image.fromarray(image_array).resize(
                (int(image_array.shape[1] * scale), int(image_array.shape[0] * scale)), Image.LANCZOS)
            image_array = np.array(small)
        fr = _fr()
        if largest_face:
            locations = fr.face_locations(image_array, number_of_times_to_upsample=0) or fr.face_locations(image_array, number_of_times_to_upsample=1)
            if not locations:
                return None
            top, right, bottom, left = max(locations, key=lambda box: (box[2] - box[0]) * (box[1] - box[3]))
            encodings = fr.face_encodings(image_array, known_face_locations=[(top, right, bottom, left)], num_jitters=jitters)
        else:
            encodings = fr.face_encodings(image_array, num_jitters=jitters)
        return encodings[0].tolist() if encodings else None

    @staticmethod
    def analyze_face(image_array: np.ndarray, max_side: int = 640, encode: bool = False) -> dict:
        """Medidas de la foto para B2d (calidad de la selfie) y la prueba de movimiento (app/liveness.py), SIN guardar nada:
        `faces` (cuántas caras), `face_h` (alto de la cara más grande / alto de la foto), `yaw` (giro horizontal: (nariz − punto medio de los ojos) / distancia entre ojos;
        0 = de frente), `sharp` (varianza del laplaciano en la cara) y `luma` (brillo medio de la cara), y con `encode` el encoding de esa cara (1 jitter: solo para comparar
        que dos fotogramas son de la misma persona)."""
        if max_side and max(image_array.shape[:2]) > max_side:
            scale = max_side / max(image_array.shape[:2])
            image_array = np.array(Image.fromarray(image_array).resize((int(image_array.shape[1] * scale), int(image_array.shape[0] * scale)), Image.LANCZOS))
        fr = _fr()
        boxes = fr.face_locations(image_array, number_of_times_to_upsample=0) or fr.face_locations(image_array, number_of_times_to_upsample=1)
        out = {"faces": len(boxes), "face_h": 0.0, "yaw": None, "sharp": 0.0, "luma": 0.0, "encoding": None}
        if not boxes:
            return out
        top, right, bottom, left = max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))
        out["face_h"] = (bottom - top) / float(image_array.shape[0])
        crop = image_array[max(0, top):bottom, max(0, left):right].astype(np.float32)
        if crop.size:
            gray = crop @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            out["luma"] = float(gray.mean())
            if gray.shape[0] > 2 and gray.shape[1] > 2:
                lap = gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4 * gray[1:-1, 1:-1]
                out["sharp"] = float(lap.var())
        marks = fr.face_landmarks(image_array, face_locations=[(top, right, bottom, left)])
        if marks:
            m = marks[0]
            le, re_, nose = (np.mean(m.get(k) or [(0, 0)], axis=0) for k in ("left_eye", "right_eye", "nose_tip"))
            eye_dist = float(np.linalg.norm(re_ - le))
            if eye_dist > 1:
                out["yaw"] = float((nose[0] - (le[0] + re_[0]) / 2) / eye_dist)
        if encode:
            enc = fr.face_encodings(image_array, known_face_locations=[(top, right, bottom, left)], num_jitters=1)
            out["encoding"] = enc[0].tolist() if enc else None
        return out

    @staticmethod
    def compare(known_encoding: list, unknown_encoding: list, tolerance=0.55) -> bool:
        # Redujimos la tolerancia de 0.68 a 0.55. Es mucho más estricto.
        dist = _fr().face_distance([np.array(known_encoding)], np.array(unknown_encoding))[0]
        return dist < tolerance
