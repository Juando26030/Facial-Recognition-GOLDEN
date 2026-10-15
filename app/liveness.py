"""Reglas (sin dlib) de B2d —calidad de la selfie en el servidor— y de la prueba de movimiento de la puerta (opción A). Las medidas salen de `faces.analyze`.

B2d: la selfie de /aceptar debe tener UNA sola cara, de tamaño suficiente, nítida y con luz razonable; si no, la persona ve el motivo y la repite (nada se guarda).
Prueba de movimiento: el servidor elige al azar un giro (izquierda o derecha) y lo firma; la pantalla toma un fotograma DE FRENTE y otro tras pedir el giro. Pasa si los dos
tienen una sola cara, el primero está de frente, el segundo giró lo suficiente HACIA EL LADO PEDIDO y ambos son la misma persona. Una foto plana (impresa o en una pantalla)
no produce ese giro: al inclinarla, la nariz no se desplaza respecto de los ojos. Un video que gire justo hacia el lado pedido sí podría pasar: por eso sigue la supervisión.
Umbrales por variable de entorno, para calibrar sin programar."""
import os
import random
from typing import Optional

import numpy as np
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


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


# ------------------------------------------------------------------ prueba de movimiento (puerta)
LIVE_FRONT_MAX = _f("LIVENESS_FRONT_MAX", 0.15)        # |giro| máximo del fotograma «de frente»
LIVE_MIN_TURN = _f("LIVENESS_MIN_TURN", 0.18)          # cuánto debe cambiar el giro hacia el lado pedido
LIVE_SAME_PERSON = _f("LIVENESS_SAME_PERSON", 0.60)    # distancia máxima entre los dos fotogramas (misma persona)
LIVE_SIGN = 1 if (os.getenv("LIVENESS_SIGN") or "1").strip() != "-1" else -1     # +1: «a tu izquierda» = la nariz se mueve a la DERECHA de la imagen (cámara frontal sin espejo)
CHALLENGE_TTL = 45
DIRECTIONS = {"izquierda": 1, "derecha": -1}
TEXT = {"izquierda": "Ahora gira un poco la cabeza hacia tu IZQUIERDA", "derecha": "Ahora gira un poco la cabeza hacia tu DERECHA"}
FAIL_MSG = "No pudimos comprobar el movimiento. Intenta de nuevo siguiendo la indicación."


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="door-liveness")


def make_challenge(event_id: int, staff_id: int) -> dict:
    direction = random.SystemRandom().choice(sorted(DIRECTIONS))
    return {"token": _serializer().dumps({"e": event_id, "s": staff_id, "d": direction}), "direction": direction, "text": TEXT[direction]}


def read_challenge(token: str, event_id: int, staff_id: int) -> Optional[str]:
    try:
        data = _serializer().loads(token or "", max_age=CHALLENGE_TTL)
    except (BadSignature, SignatureExpired):
        return None
    return data["d"] if data.get("e") == event_id and data.get("s") == staff_id and data.get("d") in DIRECTIONS else None


def movement_ok(front: dict, turned: dict, direction: str) -> bool:
    if front.get("faces") != 1 or turned.get("faces") != 1 or front.get("yaw") is None or turned.get("yaw") is None:
        return False
    if abs(front["yaw"]) > LIVE_FRONT_MAX:
        return False
    if (turned["yaw"] - front["yaw"]) * DIRECTIONS[direction] * LIVE_SIGN < LIVE_MIN_TURN:
        return False
    a, b = front.get("encoding"), turned.get("encoding")
    if not a or not b:
        return False
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b))) <= LIVE_SAME_PERSON
