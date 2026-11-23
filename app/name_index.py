"""Búsqueda por NOMBRE cuando la cédula no está (respaldo de `POST /api/checkin-cedula`, cédula vieja o nueva leída con la cámara).

Antes (hasta el 19-nov-2026) cada escaneo sin cédula conocida cargaba TODAS las personas del cliente como objetos del ORM y comparaba el nombre contra cada una
(`_identity_name_matches`, con distancia de edición en Python): con 40.000 personas eran ~1 s de CPU y decenas de MB por escaneo fallido, y con varias estaciones a la vez el
servidor se ponía lento para todos. Ahora:

* Un índice por cliente y por proceso: las palabras normalizadas de cada nombre (sin tildes, minúsculas) y, por cada palabra distinta, quiénes la tienen.
* La comparación (prefijo en ambos sentidos + tolerancia a errores de tipeo, EXACTAMENTE la misma regla de siempre) se hace UNA vez por palabra distinta del vocabulario,
  no una vez por persona; y el resultado de cada par (palabra de la base, palabra escaneada) se recuerda entre escaneos (los nombres se repiten muchísimo).
* Frescura sin esperar: antes de usar el índice se pide a la base una huella de los nombres del cliente (conteo + suma de `hashtext`, un solo número; ~10 ms con 40.000).
  Si alguien se creó, se borró o cambió de nombre, la huella cambia y el índice se reconstruye (solo id y nombres, sin objetos del ORM). Nunca hay coincidencias viejas.
* Prefiltro EXACTO con numpy antes de la distancia de edición: la distancia (con transposiciones) entre dos palabras nunca es menor que la mitad de la diferencia de sus
  conteos de letras, ni que la diferencia de largos. Esas cotas se calculan para todo el vocabulario de una vez; solo las palabras que podrían pasar llegan a la
  comparación lenta (que es la de siempre). Los prefijos se buscan directo (diccionario y lista ordenada). Mismo resultado que antes, comprobado en
  tests/test_name_index.py contra la regla original.
* Se devuelven como máximo `MAX_RESULTS` candidatos (el quiosco solo usa si hay o no, y filtra el directorio por el nombre); `total` dice cuántos eran.

Puro salvo `find` (la única que toca la base). Nada de nombres ni cédulas en logs."""
import bisect
import os
import threading
import time
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

import numpy as np

MAX_RESULTS = 50
MAX_TENANTS = int(os.getenv("NAME_INDEX_MAX_TENANTS", "8"))         # índices guardados por proceso (uno por cliente); el más viejo sale primero


def _words(text: Optional[str]) -> list:
    from app.routers.events import _words as words           # la MISMA normalización del buscador (sin tildes, minúsculas, palabras)
    return words(text)


@lru_cache(maxsize=200_000)
def _pair_ok(db_word: str, scanned_word: str) -> bool:
    """La regla de `api._identity_name_matches` para UNA palabra de la base contra UNA escaneada: prefijo en cualquier sentido o error de tipeo tolerable."""
    if scanned_word.startswith(db_word) or db_word.startswith(scanned_word):
        return True
    from app.routers.events import _typo_match
    return _typo_match(db_word, scanned_word)


