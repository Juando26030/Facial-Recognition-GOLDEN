"""Fase 9-B: copia semanal CIFRADA del respaldo a OneDrive (Microsoft 365) por Microsoft Graph, fuera del proyecto de Google.

Paso semanal del Job de operaciones (`app/ops_runner.py`, tarea «offsite-copy»; corre cada hora pero solo copia cuando toca):
  1. toma el respaldo MÁS RECIENTE del bucket (`db/…/*.sql.gz`), 2. lo CIFRA (Fernet por trozos, llave BACKUP_COPY_ENCRYPTION_KEY) al vuelo,
  3. lo sube a la carpeta de OneDrive (PUT simple si ≤ 4 MB, sesión de carga por trozos si es mayor), 4. conserva solo las últimas N copias
  (borra ÚNICAMENTE archivos `golden_db_*.gwbk` de esa carpeta), 5. deja el resultado en `offsite/state.json` del bucket de respaldos (se muestra en /sistema).
Sin variables de OneDrive el paso no hace nada («copia semanal no configurada»). Si falla, o pasan más de 10 días sin copia, el paso FALLA y el Job
avisa por correo (ALERT_EMAIL, una vez cada REALERT_H horas). Nunca hay datos personales en el estado ni en los logs: solo fechas, tamaños y motivos.

Formato del archivo (`.gwbk`): cabecera `GWBK1\\n` y luego, por cada trozo de 8 MB de texto plano, `[4 bytes: largo][token Fernet]`. El texto plano de cada trozo
empieza con 8 bytes de índice y 1 byte «último»: así se detecta un archivo truncado, con trozos repetidos o reordenados. Se abre con `scripts/open_backup_copy.py`.

Detalles de Microsoft Graph NO verificados contra la documentación oficial desde este entorno (bloqueada): ver docs/24_COPIA_SEMANAL_ONEDRIVE.md, «Qué falta verificar».
"""
from __future__ import annotations

import json
import logging
import os
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Callable, Iterator, Optional, Tuple

from app.timeutil import utcnow

log = logging.getLogger("golden.offsite")

MAGIC = b"GWBK1\n"
PLAIN_CHUNK = 8 * 1024 * 1024
SMALL_LIMIT = 4 * 1024 * 1024                  # Graph: PUT simple hasta 4 MB; más grande, sesión de carga
SESSION_CHUNK = 10 * 1024 * 1024               # múltiplo de 320 KiB (exigido por Graph en cada trozo menos el último)
STATE_KEY = "offsite/state.json"
NAME_PREFIX, NAME_SUFFIX = "golden_db_", ".gwbk"
NOT_CONFIGURED = "copia semanal no configurada"
GRAPH = "https://graph.microsoft.com/v1.0"
REQUIRED = ("ONEDRIVE_TENANT_ID", "ONEDRIVE_CLIENT_ID", "ONEDRIVE_CLIENT_SECRET", "BACKUP_COPY_ENCRYPTION_KEY")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def configured() -> bool:
    return all(_env(k) for k in REQUIRED) and bool(_env("ONEDRIVE_DRIVE_ID") or _env("ONEDRIVE_DRIVE_USER")) and bool(_env("ONEDRIVE_FOLDER"))


def keep_n() -> int:
    try:
        return max(2, int(_env("OFFSITE_KEEP_WEEKS", "8")))
    except ValueError:
        return 8


