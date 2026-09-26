"""Reconocimiento facial del escaneo en vivo, pensado para picos de carga (Fase 0 de docs/13_ARQUITECTURA_ESCALABILIDAD.md, puntos 1-5).

Qué cambió respecto al bucle de antes (traer a TODAS las personas del cliente, descifrar y comparar una por una en Python):
  * Candidatos = las personas del EVENTO con rostro (no las de todo el cliente).
  * Sus encodings se descifran UNA vez y quedan en memoria como una matriz numpy; cada escaneo es una sola operación vectorizada (~1 ms con 8.000).
  * La matriz se recarga sola cuando cambia `events.faces_version` (ver app/faces_version.py: sube en cada alta/baja/edición de un rostro).
  * El cálculo pesado (dlib) corre detrás de un semáforo propio: nunca más de FACE_CONCURRENCY a la vez por proceso; si la cola pasa de
    FACE_QUEUE_TIMEOUT segundos se responde 503 (el kiosco reintenta) en vez de acumular peticiones hasta caerse.
  * Un reconocimiento devuelve un `match_token` firmado y de corta vida: confirmar (`confirm=true`) o forzar (`force=true`) usa el token
    en vez de reenviar la foto, así cada persona se reconoce UNA vez.
El registro (25 jitters) no pasa por aquí. `RECOGNITION_JITTERS` queda en 10 como siempre: bajarlo es una decisión que se toma con datos
(scripts/bench_jitters.py, ver docs/14_FASE0_RESULTADOS.md)."""
import json
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import Event, EventAttendee, User

log = logging.getLogger("golden.faces")

FACE_TOLERANCE = 0.55                                                   # el mismo umbral de siempre (BiometricEngine.compare)
RECOGNITION_MAX_SIDE = int(os.getenv("RECOGNITION_MAX_SIDE", "640"))    # lado mayor máximo de la foto del escaneo (el navegador ya la manda así)
RECOGNITION_JITTERS = int(os.getenv("RECOGNITION_JITTERS", "10"))       # sin cambio: ver scripts/bench_jitters.py antes de bajarlo
FACE_CONCURRENCY = max(1, int(os.getenv("FACE_CONCURRENCY", "2")))      # cálculos dlib simultáneos por proceso
FACE_QUEUE_TIMEOUT = float(os.getenv("FACE_QUEUE_TIMEOUT", "20"))
MATCH_TOKEN_TTL = int(os.getenv("MATCH_TOKEN_TTL", "120"))              # segundos que vale una coincidencia para confirmarla sin reenviar la foto

_gate = threading.BoundedSemaphore(FACE_CONCURRENCY)


class Busy(Exception):
    """Demasiados reconocimientos en cola: el kiosco debe reintentar en unos segundos."""


# ------------------------------------------------------------------ matriz de encodings por evento
class _Index:
    def __init__(self, version: int, ids: List[str], matrix: np.ndarray):
        self.version, self.ids, self.matrix = version, ids, matrix

    def best(self, encoding) -> Tuple[Optional[str], float]:
        """(cédula, distancia) de la persona más parecida, o (None, inf) si no hay candidatos / la dimensión no coincide."""
        if not self.ids:
            return None, float("inf")
        vec = np.asarray(encoding, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self.matrix.shape[1]:
            return None, float("inf")
        dist = np.linalg.norm(self.matrix - vec, axis=1)
        i = int(np.argmin(dist))
        return self.ids[i], float(dist[i])


_indexes: Dict[int, _Index] = {}
_locks: Dict[int, threading.Lock] = {}
_meta = threading.Lock()


def clear_cache() -> None:
    """Olvida todas las matrices (las pruebas lo usan entre casos; en producción no hace falta: la versión de la base manda)."""
    with _meta:
        _indexes.clear()


def _lock_for(event_id: int) -> threading.Lock:
    with _meta:
        return _locks.setdefault(event_id, threading.Lock())


def _build(db: Session, event: Event, version: int) -> _Index:
    rows = (db.query(User.id, User.face_encoding)
            .join(EventAttendee, and_(EventAttendee.user_id == User.id, EventAttendee.tenant_id == User.tenant_id))
            .filter(EventAttendee.event_id == event.id, User.tenant_id == event.tenant_id, User.face_encoding != None)  # noqa: E711
            .all())
    ids, vectors, dim = [], [], None
    for uid, raw in rows:
        try:
            vec = np.asarray(json.loads(raw), dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            continue
        if dim is None:
            dim = vec.shape[0]
        if vec.shape[0] != dim:
            continue
        ids.append(uid)
        vectors.append(vec)
    matrix = np.vstack(vectors) if vectors else np.zeros((0, dim or 128), dtype=np.float32)
    log.info("matriz facial del evento %s: %d rostros (versión %s)", event.id, len(ids), version)
    return _Index(version, ids, matrix)


def event_index(db: Session, event: Event) -> _Index:
    """Matriz vigente del evento. `event.faces_version` ya viene cargado con el evento (sin una consulta extra por escaneo)."""
    version = event.faces_version or 0
    idx = _indexes.get(event.id)
    if idx is not None and idx.version >= version:
        return idx
    with _lock_for(event.id):                      # varios escaneos a la vez tras un cambio: uno reconstruye, los demás esperan y reutilizan
        idx = _indexes.get(event.id)
        if idx is None or idx.version < version:
            idx = _build(db, event, version)
            _indexes[event.id] = idx
        return idx


# ------------------------------------------------------------------ reconocer
def identify(db: Session, event: Event, image_bytes: bytes) -> Tuple[str, Optional[str]]:
    """Devuelve ("NO_FACE", None) | ("NO_MATCH", None) | ("MATCH", cédula). Levanta `Busy` si la cola de cálculo facial está saturada."""
    from app.biometrics import BiometricEngine    # import tardío: solo el servicio de biometría necesita dlib

    if not _gate.acquire(timeout=FACE_QUEUE_TIMEOUT):
        raise Busy()
    try:
        image = BiometricEngine.process_image_stream(image_bytes)
        encoding = BiometricEngine.extract_encoding(image, jitters=RECOGNITION_JITTERS, max_side=RECOGNITION_MAX_SIDE, largest_face=True)
    finally:
        _gate.release()
    if not encoding:
        return "NO_FACE", None
    uid, dist = event_index(db, event).best(encoding)
    if uid is not None and dist < FACE_TOLERANCE:
        return "MATCH", uid
    return "NO_MATCH", None


# ------------------------------------------------------------------ token de coincidencia (evita reconocer dos veces)
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="face-match")


def make_match_token(event_id: int, staff_id: int, user_id: str) -> str:
    return _serializer().dumps({"e": event_id, "s": staff_id, "u": user_id})


def read_match_token(token: str, event_id: int, staff_id: int) -> Optional[str]:
    """Cédula de la coincidencia, si el token es auténtico, no venció y es de ESTE evento y de ESTE operador; si no, None."""
    try:
        data = _serializer().loads(token, max_age=MATCH_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    return data["u"] if data.get("e") == event_id and data.get("s") == staff_id else None
