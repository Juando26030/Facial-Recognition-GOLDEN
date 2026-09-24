"""Wompi (Sprint 5, campo «Pago» de Formularios Web): llaves, firma de integridad del widget, verificación de los
eventos (webhook) y consulta de una transacción. Sin base de datos ni HTTP entrante — se prueba a fondo.

Llaves (SOLO por variables de entorno, nunca en el código ni en la base; hay dos juegos, porque Wompi da uno de
pruebas y otro de producción, y un formulario en estado `pruebas` usa el de pruebas):
  WOMPI_PUBLIC_KEY, WOMPI_INTEGRITY_SECRET, WOMPI_EVENTS_SECRET, WOMPI_PRIVATE_KEY                  -> producción
  WOMPI_SANDBOX_PUBLIC_KEY, WOMPI_SANDBOX_INTEGRITY_SECRET, WOMPI_SANDBOX_EVENTS_SECRET, WOMPI_SANDBOX_PRIVATE_KEY -> pruebas
La llave PRIVADA (prv_…) solo se usa desde el servidor: consultar una transacción y anularla. Nunca sale al navegador.
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
    return {"public_key": public, "integrity_secret": integrity, "events_secret": os.getenv(prefix + "EVENTS_SECRET", "").strip(),
            "private_key": os.getenv(prefix + "PRIVATE_KEY", "").strip(), "api": API[test], "test": test}


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


def _headers(cfg: dict, json_body: bool = False) -> dict:
    h = {"Accept": "application/json"}
    if cfg.get("private_key"):
        h["Authorization"] = f"Bearer {cfg['private_key']}"      # la consulta de transacciones exige la llave privada
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _safe_id(transaction_id: str) -> bool:
    return bool(transaction_id) and all(c.isalnum() or c in "-_" for c in transaction_id)


def fetch_transaction(cfg: dict, transaction_id: str) -> Optional[dict]:
    """Consulta una transacción (`GET /transactions/<id>`, con la llave privada): sirve de respaldo cuando el webhook tarda
    o no puede llegar (p. ej. en local). None si no se pudo consultar."""
    if not _safe_id(transaction_id):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{cfg['api']}/transactions/{transaction_id}", headers=_headers(cfg)), timeout=8) as res:
            return (json.loads(res.read().decode()) or {}).get("data")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None


def void_transaction(cfg: dict, transaction_id: str) -> tuple:
    """Anula una transacción de TARJETA (`POST /transactions/<id>/void`, llave privada): devuelve el dinero a la tarjeta por el
    valor completo. Devuelve (ok, detalle): `detalle` es la respuesta de Wompi si salió bien, o un mensaje legible si no."""
    if not cfg.get("private_key"):
        return False, "Falta la llave privada de Wompi (WOMPI_PRIVATE_KEY) en el servidor"
    if not _safe_id(transaction_id):
        return False, "Identificador de transacción inválido"
    req = urllib.request.Request(f"{cfg['api']}/transactions/{transaction_id}/void", data=b"{}", method="POST", headers=_headers(cfg, json_body=True))
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return True, json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            err = body.get("error") or {}
            detail = "; ".join(f"{k}: {v}" for k, v in (err.get("messages") or {}).items()) if isinstance(err.get("messages"), dict) else (err.get("reason") or str(err.get("messages") or body))
        except (ValueError, OSError):
            detail = e.reason
        return False, f"Wompi respondió {e.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"No se pudo contactar a Wompi: {e}"
