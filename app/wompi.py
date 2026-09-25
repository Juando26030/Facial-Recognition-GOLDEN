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
import time
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


STATUS_URL = "https://wompi.statuspage.io/api/v2/status.json"
_status = {"at": 0.0, "data": None}


def service_status() -> dict:
    """Estado público del servicio de Wompi (su página de estado): {"indicator": none|minor|major|critical|unknown, "description"}.
    Caché de 60 s; si la página de estado no responde queda «unknown» (nunca se avisa de un problema que no consta)."""
    now = time.time()
    if _status["data"] is not None and now - _status["at"] < 60:
        return _status["data"]
    data = {"indicator": "unknown", "description": ""}
    try:
        with urllib.request.urlopen(urllib.request.Request(STATUS_URL, headers={"Accept": "application/json"}), timeout=4) as res:
            st = (json.loads(res.read().decode()) or {}).get("status") or {}
            if st.get("indicator") in ("none", "minor", "major", "critical"):
                data = {"indicator": st["indicator"], "description": str(st.get("description") or "")[:120]}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        pass
    _status.update(at=now, data=data)
    return data


def service_problem() -> Optional[dict]:
    """El estado de Wompi solo si reporta un problema (minor/major/critical); None si opera normal o no se sabe."""
    st = service_status()
    return st if st["indicator"] in ("minor", "major", "critical") else None


def estimate_fee(amount_cents: int, method: str = "") -> int:
    """Comisión ESTIMADA de Wompi sobre un pago aprobado, en centavos. Plan Avanzado (wompi.com/es/co/planes-tarifas, 2026-09):
    2,65 % + $700 + IVA por transacción exitosa (tarjeta, PSE, Nequi…); Código QR: 1 %. Se asume IVA (19 %) sobre la comisión y que la
    comisión NO se devuelve al reembolsar. Es una estimación para reportes: la cifra exacta está en Wompi → Reportes. Se ajusta con
    WOMPI_FEE_PERCENT, WOMPI_FEE_FIXED_COP, WOMPI_FEE_QR_PERCENT y WOMPI_FEE_IVA_PERCENT si el plan cambia."""
    def env(name, default):
        try:
            return float(os.getenv(name, "").replace(",", ".") or default)
        except ValueError:
            return default

    qr = "QR" in (method or "").upper()
    pct = env("WOMPI_FEE_QR_PERCENT", 1.0) if qr else env("WOMPI_FEE_PERCENT", 2.65)
    fixed = 0.0 if qr else env("WOMPI_FEE_FIXED_COP", 700.0) * 100
    base = amount_cents * pct / 100 + fixed
    return int(round(base * (1 + env("WOMPI_FEE_IVA_PERCENT", 19.0) / 100)))


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


def _soft_error(body) -> Optional[str]:
    """Wompi a veces responde HTTP 200 con el error DENTRO (`{"data": {"type": "unprocessable", "reason": "…"}}`): no es un éxito."""
    d = body.get("data") if isinstance(body, dict) else None
    if isinstance(d, dict) and (d.get("type") in ("unprocessable", "error", "invalid") or (d.get("reason") and not d.get("id") and not d.get("transaction"))):
        return str(d.get("reason") or d.get("type"))
    return None


def _post(cfg: dict, path: str, body: dict) -> tuple:
    """POST autenticado con la llave privada. (ok, respuesta) o (False, mensaje legible)."""
    if not cfg.get("private_key"):
        return False, "Falta la llave privada de Wompi (WOMPI_PRIVATE_KEY) en el servidor"
    req = urllib.request.Request(f"{cfg['api']}{path}", data=json.dumps(body).encode(), method="POST", headers=_headers(cfg, json_body=True))
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            body_ok = json.loads(res.read().decode() or "{}")
            soft = _soft_error(body_ok)
            return (False, f"Wompi no lo procesó: {soft}") if soft else (True, body_ok)
    except urllib.error.HTTPError as e:
        try:
            body_err = json.loads(e.read().decode())
            err = body_err.get("error") or {}
            detail = "; ".join(f"{k}: {v}" for k, v in (err.get("messages") or {}).items()) if isinstance(err.get("messages"), dict) else (err.get("reason") or str(err.get("messages") or body_err))
        except (ValueError, OSError):
            detail = e.reason
        return False, f"Wompi respondió {e.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"No se pudo contactar a Wompi: {e}"


def void_transaction(cfg: dict, transaction_id: str, amount_cents: Optional[int] = None) -> tuple:
    """Anula una transacción de TARJETA (`POST /transactions/<id>/void`, llave privada): devuelve el dinero a la tarjeta. Sin
    `amount_cents` anula el valor completo. OJO: la especificación acepta `amount_in_cents`, pero el sandbox respondió (2026-09-24)
    «Sólo las transacciones con el mismo monto original pueden ser potencialmente anuladas»: la anulación parcial NO existe.
    Devuelve (ok, detalle): la respuesta de Wompi si salió bien, o un mensaje legible si no."""
    if not _safe_id(transaction_id):
        return False, "Identificador de transacción inválido"
    return _post(cfg, f"/transactions/{transaction_id}/void", {"amount_in_cents": int(amount_cents)} if amount_cents else {})


def refunds_v2_enabled(cfg: dict) -> bool:
    """La API de reembolsos V2 (`POST /refunds`, cualquier medio, con parciales) es hoy SOLO de sandbox según la documentación de
    Wompi. Se usa siempre en sandbox; en producción solo si se activa con WOMPI_REFUNDS_V2=1 (cuando Wompi la habilite)."""
    return bool(cfg.get("test")) or os.getenv("WOMPI_REFUNDS_V2", "").strip() == "1"


def get_refund_v2(cfg: dict, refund_id) -> Optional[dict]:
    """Consulta un reembolso V2 (`GET /refunds/<id>`, llave privada). None si no se pudo."""
    if not str(refund_id).isdigit():
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{cfg['api']}/refunds/{refund_id}", headers=_headers(cfg)), timeout=8) as res:
            return (json.loads(res.read().decode()) or {}).get("data")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None


def create_refund_v2(cfg: dict, transaction_id: str, amount_cents: int, reason: str = "", reference: str = "") -> tuple:
    """Reembolso V2 (`POST /refunds`, llave privada): parcial o total, para transacciones de cualquier medio."""
    if not _safe_id(transaction_id):
        return False, "Identificador de transacción inválido"
    body = {"transaction_id": transaction_id, "amount_in_cents": int(amount_cents)}
    if reason:
        body["reason"] = reason[:200]
    if reference:
        body["reference"] = reference[:60]
    return _post(cfg, "/refunds", body)
