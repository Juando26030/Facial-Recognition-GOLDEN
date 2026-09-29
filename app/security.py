"""Seguridad de cuentas (Sprint 4): límite de intentos, política de contraseña y tokens de restablecimiento.

Todo el estado vive en Postgres (`rate_limit_events`, `password_reset_tokens`), no en memoria, para que valga con
varios procesos/workers y sobreviva a un reinicio."""
import hashlib
import ipaddress
import math
import os
import secrets
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from app.timeutil import utcnow
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import PasswordResetToken, RateLimitEvent

LOGIN_MAX_FAILS = 5          # intentos fallidos por usuario dentro de la ventana
LOGIN_MAX_FAILS_PER_IP = 20  # tope por IP (cubre a quien prueba muchos usuarios distintos)
LOGIN_WINDOW = timedelta(minutes=15)
RESET_MAX_REQUESTS = 5       # solicitudes de "olvidé mi contraseña" por usuario / por IP en la ventana
RESET_WINDOW = timedelta(hours=1)
RESET_TOKEN_TTL = timedelta(minutes=60)
MIN_PASSWORD_LENGTH = 8


_CIDR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_infra_cidrs.txt")
_infra_cache: Optional[tuple] = None
_lock = threading.Lock()
_events: deque = deque(maxlen=5000)          # (t, ip, huella) de las peticiones con límite por IP: solo para detectar una lista de rangos vieja
_google_hits: deque = deque(maxlen=200)       # instantes en que la IP elegida resultó ser de Google


def _load_infra() -> tuple:
    """(redes, fecha de generación). XFF_STRIP_CIDRS (coma-separado; «auto» o vacío = el archivo) manda sobre el archivo `app/google_infra_cidrs.txt`
    que genera scripts/refresh_google_cidrs.py (goog.json − cloud.json)."""
    raw = os.getenv("XFF_STRIP_CIDRS", "").strip()
    generated = None
    if raw and raw.lower() != "auto":
        entries, source = [e.strip() for e in raw.split(",") if e.strip()], "variable"
    else:
        entries, source = [], "archivo"
        try:
            for line in open(_CIDR_FILE, encoding="utf8"):
                line = line.strip()
                if line.startswith("# generated:"):
                    generated = line.split(":", 1)[1].strip()
                elif line and not line.startswith("#"):
                    entries.append(line)
        except OSError:
            pass
    nets = []
    for e in entries:
        try:
            nets.append(ipaddress.ip_network(e, strict=False))
        except ValueError:
            continue
    return nets, generated, source


def infra_info() -> dict:
    global _infra_cache
    if _infra_cache is None:
        _infra_cache = _load_infra()
    return {"networks": len(_infra_cache[0]), "generated": _infra_cache[1], "source": _infra_cache[2]}


def reload_infra() -> None:
    """Vuelve a leer la lista (las pruebas cambian la variable)."""
    global _infra_cache
    _infra_cache = None


def is_google_infra(ip: str) -> bool:
    """¿Es una IP de infraestructura de Google (no de clientes de Google Cloud)? Falso si no es una IP válida."""
    if _infra_cache is None:
        infra_info()
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == n.version and addr in n for n in _infra_cache[0])


def client_ip(request: Request) -> str:
    """IP real del visitante. En la VM (Cloudflare con proxy + Nginx) `CF-Connecting-IP` es confiable porque Cloudflare la reescribe. En
    Cloud Run (Cloudflare solo DNS) cualquiera podría mandarla inventada: allá TRUST_CF_CONNECTING_IP=0 y se usa `X-Forwarded-For`:
      * XFF_STRIP_GOOGLE=1 (Cloud Run): se QUITAN del FINAL de la cadena las IPs de infraestructura de Google (los proxies de Firebase Hosting y del frontend de
        Cloud Run, 66.102.x, 74.125.x…) y se toma la última que queda. Por run.app directo la cadena es `[lo que escriba el cliente…, IP real]` (la última la
        agrega Google, no se puede falsificar); por Firebase Hosting es `[IP real, IP de Google]`. En ambos casos sale la IP real. Si TODAS son de Google
        (llamadas internas, o un visitante con IP de Google) devuelve la última, y `limit_ip` la descarta (ver abajo).
      * si no, `XFF_CLIENT_INDEX` (0 = la primera, comportamiento de la VM; -1 = la última…)."""
    if os.getenv("TRUST_CF_CONNECTING_IP", "1") == "1" and request.headers.get("cf-connecting-ip"):
        return request.headers["cf-connecting-ip"]
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if hops:
        if os.getenv("XFF_STRIP_GOOGLE", "0") == "1":
            i = len(hops)
            while i > 0 and is_google_infra(hops[i - 1]):
                i -= 1
            return hops[i - 1] if i > 0 else hops[-1]
        try:
            return hops[int(os.getenv("XFF_CLIENT_INDEX", "0"))]
        except IndexError:
            return hops[0]
    return request.client.host if request.client else "?"


def limit_ip(request: Request) -> Optional[str]:
    """La IP para los LÍMITES por IP, o None si no es confiable: una IP de infraestructura de Google (todas las entradas de la cadena eran de Google) juntaría a
    todos los visitantes en un solo cubo y bloquearía a todos a la vez. Con None los límites por IP se saltan (siguen los de por usuario/cédula) y queda
    contado para el aviso de «Estado del sistema». Además anota la petición para detectar una lista de rangos VIEJA (ver `ip_health`)."""
    ip = client_ip(request)
    now = time.time()
    if os.getenv("XFF_STRIP_GOOGLE", "0") == "1" and is_google_infra(ip):
        with _lock:
            _google_hits.append(now)
        return None
    fp = hashlib.sha1((request.headers.get("user-agent", "") + "|" + request.headers.get("accept-language", "")).encode()).hexdigest()[:10]
    with _lock:
        _events.append((now, ip, fp))
    return ip


