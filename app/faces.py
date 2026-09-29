"""Reconocimiento facial del escaneo en vivo, pensado para picos de carga (Fase 0 de docs/13_ARQUITECTURA_ESCALABILIDAD.md, puntos 1-5).

Qué cambió respecto al bucle de antes (traer a TODAS las personas del cliente, descifrar y comparar una por una en Python):
  * Candidatos = las personas del EVENTO con rostro (no las de todo el cliente).
  * Sus encodings se descifran UNA vez y quedan en memoria como una matriz numpy; cada escaneo es una sola operación vectorizada (~1 ms con 8.000).
  * La matriz se recarga sola cuando cambia `events.faces_version` (ver app/faces_version.py: sube en cada alta/baja/edición de un rostro).
  * El cálculo pesado (dlib) corre en PROCESOS aparte (`FACE_PROCESSES`, app/face_worker.py) y no en hilos: dlib retiene el GIL mientras calcula, así que en un hilo
    congelaría al resto de la aplicación. Detrás de un semáforo: nunca más de FACE_CONCURRENCY pendientes a la vez por proceso web; si la espera pasa de
    FACE_QUEUE_TIMEOUT segundos se responde 503 (el kiosco reintenta) en vez de acumular peticiones hasta caerse. `FACE_PROCESSES=0` lo calcula en el mismo
    proceso (pruebas o instalaciones pequeñas).
  * Un reconocimiento devuelve un `match_token` firmado y de corta vida: confirmar (`confirm=true`) o forzar (`force=true`) usa el token
    en vez de reenviar la foto, así cada persona se reconoce UNA vez.
El registro (25 jitters) no pasa por aquí. `RECOGNITION_JITTERS` queda en 10 como siempre: bajarlo es una decisión que se toma con datos
(scripts/bench_jitters.py, ver docs/14_FASE0_RESULTADOS.md)."""
import json
import logging
import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Dict, List, Optional, Tuple

import numpy as np
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app import face_worker
from app.models import Event, EventAttendee, User

log = logging.getLogger("golden.faces")

FACE_TOLERANCE = 0.55                                                   # el mismo umbral de siempre (BiometricEngine.compare)
RECOGNITION_MAX_SIDE = int(os.getenv("RECOGNITION_MAX_SIDE", "640"))    # lado mayor máximo de la foto del escaneo (el navegador ya la manda así)
RECOGNITION_JITTERS = int(os.getenv("RECOGNITION_JITTERS", "10"))       # sin cambio: ver scripts/bench_jitters.py antes de bajarlo
FACE_PROCESSES = max(0, int(os.getenv("FACE_PROCESSES", "1")))          # procesos hijo con dlib por proceso web (0 = en el mismo proceso)
FACE_CONCURRENCY = max(1, int(os.getenv("FACE_CONCURRENCY", "4")))      # cálculos faciales pendientes (en curso + en cola) por proceso web
FACE_TASK_TIMEOUT = float(os.getenv("FACE_TASK_TIMEOUT", "180"))
FACE_QUEUE_TIMEOUT = float(os.getenv("FACE_QUEUE_TIMEOUT", "1"))         # espera corta: un hilo esperando turno es un hilo menos para cédulas y formularios; mejor 503 rápido y que el kiosco reintente
MATCH_TOKEN_TTL = int(os.getenv("MATCH_TOKEN_TTL", "300"))              # segundos que vale una coincidencia (y sus candidatos) para confirmarla sin reenviar la foto
MATCH_MARGIN = float(os.getenv("MATCH_MARGIN") or "0.06")                # si el mejor y el segundo candidato distan menos que esto, el resultado es DUDOSO (docs/14 §6.3)
TOP_CANDIDATES = 6                                                      # principal + los 5 siguientes que ve el operador

_gate = threading.BoundedSemaphore(FACE_CONCURRENCY)


class Busy(Exception):
    """Demasiados reconocimientos en cola (o el motor facial se está reiniciando): el kiosco debe reintentar en unos segundos."""


# ------------------------------------------------------------------ cálculo en procesos aparte
_pool: Optional[ProcessPoolExecutor] = None
_pool_lock = threading.Lock()


def _get_pool() -> Optional[ProcessPoolExecutor]:
    global _pool
    if FACE_PROCESSES == 0:
        return None
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=FACE_PROCESSES, mp_context=multiprocessing.get_context("spawn"), initializer=face_worker.child_init)
        return _pool


def _reset_pool() -> None:
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def extract(image_array, **kwargs) -> Optional[list]:
    """Encoding facial de una imagen (arreglo RGB). Todos los cálculos faciales de la app pasan por aquí: tope de pendientes, y procesos aparte."""
    if not _gate.acquire(timeout=FACE_QUEUE_TIMEOUT):
        raise Busy()
    try:
        pool = _get_pool()
        if pool is None:
            return face_worker.extract(image_array, kwargs)
        try:
            return pool.submit(face_worker.extract, image_array, kwargs).result(timeout=FACE_TASK_TIMEOUT)
        except BrokenProcessPool:
            log.error("el proceso del motor facial murió; se reinicia", exc_info=True)
            _reset_pool()
            raise Busy()
    finally:
        _gate.release()


