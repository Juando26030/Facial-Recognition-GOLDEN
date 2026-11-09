"""¿Este servidor es un servidor LOCAL sin internet (Fase 6)? Se decide solo por la variable de entorno LOCAL_SERVER=1 (nunca por la base ni por la petición)."""
import os

from fastapi import HTTPException

PASSWORD_ONLY_CLOUD = "La contraseña solo se cambia en la nube"
ACCOUNTS_ONLY_CLOUD = "Las cuentas se crean en la nube: aquí llegan solas al conectarse"


def is_local_server() -> bool:
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def assert_passwords_allowed() -> None:
    """En un servidor local NINGÚN camino cambia una contraseña (la nube manda y la copia hacia acá): 403 con el mensaje de siempre."""
    if is_local_server():
        raise HTTPException(status_code=403, detail=PASSWORD_ONLY_CLOUD)
