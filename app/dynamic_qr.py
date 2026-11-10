"""QR dinámico de la credencial digital (Fase 8, docs/21_QR_DINAMICO_WALLET.md).

Dos clases de código, ambas FIRMADAS con HMAC-SHA256 (llave derivada de SECRET_KEY; el mensaje incluye el `digital_token` de la persona, así que regenerar ese enlace invalida TODOS sus códigos):

  gwq1.<id>.<ventana>.<firma>   DINÁMICO. `ventana` = segundo UNIX // STEP_SECONDS. Vale mientras `ventana` esté entre (ahora - BACK_WINDOWS) y (ahora + SKEW_WINDOWS): ~60-90 s.
                                La página personal lo renueva sola; una captura de pantalla caduca.
  gwq1s.<id>.<firma>            ESTÁTICO de larga vida, solo para ENTRADA: es el que lleva el pase de Wallet (un pase no puede rotar cada 30 s sin la API de actualización).
                                Se revoca regenerando el enlace de la persona o archivando el evento.

`<id>` es el id de `event_attendees` (no la cédula). Nada de datos personales viaja en el código. Solo letras minúsculas, dígitos y puntos: sobrevive a un lector de código de barras que «teclea».
Este módulo es PURO (sin base de datos): el router busca a la persona y aquí se firma/verifica."""
import hashlib
import hmac
import os
import re
import time
from typing import Optional

from app import qr_vcard

STEP_SECONDS = 30
BACK_WINDOWS = 2          # un código sigue valiendo hasta 2 ventanas después (60-90 s en total, tiempo de leerlo)
SKEW_WINDOWS = 1          # y se tolera un reloj del celular adelantado hasta 1 ventana
BATCH = 4                 # la página pide 4 ventanas de una vez (2 min) y vuelve a pedir antes de que se acaben
SIG_HEX = 20

_PARSE = re.compile(r"^gwq1(s?)\.(\d{1,12})\.(?:(\d{1,12})\.)?([0-9a-f]{%d})$" % SIG_HEX)


def _key() -> bytes:
    secret = os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production"
    return hmac.new(secret.encode(), b"dynamic-qr-v1", hashlib.sha256).digest()


def _sig(kind: str, att_id: int, window: Optional[int], digital_token: str) -> str:
    msg = f"{kind}|{int(att_id)}|{'' if window is None else int(window)}|{digital_token}".encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:SIG_HEX]


def window_of(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def make_dynamic(att_id: int, digital_token: str, window: int) -> str:
    return f"gwq1.{int(att_id)}.{int(window)}.{_sig('d', att_id, window, digital_token)}"


def make_static(att_id: int, digital_token: str) -> str:
    return f"gwq1s.{int(att_id)}.{_sig('s', att_id, None, digital_token)}"


def batch(att_id: int, digital_token: str, now: Optional[float] = None) -> dict:
    """Lo que entrega `/b/<token>/qr`: los códigos de las próximas ventanas con su hora de inicio (ms), para que la página los muestre por su reloj sin volver a preguntar a cada rato."""
    cur = window_of(now)
    return {"step": STEP_SECONDS, "codes": [{"from_ms": (cur + i) * STEP_SECONDS * 1000, "code": make_dynamic(att_id, digital_token, cur + i)} for i in range(BATCH)]}


def looks_like(text) -> bool:
    return bool(_PARSE.match(qr_vcard.unwrap(text).strip().lower()))


def parse(text) -> Optional[dict]:
    """{'kind': 'd'|'s', 'att_id': int, 'window': int|None, 'sig': str} o None si no tiene la forma."""
    m = _PARSE.match(qr_vcard.unwrap(text).strip().lower())          # el QR viene como vCard con el código en NOTE (Fase 10, C) o como texto suelto (formato anterior)
    if not m:
        return None
    static, att_id, window, sig = m.group(1) == "s", int(m.group(2)), m.group(3), m.group(4)
    if static == (window is not None):          # el estático no lleva ventana y el dinámico siempre
        return None
    return {"kind": "s" if static else "d", "att_id": att_id, "window": None if static else int(window), "sig": sig}


def verify(parsed: Optional[dict], digital_token: str, now: Optional[float] = None) -> str:
    """'ok' | 'invalid' (firma o forma mala) | 'expired' (firma buena pero fuera de la ventana)."""
    if not parsed or not digital_token:
        return "invalid"
    expected = _sig(parsed["kind"], parsed["att_id"], parsed["window"], digital_token)
    if not hmac.compare_digest(expected, parsed["sig"]):
        return "invalid"
    if parsed["kind"] == "s":
        return "ok"
    cur = window_of(now)
    return "ok" if cur - BACK_WINDOWS <= parsed["window"] <= cur + SKEW_WINDOWS else "expired"
