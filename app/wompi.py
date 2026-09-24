"""Wompi (Sprint 5, campo «Pago» de Formularios Web): llaves, firma de integridad del widget, verificación de los
eventos (webhook) y consulta de una transacción. Sin base de datos ni HTTP entrante — se prueba a fondo.

Llaves (SOLO por variables de entorno, nunca en el código ni en la base; hay dos juegos, porque Wompi da uno de
pruebas y otro de producción, y un formulario en estado `pruebas` usa el de pruebas):
  WOMPI_PUBLIC_KEY, WOMPI_INTEGRITY_SECRET, WOMPI_EVENTS_SECRET                  -> producción
  WOMPI_SANDBOX_PUBLIC_KEY, WOMPI_SANDBOX_INTEGRITY_SECRET, WOMPI_SANDBOX_EVENTS_SECRET -> pruebas (sandbox)
"""
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from typing import Optional

WIDGET_URL = "https://checkout.wompi.co/widget.js"
API = {False: "https://production.wompi.co/v1", True: "https://sandbox.wompi.co/v1"}
PENDING_STATUSES = ("PENDING",)
APPROVED, NEGATIVE = "APPROVED", ("DECLINED", "ERROR", "VOIDED")


def _build(prefix: str) -> Optional[dict]:
    public, integrity = os.getenv(prefix + "PUBLIC_KEY", "").strip(), os.getenv(prefix + "INTEGRITY_SECRET", "").strip()
    if not public or not integrity:
        return None
    test = public.startswith("pub_test_")      # el ambiente lo dice la propia llave (pub_test_… / pub_prod_…), no el nombre de la variable
    return {"public_key": public, "integrity_secret": integrity, "events_secret": os.getenv(prefix + "EVENTS_SECRET", "").strip(), "api": API[test], "test": test}


def config(test: bool) -> Optional[dict]:
    """Llaves para un formulario en `pruebas` (`test=True`) o en producción. None si falta la llave pública o el secreto
    de integridad. Regla de seguridad: un formulario en pruebas NUNCA usa llaves reales — si no hay juego SANDBOX, solo
    sirven las llaves principales cuando son de pruebas (`pub_test_`). Y `cfg["test"]` (deducido de la llave) manda sobre
    todo lo demás: con llaves de pruebas todo pago es de pruebas aunque el formulario esté «activo»."""
    cfg = _build("WOMPI_SANDBOX_" if test else "WOMPI_")
    if test and not cfg:
        main = _build("WOMPI_")
        cfg = main if main and main["test"] else None
    return cfg


def integrity_signature(reference: str, amount_cents: int, currency: str, secret: str) -> str:
    """SHA-256 de «referencia + monto en centavos + moneda + secreto de integridad» (lo exige el widget)."""
    return hashlib.sha256(f"{reference}{amount_cents}{currency}{secret}".encode()).hexdigest()


def _dig(data: dict, path: str):
    cur = data
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def event_checksum(event: dict, secret: str) -> str:
    """Checksum de un evento: SHA-256 de los valores de `signature.properties` (rutas dentro de `data`), luego el
    `timestamp` y el secreto de eventos, todo concatenado."""
    props = (event.get("signature") or {}).get("properties") or []
    joined = "".join("" if (v := _dig(event.get("data") or {}, p)) is None else str(v) for p in props)
    return hashlib.sha256(f"{joined}{event.get('timestamp', '')}{secret}".encode()).hexdigest()


def verify_event(event: dict, header_checksum: Optional[str] = None) -> Optional[bool]:
    """True si el checksum del evento coincide con el calculado con ALGUNO de los secretos de eventos configurados
    (producción o pruebas: Wompi manda cada ambiente a su propia URL, pero aquí llegan a la misma). None si no hay
    ningún secreto de eventos configurado (no se puede verificar → el llamador debe rechazar)."""
    secrets = [c["events_secret"] for c in (config(False), config(True)) if c and c["events_secret"]]
    if not secrets:
        return None
    given = str((event.get("signature") or {}).get("checksum") or header_checksum or "").lower()
    return bool(given) and any(hmac.compare_digest(event_checksum(event, s).lower(), given) for s in secrets)


def fetch_transaction(cfg: dict, transaction_id: str) -> Optional[dict]:
    """Consulta pública de una transacción (`GET /transactions/<id>`): sirve de respaldo cuando el webhook tarda o no
    puede llegar (p. ej. en local). None si no se pudo consultar."""
    if not transaction_id or not all(c.isalnum() or c in "-_" for c in transaction_id):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{cfg['api']}/transactions/{transaction_id}", headers={"Accept": "application/json"}), timeout=8) as res:
            return (json.loads(res.read().decode()) or {}).get("data")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None
