"""Reglas (sin dlib) de B2d —calidad de la selfie en el servidor—. Las medidas salen de `faces.analyze`.

B2d: la selfie de /aceptar debe tener UNA sola cara, de tamaño suficiente, nítida y con luz razonable; si no, la persona ve el motivo y la repite (nada se guarda).
(La prueba de movimiento en la puerta se retiró el 2026-10-16 por decisión del dueño del producto: la validación la hace la persona del equipo que supervisa; la migración 0068 y su columna `events.face_door_liveness`
quedan inactivas.) Umbrales por variable de entorno, para calibrar sin programar."""
import os
from typing import Optional


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


# ------------------------------------------------------------------ B2d: calidad de la selfie
SELFIE_MIN_FACE_H = _f("SELFIE_MIN_FACE_H", 0.20)      # alto de la cara / alto de la foto
SELFIE_MIN_SHARP = _f("SELFIE_MIN_SHARP", 25.0)        # varianza del laplaciano en la cara
SELFIE_MIN_LUMA, SELFIE_MAX_LUMA = _f("SELFIE_MIN_LUMA", 45.0), _f("SELFIE_MAX_LUMA", 225.0)


def selfie_problem(info: dict) -> Optional[str]:
    """El motivo en palabras sencillas, o None si la selfie sirve."""
    if info.get("faces", 0) == 0:
        return "No encontramos tu cara en la foto. Tómala de frente, con buena luz, y vuelve a intentarlo."
    if info["faces"] > 1:
        return "En la foto aparece más de una persona. Tómala solo tú."
    if info.get("face_h", 0) < SELFIE_MIN_FACE_H:
        return "Tu cara se ve muy pequeña. Acércate a la cámara y vuelve a tomarla."
    if info.get("luma", 0) < SELFIE_MIN_LUMA:
        return "La foto está muy oscura. Busca más luz, de frente, y vuelve a tomarla."
    if info.get("luma", 0) > SELFIE_MAX_LUMA:
        return "La foto tiene demasiada luz. Evita la luz directa sobre la cara y vuelve a tomarla."
    if info.get("sharp", 0) < SELFIE_MIN_SHARP:
        return "La foto se ve borrosa. Quédate quieto y vuelve a tomarla."
    return None
