"""Seguridad de cuentas (Sprint 4): límite de intentos, política de contraseña y tokens de restablecimiento.

Todo el estado vive en Postgres (`rate_limit_events`, `password_reset_tokens`), no en memoria, para que valga con
varios procesos/workers y sobreviva a un reinicio."""
import functools
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

LOGIN_MAX_FAILS = 5          # intentos fallidos por PAR (usuario, IP) dentro de la ventana
LOGIN_MAX_FAILS_PER_IP = 20  # tope por IP (cubre a quien prueba muchos usuarios distintos)
LOGIN_MAX_FAILS_PER_USER = 40  # tope global por usuario desde cualquier IP (fuerza bruta distribuida); muy alto para que un tercero no pueda dejar fuera al dueño
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
    _google_infra_lookup.cache_clear()


@functools.lru_cache(maxsize=8192)
def _google_infra_lookup(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == n.version and addr in n for n in _infra_cache[0])


def is_google_infra(ip: str) -> bool:
    """¿Es una IP de infraestructura de Google (no de clientes de Google Cloud)? Falso si no es una IP válida. El resultado se guarda por IP (recorrer ~400 redes costaba ~0,6 ms por
    petición de envío; los reintentos de una misma persona repiten la IP): la caché se vacía al releer la lista (`reload_infra`)."""
    if _infra_cache is None:
        infra_info()
    return _google_infra_lookup(ip)


def client_ip(request: Request) -> str:
    """IP real del visitante. En la VM (Cloudflare con proxy + Nginx) `CF-Connecting-IP` es confiable porque Cloudflare la reescribe. En
    Cloud Run (Cloudflare solo DNS) cualquiera podría mandarla inventada: allá TRUST_CF_CONNECTING_IP=0 y se usa `X-Forwarded-For`:
      * XFF_STRIP_GOOGLE=1 (Cloud Run): se QUITAN del FINAL de la cadena las IPs de infraestructura de Google (los proxies de Firebase Hosting y del frontend de
        Cloud Run, 66.102.x, 74.125.x…) y se toma la última que queda. Por run.app directo la cadena es `[lo que escriba el cliente…, IP real]` (la última la
        agrega Google, no se puede falsificar); por Firebase Hosting es `[IP real, IP de Google]`. En ambos casos sale la IP real. Si TODAS son de Google
        (llamadas internas, o un visitante con IP de Google) devuelve la última, y `limit_ip` la descarta (ver abajo).
      * si no, `XFF_CLIENT_INDEX` (0 = la primera, comportamiento de la VM; -1 = la última…)."""
    if os.getenv("TRUST_CF_CONNECTING_IP", "0") == "1" and request.headers.get("cf-connecting-ip"):
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
    ip = bucket_ip(ip)
    fp = hashlib.sha1((request.headers.get("user-agent", "") + "|" + request.headers.get("accept-language", "")).encode(), usedforsecurity=False).hexdigest()[:10]
    with _lock:
        _events.append((now, ip, fp))
    return ip


