"""Configuración compartida de la prueba de carga contra STAGING (Cloud Run Jobs): la clave de la cuenta de carga no viaja por ningún lado, se DERIVA del `OPS_TOKEN`
del entorno (que el Job de siembra y los generadores leen de Secret Manager): así ni el repositorio, ni la salida de un comando, ni el chat la ven."""
import hashlib
import hmac
import os

TENANT = "carga-staging"
EVENT_CODE = "LOAD-STG"
USERNAME = "carga_dig"
FORM_SLUG = "carga"


def derived_password() -> str:
    token = os.environ.get("OPS_TOKEN", "")
    if not token:
        raise SystemExit("Falta OPS_TOKEN: la clave de la cuenta de carga se deriva de él (ver scripts/load_cfg.py).")
    return "Ld" + hmac.new(token.encode(), b"golden-load-account", hashlib.sha256).hexdigest()[:30] + "!9"
