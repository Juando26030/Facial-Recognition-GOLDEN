"""Llaves de producto del servidor local (20-nov-2026): lógica PURA (sin base de datos ni FastAPI, para poder probarla sola).

Una llave (`GLD-XXXX-XXXX-XXXX`) la crea un administrador y sirve para instalar UN servidor local: se «reclama» con el instalador (queda atada a esa instalación), se «activa» al vincular el
servidor la primera vez y desde entonces ES el identificador (serial) del servidor. Es de un solo uso: una vez reclamada ya no sirve para otra instalación. Deshabilitarla apaga el servidor
asociado (en cuanto vuelve a tener internet). Una llave sin usar vence a los 7 días.

Estados (`status`): unused (sin usar) · claimed (el instalador la reclamó; falta activar) · active (servidor activo) · expired (venció sin usarse) · disabled (deshabilitada: ya no sirve nunca más).
"""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from typing import Optional

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"          # sin I, O, 0 ni 1: no se confunden al dictarla o copiarla
PREFIX = "GLD"
VALID_DAYS = 7                                         # una llave sin usar vence a los 7 días
CLAIM_HOURS = 48                                       # reclamada por el instalador, tiene este tiempo para activarse (instalar + primer ingreso)
TICKET_SECONDS = 2 * 3600                              # el permiso de descarga del paquete que recibe el instalador
KEY_RE = re.compile(r"^GLD-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
INSTALL_ID_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")

STATUS_LABEL = {"unused": "Sin usar", "claimed": "Instalando", "active": "Activa", "expired": "Vencida", "disabled": "Deshabilitada"}


def generate() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{PREFIX}-{body[:4]}-{body[4:8]}-{body[8:]}"


def normalize(raw) -> Optional[str]:
    """Lo que el usuario escriba (minúsculas, sin guiones, con espacios) → `GLD-XXXX-XXXX-XXXX`; None si no tiene la forma de una llave."""
    flat = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    if len(flat) != 15 or not flat.startswith(PREFIX):
        return None
    code = f"{PREFIX}-{flat[3:7]}-{flat[7:11]}-{flat[11:15]}"
    return code if KEY_RE.match(code) else None


def clean_install_id(raw) -> Optional[str]:
    v = str(raw or "").strip()
    return v if INSTALL_ID_RE.match(v) else None


def expires_at(created_at):
    return created_at + timedelta(days=VALID_DAYS)


def status(key, now) -> str:
    """Estado de una llave (objeto con disabled_at, activated_at, claimed_at, expires_at)."""
    if key.disabled_at is not None:
        return "disabled"
    if key.activated_at is not None:
        return "active"
    if key.claimed_at is not None:
        return "expired" if now > key.claimed_at + timedelta(hours=CLAIM_HOURS) else "claimed"
    return "expired" if now > key.expires_at else "unused"


MSG = {
    "format": "La llave no tiene el formato correcto. Se ve así: GLD-XXXX-XXXX-XXXX.",
    "unknown": "Esa llave no existe. Revisa que esté bien escrita.",
    "disabled": "Esa llave fue deshabilitada: ya no se puede usar. Pide otra a un administrador.",
    "active": "Esa llave ya se usó en otro servidor: es de un solo uso. Pide otra a un administrador.",
    "expired": "Esa llave venció. Pide otra a un administrador.",
    "other_install": "Esa llave ya se usó en otra instalación: es de un solo uso. Pide otra a un administrador.",
    "not_claimed": "Esa llave no se activó con el instalador. Instala el servidor con el instalador y su llave.",
    "bad_install": "La instalación no se identificó bien. Vuelve a abrir el instalador.",
}


def check_claim(key, installation_id: str, now) -> tuple:
    """(ok, código, mensaje) para RECLAMAR la llave con el instalador. Repetir con la MISMA instalación vale (reintentos si se cortó la descarga); otra instalación, no."""
    st = status(key, now)
    if st in ("disabled", "expired"):
        return False, st, MSG[st]
    if st == "active":
        return False, "active", MSG["active"]
    if st == "claimed" and key.installation_id != installation_id:
        return False, "other_install", MSG["other_install"]
    return True, "ok", ""


def check_activate(key, installation_id: str, now) -> tuple:
    """(ok, código, mensaje) para ACTIVAR (vincular el servidor): solo una llave reclamada por ESA instalación y todavía vigente."""
    st = status(key, now)
    if st in ("disabled", "expired", "active"):
        return False, st, MSG[st]
    if st == "unused":
        return False, "not_claimed", MSG["not_claimed"]
    if key.installation_id != installation_id:
        return False, "other_install", MSG["other_install"]
    return True, "ok", ""


# ------------------------------------------------------------------------------------------------ permiso de descarga del paquete (sin estado: firmado con un secreto de la nube)
def _sig(secret: str, key_id: int, installation_id: str, exp: int) -> str:
    msg = f"gwk1|{key_id}|{installation_id}|{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:40]


def make_ticket(secret: str, key_id: int, installation_id: str, now_ts: int) -> str:
    exp = int(now_ts) + TICKET_SECONDS
    return f"{key_id}.{exp}.{_sig(secret, key_id, installation_id, exp)}"


def read_ticket(secret: str, ticket: str, installation_id: str, now_ts: int) -> Optional[int]:
    """El id de la llave si el permiso es auténtico, es de ESA instalación y no venció; None en cualquier otro caso."""
    try:
        kid, exp, sig = str(ticket or "").split(".")
        key_id, exp_i = int(kid), int(exp)
    except ValueError:
        return None
    if exp_i < int(now_ts) or not hmac.compare_digest(sig, _sig(secret, key_id, installation_id, exp_i)):
        return None
    return key_id