_ALPHA = {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_NCOLS = 28                                                          # a-z, dígito, cualquier otro carácter (agrupar categorías solo puede BAJAR la cota: sigue siendo válida)


def _code(ch: str) -> int:
    return _ALPHA.get(ch, 26 if ch.isdigit() else 27)


def _cnt(word: str) -> np.ndarray:
    v = np.zeros(_NCOLS, np.int8)
    for ch in word:
        v[_code(ch)] += 1
    return v


def _l1(mat_t: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Diferencia de conteos de letras (suma de |a - b|) entre `v` y cada columna de `mat_t` (letra × palabra)."""
    return np.abs(mat_t - v[:, None]).sum(0, dtype=np.int16)


def _limit(short_len: int) -> int:
    """Errores tolerados por `_typo_match` según el largo de la palabra más corta (4-6 letras: 1; 7 o más: 2)."""
    return 1 if short_len <= 6 else 2


class NameIndex:
    """people[i] = (id, first_name, last_name, cuántas palabras distintas tiene su nombre); words[j] = palabra del vocabulario; owners[j] = [i, …] de quienes la tienen."""
    __slots__ = ("people", "nwords", "words", "wpos", "owners", "lens", "counts", "sorted_words", "by_len", "_longer", "_codes", "signature", "built_at")

    def __init__(self, rows: Iterable[Tuple[str, Optional[str], Optional[str]]], signature=None):
        self.people: List[tuple] = []
        vocab: dict = {}
        for pid, first, last in rows:
            words = set(_words(f"{first or ''} {last or ''}"))
            if not words:                                           # sin nombre: nunca coincide (igual que antes)
                continue
            i = len(self.people)
            self.people.append((pid, first, last, len(words)))
            for w in words:
                vocab.setdefault(w, []).append(i)
        self.nwords = np.fromiter((p[3] for p in self.people), np.int32, len(self.people))
        self.words = list(vocab)
        self.wpos = {w: j for j, w in enumerate(self.words)}
        self.owners = [np.array(vocab[w], np.int32) for w in self.words]
        self.lens = np.fromiter((len(w) for w in self.words), np.int32, len(self.words))
        self._codes = [[_code(ch) for ch in w] for w in self.words]
        self.counts = self._matrix(None)
        self.sorted_words = sorted(self.words)
        groups: dict = {}
        for j, n in enumerate(self.lens.tolist()):
            groups.setdefault(n, []).append(j)
        self.by_len = {}                                            # largo -> (índices, conteos contiguos): sin copiar en cada consulta
        for n, js in groups.items():
            ids = np.array(js, np.int32)
            self.by_len[n] = (ids, np.ascontiguousarray(self.counts[ids].T))          # traspuesta (letra × palabra): sumar 28 vectores largos es mucho más rápido
        self._longer: dict = {}
        self.signature = signature
        self.built_at = time.monotonic()

    def _matrix(self, upto: Optional[int]) -> np.ndarray:
        """Conteo de letras de cada palabra (o de sus primeras `upto` letras)."""
        rows, cols = [], []
        for j, codes in enumerate(self._codes):
            part = codes if upto is None else codes[:upto]
            rows.extend([j] * len(part))
            cols.extend(part)
        m = np.zeros((len(self._codes), _NCOLS), np.int8)          # ninguna palabra tiene 128 veces la misma letra
        if rows:
            np.add.at(m, (np.array(rows, np.int32), np.array(cols, np.int32)), 1)
        return m

    def _longer_than(self, n: int) -> tuple:
        """Palabras de más de `n` letras: (índices, largos, conteo completo, conteo de sus primeras `n` letras). Se arma la primera vez que se necesita y queda guardado."""
        got = self._longer.get(n)
        if got is None:
            ids = np.nonzero(self.lens > n)[0].astype(np.int32)
            prefix = self._matrix(n)[ids]
            got = self._longer[n] = (ids, self.lens[ids], np.ascontiguousarray(self.counts[ids].T), np.ascontiguousarray(prefix.T))
        return got

    def _ok_words(self, s: str) -> set:
        """Índices del vocabulario que pasan la regla contra la palabra escaneada `s` (exacto: candidatos por cotas, confirmados con `_pair_ok`)."""
        n, ok = len(s), set()
        for k in range(1, n + 1):                                   # palabras de la base que son prefijo de `s`
            j = self.wpos.get(s[:k])
            if j is not None:
                ok.add(j)
        lo = bisect.bisect_left(self.sorted_words, s)               # palabras de la base que empiezan por `s`
        for w in self.sorted_words[lo:]:
            if not w.startswith(s):
                break
            ok.add(self.wpos[w])
        if n < 4:
            return ok                                               # error de tipeo: la palabra más corta necesita 4+ letras (y aquí la corta es `s` o una de largo <= n)
        cs, cand = _cnt(s), []
        for L, (js, mat) in self.by_len.items():                    # la palabra de la base es la corta (o igual): contra `s` entera y contra su inicio del mismo largo
            if L < 4 or L > n:
                continue
            lim = _limit(L)
            sel = _l1(mat, _cnt(s[:L])) <= 2 * lim
            if n - L <= lim:
                sel |= _l1(mat, cs) <= 2 * lim
            cand.extend(js[sel].tolist())
        ids, lens, full, prefix = self._longer_than(n)              # `s` es la corta: contra la palabra entera y contra su inicio de largo n
        if len(ids):
            lim = _limit(n)
            sel = _l1(prefix, cs) <= 2 * lim
            near = lens - n <= lim
            if near.any():
                sel |= near & (_l1(full, cs) <= 2 * lim)
            cand.extend(ids[sel].tolist())
        for j in cand:
            if j not in ok and _pair_ok(self.words[j], s):
                ok.add(j)
        return ok

    def match(self, scanned_name: str, limit: int = MAX_RESULTS) -> Tuple[list, int]:
        """Personas cuyo nombre coincide con `scanned_name` con la regla de siempre: CADA palabra del nombre en la base tiene alguna palabra escaneada que la prefija, es prefijada
        por ella o se le parece salvo un error de tipeo. Devuelve ([{id, first_name, last_name}] hasta `limit`, total)."""
        scanned = sorted(set(_words(scanned_name)))
        if not scanned or not self.words:
            return [], 0
        ok: set = set()
        for s in scanned:
            ok |= self._ok_words(s)
        if not ok:
            return [], 0
        hits = np.bincount(np.concatenate([self.owners[j] for j in ok]), minlength=len(self.people))     # cuántas palabras de cada persona pasaron
        found = np.nonzero(hits == self.nwords)[0].tolist()                                             # coincide si pasaron TODAS las de su nombre
        return [{"id": self.people[i][0], "first_name": self.people[i][1], "last_name": self.people[i][2]} for i in found[:limit]], len(found)


_INDEXES: dict = {}                    # tenant_id -> NameIndex
_LOCK = threading.Lock()
_BUILD_LOCKS: dict = {}                # tenant_id -> Lock: varios escaneos fallidos a la vez esperan UNA sola reconstrucción


def _signature(db, tenant_id: str):
    from sqlalchemy import text
    row = db.execute(text("SELECT count(*), coalesce(sum(hashtext(id || '|' || coalesce(first_name, '') || '|' || coalesce(last_name, ''))::bigint), 0) "
                          "FROM users WHERE tenant_id = :t"), {"t": tenant_id}).one()
    return (int(row[0]), int(row[1]))


def index_for(db, tenant_id: str) -> NameIndex:
    sig = _signature(db, tenant_id)
    idx = _INDEXES.get(tenant_id)
    if idx is not None and idx.signature == sig:
        return idx
    with _LOCK:
        build_lock = _BUILD_LOCKS.setdefault(tenant_id, threading.Lock())
    with build_lock:
        idx = _INDEXES.get(tenant_id)
        if idx is not None and idx.signature == sig:                # otro hilo ya lo reconstruyó mientras esperábamos
            return idx
        from app.models import User
        rows = db.query(User.id, User.first_name, User.last_name).filter(User.tenant_id == tenant_id).yield_per(5000)
        idx = NameIndex(rows, signature=sig)
        with _LOCK:
            _INDEXES[tenant_id] = idx
            while len(_INDEXES) > MAX_TENANTS:
                oldest = min(_INDEXES, key=lambda t: _INDEXES[t].built_at)
                _INDEXES.pop(oldest, None)
        return idx


def find(db, tenant_id: str, scanned_name: str, limit: int = MAX_RESULTS) -> Tuple[list, int]:
    """Candidatos por nombre dentro del cliente (ninguno se acredita solo: el operador decide). ([…hasta `limit`], total)."""
    if not _words(scanned_name):
        return [], 0
    return index_for(db, tenant_id).match(scanned_name, limit)


def clear() -> None:
    """Para pruebas."""
    with _LOCK:
        _INDEXES.clear()
    _pair_ok.cache_clear()