# ------------------------------------------------------------------ cifrado por trozos
def _fernet_len(n: int) -> int:
    """Largo exacto (bytes) del token Fernet de `n` bytes de texto plano: 1+8+16 de cabecera, relleno PKCS7 a 16, 32 de HMAC, todo en base64 con relleno."""
    raw = 1 + 8 + 16 + (n // 16 + 1) * 16 + 32
    return 4 * ((raw + 2) // 3)


def encrypted_size(plain_size: int, chunk: int = PLAIN_CHUNK) -> int:
    n_chunks = max(1, -(-plain_size // chunk))
    total = len(MAGIC)
    for i in range(n_chunks):
        data = chunk if i < n_chunks - 1 else plain_size - chunk * (n_chunks - 1)
        total += 4 + _fernet_len(9 + data)
    return total


def encrypt_stream(src, key: str, chunk: int = PLAIN_CHUNK) -> Iterator[bytes]:
    """Lee `src` (objeto con .read) y entrega el archivo cifrado en pedazos, sin cargarlo entero en memoria."""
    from cryptography.fernet import Fernet
    f = Fernet(key.encode() if isinstance(key, str) else key)
    yield MAGIC
    idx, cur = 0, _read_full(src, chunk)
    while True:
        nxt = _read_full(src, chunk) if len(cur) == chunk else b""
        last = 0 if nxt else 1
        token = f.encrypt(struct.pack(">QB", idx, last) + cur)
        yield struct.pack(">I", len(token)) + token
        if last:
            return
        idx, cur = idx + 1, nxt


def _read_full(src, n: int) -> bytes:
    parts, got = [], 0
    while got < n:
        b = src.read(n - got)
        if not b:
            break
        parts.append(b)
        got += len(b)
    return b"".join(parts)


def decrypt_stream(src, key: str) -> Iterator[bytes]:
    """Inversa de encrypt_stream. Levanta ValueError si el archivo está truncado, alterado o desordenado."""
    from cryptography.fernet import Fernet, InvalidToken
    f = Fernet(key.encode() if isinstance(key, str) else key)
    if _read_full(src, len(MAGIC)) != MAGIC:
        raise ValueError("No es un archivo de copia de GoldenWeb (cabecera distinta).")
    expect = 0
    while True:
        head = _read_full(src, 4)
        if len(head) < 4:
            raise ValueError("Archivo truncado: falta el último trozo.")
        (ln,) = struct.unpack(">I", head)
        token = _read_full(src, ln)
        if len(token) < ln:
            raise ValueError("Archivo truncado dentro de un trozo.")
        try:
            plain = f.decrypt(token)
        except InvalidToken as e:
            raise ValueError("Llave incorrecta o archivo alterado.") from e
        idx, last = struct.unpack(">QB", plain[:9])
        if idx != expect:
            raise ValueError("Trozos desordenados o repetidos.")
        yield plain[9:]
        expect += 1
        if last:
            if src.read(1):
                raise ValueError("Hay datos de más después del último trozo.")
            return


class _Rechunk:
    """Junta pedazos de tamaño variable y los entrega en trozos exactos de `size` (el último puede ser menor)."""

    def __init__(self, it: Iterator[bytes], size: int):
        self.it, self.size, self.buf = iter(it), size, bytearray()

    def __iter__(self):
        for part in self.it:
            self.buf += part
            while len(self.buf) >= self.size:
                out, self.buf = bytes(self.buf[: self.size]), self.buf[self.size:]
                yield out
        if self.buf:
            yield bytes(self.buf)


# ------------------------------------------------------------------ cliente de Microsoft Graph
class GraphError(RuntimeError):
    pass


def _urlopen(req: urllib.request.Request, timeout: int = 120) -> Tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 — URLs fijas de Microsoft o la de sesión que Graph entrega
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", dict(e.headers or {})


class GraphClient:
    """Mínimo necesario de Graph. `http(method, url, headers, data) -> (status, body, headers)` se puede reemplazar en las pruebas."""

    def __init__(self, http: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep):
        self._http = http or self._real
        self._sleep = sleep
        self._token: Optional[str] = None
        tenant = _env("ONEDRIVE_TENANT_ID")
        self.token_url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"
        drive_id, user = _env("ONEDRIVE_DRIVE_ID"), _env("ONEDRIVE_DRIVE_USER")
        self.base = f"{GRAPH}/drives/{urllib.parse.quote(drive_id)}" if drive_id else f"{GRAPH}/users/{urllib.parse.quote(user)}/drive"
        self.folder = "/".join(p for p in _env("ONEDRIVE_FOLDER").replace("\\", "/").split("/") if p and p not in (".", ".."))

    @staticmethod
    def _real(method, url, headers, data):
        return _urlopen(urllib.request.Request(url, data=data, method=method, headers=headers))

    def _call(self, method: str, url: str, headers: Optional[dict] = None, data: Optional[bytes] = None, ok=(200, 201, 202, 204), auth: bool = True):
        """Con reintentos ante 429/5xx (respeta Retry-After). Levanta GraphError con un motivo SIN secretos ni datos personales."""
        last = ""
        for attempt in range(4):
            h = dict(headers or {})
            if auth:
                h["Authorization"] = f"Bearer {self.token()}"
            status, body, rh = self._http(method, url, h, data)
            if status in ok:
                return status, body, rh
            if status == 401 and auth and attempt == 0:
                self._token = None                            # token vencido: se pide otro una vez
                continue
            last = f"HTTP {status} {self._err_code(body)}"
            if status in (429, 500, 502, 503, 504) and attempt < 3:
                try:
                    wait = float(rh.get("Retry-After") or rh.get("retry-after") or 2 ** attempt)
                except ValueError:
                    wait = 2 ** attempt
                self._sleep(min(wait, 60))
                continue
            break
        raise GraphError(f"{method} {self._where(url)}: {last}")

    @staticmethod
    def _err_code(body: bytes) -> str:
        try:
            e = json.loads(body.decode("utf-8", "replace")).get("error")
            return (e.get("code") if isinstance(e, dict) else str(e or ""))[:80]
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _where(url: str) -> str:
        return urllib.parse.urlsplit(url).path[-60:]       # solo la ruta final: el enlace de sesión de carga lleva credenciales en la consulta

    def token(self) -> str:
        if self._token:
            return self._token
        form = urllib.parse.urlencode({"client_id": _env("ONEDRIVE_CLIENT_ID"), "client_secret": _env("ONEDRIVE_CLIENT_SECRET"),
                                       "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}).encode()
        _, body, _ = self._call("POST", self.token_url, {"Content-Type": "application/x-www-form-urlencoded"}, form, ok=(200,), auth=False)
        tok = json.loads(body.decode()).get("access_token")
        if not tok:
            raise GraphError("La respuesta de Microsoft no trajo access_token.")
        self._token = tok
        return tok

    def _item_path(self, name: str) -> str:
        return f"{self.base}/root:/{urllib.parse.quote(self.folder + '/' + name)}"

    def upload(self, name: str, parts: Iterator[bytes], total: int) -> None:
        if total <= SMALL_LIMIT:
            data = b"".join(parts)
            self._call("PUT", self._item_path(name) + ":/content", {"Content-Type": "application/octet-stream"}, data, ok=(200, 201))
            return
        body = json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode()
        _, resp, _ = self._call("POST", self._item_path(name) + ":/createUploadSession", {"Content-Type": "application/json"}, body, ok=(200,))
        url = json.loads(resp.decode()).get("uploadUrl")
        if not url:
            raise GraphError("Graph no devolvió uploadUrl.")
        pos = 0
        for piece in _Rechunk(parts, SESSION_CHUNK):
            end = pos + len(piece) - 1
            final = end + 1 == total
            self._call("PUT", url, {"Content-Length": str(len(piece)), "Content-Range": f"bytes {pos}-{end}/{total}", "Content-Type": "application/octet-stream"},
                       piece, ok=(200, 201) if final else (202,), auth=False)
            pos = end + 1
        if pos != total:
            raise GraphError(f"Se subieron {pos} bytes y se esperaban {total}.")

    def list_copies(self) -> list:
        """[(id, name)] de los archivos de copia (golden_db_*.gwbk) de la carpeta. Carpeta inexistente → []."""
        url = f"{self.base}/root:/{urllib.parse.quote(self.folder)}:/children?$select=id,name,size&$top=200"
        out = []
        while url:
            try:
                _, body, _ = self._call("GET", url, ok=(200,))
            except GraphError as e:
                if "HTTP 404" in str(e):
                    return []
                raise
            js = json.loads(body.decode())
            out += [(v["id"], v["name"]) for v in js.get("value", []) if v.get("name", "").startswith(NAME_PREFIX) and v["name"].endswith(NAME_SUFFIX) and "folder" not in v]
            url = js.get("@odata.nextLink")
            if url and not url.startswith(GRAPH + "/"):
                raise GraphError("Graph devolvió un enlace de página fuera de graph.microsoft.com; no se le envía el token.")
        return out

    def delete(self, item_id: str) -> None:
        self._call("DELETE", f"{self.base}/items/{urllib.parse.quote(item_id)}", ok=(200, 204, 404))


# ------------------------------------------------------------------ estado (en el bucket de respaldos)
def _bucket():
    from app.ops_runner import _bucket as b
    return b()


def load_state(bucket=None) -> dict:
    try:
        blob = (bucket or _bucket()).blob(STATE_KEY)
        if not blob.exists():
            return {}
        return json.loads(blob.download_as_text())
    except Exception:  # noqa: BLE001 — sin estado se trata como primera vez
        log.warning("no se pudo leer el estado de la copia semanal", exc_info=True)
        return {}


def save_state(state: dict, bucket=None) -> None:
    (bucket or _bucket()).blob(STATE_KEY).upload_from_string(json.dumps(state, ensure_ascii=False, indent=1), content_type="application/json")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _parse(s: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.rstrip("Z")) if s else None
    except ValueError:
        return None


def due(now: datetime, state: dict) -> bool:
    """now = UTC ingenuo. Toca copiar si no hay copia buena o la última tiene ≥ OFFSITE_EVERY_DAYS (6), pasada la hora local OFFSITE_HOUR (6) y sin intentos en las últimas 6 h."""
    from app.timeutil import to_local
    ok, tried = _parse(state.get("last_ok_at")), _parse(state.get("last_attempt_at"))
    if ok and now - ok < timedelta(days=float(_env("OFFSITE_EVERY_DAYS", "6"))):
        return False
    if tried and now - tried < timedelta(hours=float(_env("OFFSITE_RETRY_HOURS", "6"))):
        return False
    return to_local(now).hour >= int(_env("OFFSITE_HOUR", "6"))


def latest_backup(bucket):
    """El volcado .sql.gz más reciente (por fecha de actualización) bajo db/."""
    blobs = [b for b in bucket.list_blobs(prefix="db/") if b.name.endswith(".sql.gz")]
    return max(blobs, key=lambda b: b.updated, default=None)


def run(now: Optional[datetime] = None, bucket=None, graph: Optional[GraphClient] = None) -> str:
    """Paso del Job. `now` UTC ingenuo."""
    if not configured():
        return NOT_CONFIGURED
    now = now or utcnow()
    bucket = bucket or _bucket()
    state = load_state(bucket)
    first = "since" not in state
    state.setdefault("since", _iso(now))
    stale_days = float(_env("OFFSITE_ALERT_DAYS", "10"))
    if not due(now, state):
        ref = _parse(state.get("last_ok_at")) or _parse(state.get("since")) or now
        if now - ref > timedelta(days=stale_days):
            raise RuntimeError(f"Hace más de {int(stale_days)} días que no hay copia semanal en OneDrive (última buena: {state.get('last_ok_at') or 'ninguna'}). Último error: {state.get('last_error') or 'sin intentos'}")
        if first:
            save_state(state, bucket)
        return f"copia semanal al día (última: {state.get('last_ok_at') or 'ninguna'})"
    state["last_attempt_at"] = _iso(now)
    try:
        info = _copy_once(now, bucket, graph or GraphClient())
    except Exception as e:  # noqa: BLE001
        reason = f"{type(e).__name__}: {e}"[:300]
        state.update(last_status="fail", last_error=reason)
        _push_history(state, {"at": _iso(now), "ok": False, "error": reason})
        save_state(state, bucket)
        raise
    state.update(last_status="ok", last_ok_at=_iso(now), last_error="", last_name=info["name"], last_size=info["size"], last_deleted=info["deleted"])
    _push_history(state, {"at": _iso(now), "ok": True, "name": info["name"], "size": info["size"]})
    save_state(state, bucket)
    return f"copia subida: {info['name']} ({info['size']} bytes cifrados); se borraron {info['deleted']} copia(s) vieja(s)"


def _push_history(state: dict, row: dict) -> None:
    state["history"] = (state.get("history") or [])[-19:] + [row]


def _copy_once(now: datetime, bucket, graph: GraphClient) -> dict:
    blob = latest_backup(bucket)
    if blob is None:
        raise RuntimeError("No hay respaldos en el bucket (db/…/*.sql.gz) para copiar.")
    base = os.path.basename(blob.name)
    stem = base[: -len(".sql.gz")] if base.endswith(".sql.gz") else base
    name = (stem if stem.startswith(NAME_PREFIX) else NAME_PREFIX + stem) + NAME_SUFFIX
    if getattr(blob, "size", None) is None:
        blob.reload()
    total = encrypted_size(int(blob.size))
    key = _env("BACKUP_COPY_ENCRYPTION_KEY")
    sent = [0]

    def counted():
        with blob.open("rb") as src:
            for part in encrypt_stream(src, key):
                sent[0] += len(part)
                yield part

    graph.upload(name, counted(), total)
    if sent[0] != total:
        raise RuntimeError(f"El tamaño cifrado ({sent[0]}) no coincide con el calculado ({total}).")
    deleted = prune(graph, keep_n(), protect=name, now=now)
    return {"name": name, "size": total, "deleted": deleted}


_COPY_NAME = re.compile(r"golden_db_(\d{8})_(\d{4})\.gwbk")


def _copy_date(name: str) -> Optional[datetime]:
    m = _COPY_NAME.fullmatch(name or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
    except ValueError:
        return None


def prune(graph: GraphClient, keep: int, protect: str = "", now: Optional[datetime] = None) -> int:
    """Deja las `keep` copias más nuevas (el nombre lleva la fecha) y borra el resto. Solo toca `golden_db_AAAAmmdd_HHMM.gwbk` dentro de la carpeta configurada.
    F5-9 E: nunca borra la copia recién subida (`protect`) y no cuenta nombres con fecha FUTURA ni con otro formato: alguien con permiso de escritura en la carpeta
    podía dejar `golden_db_9999….gwbk` para que cada copia real se borrara justo después de subirse (la copia «salía bien» y no quedaba ninguna)."""
    limit = (now or utcnow()) + timedelta(days=2)
    ours = []
    for item_id, name in graph.list_copies():
        d = _copy_date(name)
        if d is None or d > limit:
            continue
        ours.append((d, name, item_id))
    ours.sort(reverse=True)
    n = 0
    for _, name, item_id in ours[keep:]:
        if name == protect:
            continue
        graph.delete(item_id)
        n += 1
    return n


# ------------------------------------------------------------------ /sistema
def status_item(bucket=None, now: Optional[datetime] = None) -> dict:
    from app.ops import item
    state = load_state(bucket) if (bucket is not None or os.getenv("BACKUP_BUCKET")) else {}
    title = "Copia semanal fuera de Google"
    if not state and not configured():
        return item("offsite_copy", title, "yellow", NOT_CONFIGURED, "Las copias solo están dentro del proyecto de Google.", "Sigue docs/24_COPIA_SEMANAL_ONEDRIVE.md para activarla.")
    now = now or utcnow()
    ok = _parse(state.get("last_ok_at"))
    if ok is None:
        lvl = "yellow" if not state.get("last_error") else "red"
        return item("offsite_copy", title, lvl, "sin copia todavía", state.get("last_error") or "Aún no se ha hecho la primera copia.", "Espera a la próxima corrida o revisa docs/24.")
    age = (now - ok).total_seconds() / 86400
    alert = float(_env("OFFSITE_ALERT_DAYS", "10"))
    lvl = "green" if age <= 8 else "yellow" if age <= alert else "red"
    size_mb = round((state.get("last_size") or 0) / 1048576, 1)
    return item("offsite_copy", title, lvl, f"hace {age:.0f} días · {size_mb} MB", "" if lvl == "green" else (state.get("last_error") or "La última copia es más vieja de lo esperado."),
                "" if lvl == "green" else "Revisa el paso offsite-copy del Job golden-ops y docs/24.", age_days=round(age, 1), last_ok_at=state.get("last_ok_at"), last_status=state.get("last_status"))


__all__ = ["run", "due", "configured", "encrypt_stream", "decrypt_stream", "encrypted_size", "GraphClient", "status_item"]