def ip_health(now: Optional[float] = None) -> dict:
    """Señales de que los rangos de Google están viejos, para «Estado del sistema». `google_ip_hits`: veces en los últimos 10 min que TODA la cadena fue de Google.
    `top_share`/`distinct_clients`: en los últimos 5 min, la IP más frecuente concentra esa fracción de las peticiones con límite y tiene tantos navegadores distintos
    (huella de User-Agent + idioma; ojo: también pasa con el wifi de un evento). `concentrated` = ≥100 peticiones, ≥60 % en una IP y ≥20 navegadores distintos."""
    now = now or time.time()
    with _lock:
        hits = sum(1 for t in _google_hits if now - t <= 600)
        recent = [(ip, fp) for t, ip, fp in _events if now - t <= 300]
    top_ip, top_n, distinct = None, 0, 0
    if recent:
        counts = Counter(ip for ip, _ in recent)
        top_ip, top_n = counts.most_common(1)[0]
        distinct = len({fp for ip, fp in recent if ip == top_ip})
    share = top_n / len(recent) if recent else 0.0
    info = infra_info()
    age = None
    if info["generated"]:
        try:
            age = (utcnow().date() - datetime.strptime(info["generated"][:10], "%Y-%m-%d").date()).days
        except ValueError:
            pass
    return {"strip": os.getenv("XFF_STRIP_GOOGLE", "0") == "1", "list_age_days": age, "list_networks": info["networks"], "list_source": info["source"],
            "google_ip_hits": hits, "requests_5m": len(recent), "top_share": round(share, 2), "distinct_clients": distinct,
            "concentrated": len(recent) >= 100 and share >= 0.6 and distinct >= 20}


def record_event(db: Session, kind: str, key: str, ip: Optional[str]) -> None:
    db.add(RateLimitEvent(kind=kind, key=key.lower(), ip=ip))
    # Limpieza oportunista: nada de esto se necesita pasado un día.
    db.query(RateLimitEvent).filter(RateLimitEvent.created_at < utcnow() - timedelta(days=1)).delete()
    db.commit()


def clear_events(db: Session, kind: str, key: str) -> None:
    db.query(RateLimitEvent).filter(RateLimitEvent.kind == kind, RateLimitEvent.key == key.lower()).delete()
    db.commit()


def minutes_locked(db: Session, kind: str, key: Optional[str], ip: Optional[str], max_by_key: int, max_by_ip: int, window: timedelta) -> int:
    """Minutos que faltan para poder volver a intentar (0 = no está bloqueado). Bloquea si `key` acumuló
    `max_by_key` eventos dentro de la ventana, o si `ip` acumuló `max_by_ip`."""
    since = utcnow() - window
    locks = []
    for value, column, limit in ((key.lower() if key else None, RateLimitEvent.key, max_by_key), (ip, RateLimitEvent.ip, max_by_ip)):
        if not value:
            continue
        times = [r.created_at for r in db.query(RateLimitEvent.created_at).filter(
            RateLimitEvent.kind == kind, column == value, RateLimitEvent.created_at > since,
        ).order_by(RateLimitEvent.created_at.desc()).limit(limit)]
        if len(times) >= limit:
            # Se libera cuando el evento más viejo de los últimos `limit` sale de la ventana.
            locks.append((times[-1] + window) - utcnow())
    if not locks:
        return 0
    return max(1, math.ceil(max(locks).total_seconds() / 60))


def login_minutes_locked(db: Session, username: str, ip: str) -> int:
    return minutes_locked(db, "login_fail", username, ip, LOGIN_MAX_FAILS, LOGIN_MAX_FAILS_PER_IP, LOGIN_WINDOW)


def enforce_public_limit(db: Session, request: Request, kind: str, key: str, max_hits: int, window: timedelta) -> None:
    """Para endpoints públicos (ej. consulta de certificados): registra la consulta y responde 429 si esa IP
    ya hizo `max_hits` para esa clave dentro de la ventana."""
    ip = limit_ip(request)
    if ip is not None and _public_locked(db, kind, key, ip, max_hits, window):      # ip None = IP de Google: sin límite por IP (no se junta a todos en un cubo)
        raise HTTPException(status_code=429, detail="Demasiadas consultas seguidas — espera unos minutos e intenta de nuevo.")
    record_event(db, kind, key, ip)


def _public_locked(db: Session, kind: str, key: str, ip: str, max_hits: int, window: timedelta) -> bool:
    since = utcnow() - window
    hits = db.query(RateLimitEvent).filter(
        RateLimitEvent.kind == kind, RateLimitEvent.key == key.lower(), RateLimitEvent.ip == ip, RateLimitEvent.created_at > since,
    ).count()
    return hits >= max_hits


def password_problem(password: str) -> Optional[str]:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(db: Session, staff_id: int) -> str:
    """Crea un enlace nuevo e invalida los anteriores sin usar de esa cuenta. Devuelve el token en claro
    (solo se envía por correo; en la base queda el hash)."""
    now = utcnow()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.staff_user_id == staff_id, PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now})
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(staff_user_id=staff_id, token_hash=_hash_token(token), expires_at=now + RESET_TOKEN_TTL))
    db.commit()
    return token


def find_valid_reset_token(db: Session, token: str) -> Optional[PasswordResetToken]:
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == _hash_token(token)).first()
    if not row or row.used_at is not None or row.expires_at < utcnow():
        return None
    return row