def bucket_ip(ip: str) -> str:
    """S3: una conexión IPv6 trae un /64 entero (2^64 direcciones): contar por dirección exacta dejaba saltar los límites rotando direcciones. Las IPv6 se agrupan por su /64
    («2001:db8:1:2::/64»); una IPv4 (o IPv4 dentro de IPv6, «::ffff:1.2.3.4») queda tal cual. Un texto que no es IP se devuelve igual."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
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


def _window_unlock(db: Session, kind: str, conds: list, limit: int, window: timedelta) -> Optional[timedelta]:
    """Cuánto falta para que se libere el cubo definido por `conds` (None = no está lleno)."""
    times = [r.created_at for r in db.query(RateLimitEvent.created_at).filter(
        RateLimitEvent.kind == kind, RateLimitEvent.created_at > utcnow() - window, *conds,
    ).order_by(RateLimitEvent.created_at.desc()).limit(limit)]
    if len(times) < limit:
        return None
    return (times[-1] + window) - utcnow()


def login_minutes_locked(db: Session, username: str, ip: Optional[str]) -> int:
    """Minutos de bloqueo del login (0 = libre). 0C (C7): el bloqueo es por PAR (usuario, IP), así un atacante externo no deja fuera al dueño de la cuenta (p. ej. el
    super_admin) desde otra IP. Tres cubos: el par (LOGIN_MAX_FAILS; si la IP es None —IP de Google, no confiable— el par es solo el usuario), la IP (LOGIN_MAX_FAILS_PER_IP: quien
    prueba muchos usuarios) y un tope global por usuario MUCHO más alto (LOGIN_MAX_FAILS_PER_USER) contra la fuerza bruta repartida en muchas IPs."""
    key = (username or "").lower()
    locks = []
    pair = [RateLimitEvent.key == key] + ([RateLimitEvent.ip == ip] if ip else [])
    # S3: el tope global por usuario NO frena a una IP desde la que esa cuenta ya entró bien en las últimas 24 h: así un tercero que manda 40 fallos no deja fuera al dueño
    # (sigue el tope por par usuario+IP, que es lo que frena a quien prueba desde esa misma IP).
    global_user = None if known_ip(db, key, ip) else [RateLimitEvent.key == key]
    for conds, limit in ((pair, LOGIN_MAX_FAILS), (global_user, LOGIN_MAX_FAILS_PER_USER), ([RateLimitEvent.ip == ip] if ip else None, LOGIN_MAX_FAILS_PER_IP)):
        if conds is None:
            continue
        left = _window_unlock(db, "login_fail", conds, limit, LOGIN_WINDOW)
        if left is not None:
            locks.append(left)
    if not locks:
        return 0
    return max(1, math.ceil(max(locks).total_seconds() / 60))


KNOWN_IP_WINDOW = timedelta(hours=24)       # las filas de rate_limit_events se borran pasado un día (record_event)


def known_ip(db: Session, username: str, ip: Optional[str]) -> bool:
    """¿La cuenta entró bien desde esta IP (o su /64) en las últimas 24 h? Lo anota `record_login_ok` al ingresar."""
    if not ip or not username:
        return False
    return db.query(RateLimitEvent.id).filter(RateLimitEvent.kind == "login_ok", RateLimitEvent.key == username.lower(), RateLimitEvent.ip == ip,
                                              RateLimitEvent.created_at > utcnow() - KNOWN_IP_WINDOW).first() is not None


def record_login_ok(db: Session, username: str, ip: Optional[str]) -> None:
    if ip:
        record_event(db, "login_ok", username, ip)


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


MIN_PASSWORD_LENGTH_CREATED = 10   # 0C (C11): contraseñas que fija un administrador (alta de personal, restablecimiento): más largas y con letra y número
COMMON_PASSWORDS = frozenset({
    "password", "passw0rd", "contrasena", "contrasenia", "clave", "claves", "admin", "administrador", "administrator", "root", "qwerty", "qwertyuiop", "asdfgh", "abc", "abcdef", "letmein",
    "welcome", "bienvenido", "bienvenida", "golden", "goldenweb", "goldeneventos", "goldenlogistica", "goldenlogisticas", "colombia", "bogota", "medellin", "usuario", "digitador", "coordinador",
    "comercial", "cliente", "evento", "eventos", "cambiame", "cambiar", "iloveyou", "monkey", "dragon", "123456", "12345678", "123456789", "1234567890", "0123456789",
})


def _is_common(low: str) -> bool:
    letters = "".join(c for c in low if c.isalpha())
    return low in COMMON_PASSWORDS or (letters in COMMON_PASSWORDS and len(letters) >= 4) or (low.strip("0123456789") == "" and len(set(low)) <= 2)


MAX_PASSWORD_BYTES = 72      # bcrypt 5 lanza ValueError con más de 72 bytes: se rechaza con un 4xx en vez de dar 500 (R3-08)


def password_rules(password: str, username: Optional[str] = None, strict: bool = False) -> list:
    """Política de contraseñas como lista de requisitos [{id, label, problem, ok}] (la ÚNICA fuente: `password_problem` y el endpoint
    /api/password-policy salen de acá; static/js/password-policy.js evalúa lo mismo en vivo). Siempre: mínimo MIN_PASSWORD_LENGTH, distinta del usuario y fuera de una lista
    corta de contraseñas comunes (con o sin cifras/símbolos alrededor). `strict=True` (0C-C11: la fija un administrador al crear o restablecer una cuenta): mínimo
    MIN_PASSWORD_LENGTH_CREATED y al menos una letra y un número."""
    password = password or ""
    minimum = MIN_PASSWORD_LENGTH_CREATED if strict else MIN_PASSWORD_LENGTH
    low = password.strip().lower()
    rules = [{"id": "length", "label": f"Tiene al menos {minimum} caracteres", "problem": f"La contraseña debe tener al menos {minimum} caracteres", "ok": len(password) >= minimum}]
    if strict:
        rules.append({"id": "letter_digit", "label": "Tiene al menos una letra y un número", "problem": "La contraseña debe tener al menos una letra y un número",
                      "ok": any(c.isalpha() for c in password) and any(c.isdigit() for c in password)})
    rules.append({"id": "not_username", "label": "No es igual a tu usuario", "problem": "La contraseña no puede ser igual al usuario",
                  "ok": not (username and low == username.strip().lower())})
    rules.append({"id": "not_common", "label": "No es una contraseña muy común (como «123456» o «Colombia2026»)",
                  "problem": "Esa contraseña es demasiado común: elige otra más difícil de adivinar", "ok": not _is_common(low)})
    return rules


def must_change_on_set_by_other(role: str) -> bool:
    """Fase 4 (8-nov-2026): la cuenta cuya contraseña inicial (la cédula o una temporal) la puso OTRA persona debe elegir la suya en el primer ingreso. Única excepción: el
    digitador temporal, que entra solo con su cédula y nunca usa ni cambia contraseña. Sin interruptor: no es opcional."""
    return role != "digitador"


def password_problem(password: str, username: Optional[str] = None, strict: bool = False) -> Optional[str]:
    """Primer requisito que NO se cumple (mensaje en español para la persona), o None si la contraseña sirve. Ver `password_rules`."""
    for r in password_rules(password, username, strict):
        if not r["ok"]:
            return r["problem"]
    if len((password or "").encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"La contraseña es demasiado larga (máximo {MAX_PASSWORD_BYTES} bytes, unos {MAX_PASSWORD_BYTES // 2}-{MAX_PASSWORD_BYTES} caracteres)"
    return None


def password_policy(strict: bool = False) -> dict:
    """Lo que el navegador necesita para evaluar los requisitos en vivo sin duplicar números ni listas (se sirve en /api/password-policy)."""
    base = password_rules("", None, strict)
    return {
        "strict": strict, "min_length": MIN_PASSWORD_LENGTH_CREATED if strict else MIN_PASSWORD_LENGTH,
        "rules": [{"id": r["id"], "label": r["label"], "problem": r["problem"]} for r in base],
        "common": sorted(COMMON_PASSWORDS),
    }


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