def warmup() -> None:
    """Deja listo el motor facial (crea los procesos hijo y carga los modelos). Lo usa el arranque y /readyz."""
    pool = _get_pool()
    if pool is None:
        face_worker.warm()
    else:
        pool.submit(face_worker.ping).result(timeout=120)


def shutdown() -> None:
    _reset_pool()


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

    def top(self, encoding, k: int = TOP_CANDIDATES) -> List[Tuple[str, float]]:
        """Las `k` personas más parecidas, de la más cercana a la más lejana [(cédula, distancia)], con el mismo cálculo (una sola operación numpy)."""
        if not self.ids:
            return []
        vec = np.asarray(encoding, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self.matrix.shape[1]:
            return []
        dist = np.linalg.norm(self.matrix - vec, axis=1)
        # Una persona puede tener varios encodings (varias filas con la misma cédula): cada PERSONA cuenta una sola vez, con su mejor fila. Así el «segundo
        # candidato» de la regla DUDOSO es siempre OTRA persona, nunca la segunda foto de la misma.
        out, seen = [], set()
        for i in np.argsort(dist):
            uid = self.ids[int(i)]
            if uid in seen:
                continue
            seen.add(uid)
            out.append((uid, float(dist[int(i)])))
            if len(out) == k:
                break
        return out


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
            arr = np.asarray(json.loads(raw), dtype=np.float32)
        except (TypeError, ValueError):
            continue
        if arr.ndim == 1:
            arr = arr[None, :]
        if arr.ndim != 2:
            continue
        for vec in arr:                                # una fila por encoding: varios encodings de la misma persona = varias filas con su cédula
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
def confidence(dist: float) -> dict:
    """La distancia en palabras para el operador (umbrales de docs/14 §6.2). `level`: high | medium | low | out (fuera de la tolerancia)."""
    if dist < 0.40:
        return {"level": "high", "label": "Muy parecido"}
    if dist < 0.50:
        return {"level": "medium", "label": "Parecido"}
    if dist < FACE_TOLERANCE:
        return {"level": "low", "label": "Revisar con cuidado"}
    return {"level": "out", "label": "Fuera de la tolerancia"}


def is_doubtful(ranked: List[Tuple[str, float]]) -> bool:
    """DUDOSO: el mejor y el segundo candidato quedan a menos de MATCH_MARGIN (casi empatados). Con un solo candidato no hay con quién compararse."""
    return len(ranked) >= 2 and (ranked[1][1] - ranked[0][1]) < MATCH_MARGIN


def recognize(db: Session, event: Event, image_bytes: bytes) -> Tuple[str, List[Tuple[str, float]]]:
    """Devuelve ("NO_FACE", []) | ("NO_MATCH", []) | ("MATCH", ranked) con `ranked` = los TOP_CANDIDATES más cercanos (el primero está dentro de la tolerancia).
    Levanta `Busy` si la cola de cálculo facial está saturada. Un solo cálculo facial y una sola operación numpy: los candidatos no cuestan más."""
    from app.biometrics import BiometricEngine    # import tardío: PIL/numpy solo hacen falta aquí (dlib vive en el proceso hijo)

    image = BiometricEngine.process_image_stream(image_bytes)
    encoding = extract(image, jitters=RECOGNITION_JITTERS, max_side=RECOGNITION_MAX_SIDE, largest_face=True)
    if not encoding:
        return "NO_FACE", []
    ranked = event_index(db, event).top(encoding)
    if ranked and ranked[0][1] < FACE_TOLERANCE:
        return "MATCH", ranked
    return "NO_MATCH", []


def identify(db: Session, event: Event, image_bytes: bytes) -> Tuple[str, Optional[str]]:
    """Devuelve ("NO_FACE", None) | ("NO_MATCH", None) | ("MATCH", cédula). Lo usa el Control de Áreas; el registro usa `recognize` (candidatos y regla de duda)."""
    status, ranked = recognize(db, event, image_bytes)
    return status, (ranked[0][0] if status == "MATCH" else None)


# ------------------------------------------------------------------ token de coincidencia (evita reconocer dos veces)
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="face-match")


def make_match_token(event_id: int, staff_id: int, user_id: str, ranked: Optional[List[Tuple[str, float]]] = None, doubtful: bool = False) -> str:
    """Token firmado de corta vida de UN reconocimiento: la persona principal y los candidatos (cédula, distancia) del mismo cálculo. Solo viaja en cuerpos
    de petición (nunca en URLs ni logs)."""
    data = {"e": event_id, "s": staff_id, "u": user_id, "c": [[uid, round(dist, 4)] for uid, dist in (ranked or [])], "d": 1 if doubtful else 0}
    return _serializer().dumps(data)


def read_match_payload(token: str, event_id: int, staff_id: int) -> Optional[dict]:
    """Contenido del token (`u` principal, `c` candidatos, `d` dudoso) si es auténtico, no venció y es de ESTE evento y de ESTE operador; si no, None."""
    try:
        data = _serializer().loads(token, max_age=MATCH_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    return data if data.get("e") == event_id and data.get("s") == staff_id else None


def read_match_token(token: str, event_id: int, staff_id: int) -> Optional[str]:
    """Cédula de la coincidencia principal (ver `read_match_payload`), o None."""
    data = read_match_payload(token, event_id, staff_id)
    return data["u"] if data else None
