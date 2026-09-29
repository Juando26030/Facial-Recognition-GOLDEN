"""Cachés y limitadores EN MEMORIA de un solo proceso (Fase 0, escalabilidad). Nada de esto es la fuente de verdad: solo evita repetir
consultas idénticas durante unos segundos y frena abusos baratos. Con varios procesos (Gunicorn) cada uno tiene los suyos: por eso los
tiempos son cortos y cualquier decisión que importe (cupo, duplicados, precios) se vuelve a comprobar en el servidor contra la base."""
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Tuple

_MISSING = object()


class TTLCache:
    """Diccionario con vencimiento. `get_or_set(clave, fabrica)` no bloquea a los demás mientras calcula (dos hilos pueden calcular a la vez la
    primera vez; el resultado es el mismo, así que da igual cuál gane)."""

    def __init__(self, ttl: float, maxsize: int = 2048):
        self.ttl, self.maxsize = ttl, maxsize
        self._data: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._key_locks: Dict[Any, threading.Lock] = {}

    def get(self, key, default=None):
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            if hit:
                del self._data[key]
        return default

    def set(self, key, value) -> None:
        with self._lock:
            if len(self._data) >= self.maxsize:
                now = time.monotonic()
                self._data = {k: v for k, v in self._data.items() if v[0] > now}
                if len(self._data) >= self.maxsize:
                    self._data.clear()
            self._data[key] = (time.monotonic() + self.ttl, value)

    def get_or_set(self, key, factory: Callable[[], Any]):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            value = factory()
            self.set(key, value)
        return value

    def get_or_compute(self, key, factory: Callable[[], Any]):
        """Como `get_or_set`, pero con UNA sola recarga a la vez por clave: al vencer la entrada, un hilo recalcula y los demás esperan ese resultado en vez de
        repetir la consulta todos a la vez (efecto manada). Si `factory` falla no se guarda nada y el siguiente en la fila lo intenta."""
        value = self.get(key, _MISSING)
        if value is not _MISSING:
            return value
        with self._lock:
            if len(self._key_locks) > self.maxsize:
                self._key_locks.clear()
            gate = self._key_locks.setdefault(key, threading.Lock())
        with gate:
            value = self.get(key, _MISSING)          # otro hilo pudo recargarla mientras esperábamos el turno
            if value is _MISSING:
                value = factory()
                self.set(key, value)
            return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class SlidingLimiter:
    """Limitador de ventana deslizante en memoria: `hit(clave, máximo, ventana_s)` devuelve False si esa clave ya hizo `máximo` peticiones en la ventana."""

    def __init__(self, maxkeys: int = 50000):
        self._hits: Dict[Any, Deque[float]] = {}
        self._lock = threading.Lock()
        self.maxkeys = maxkeys

    def hit(self, key, max_hits: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.maxkeys:
                    self._prune(now)
                q = self._hits[key] = deque()
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= max_hits:
                return False
            q.append(now)
            return True

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] < now - 3600]:
            del self._hits[k]
        if len(self._hits) >= self.maxkeys:
            self._hits.clear()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
