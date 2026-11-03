"""SECRET_KEY única para firmar y hashear (Fase 0C: E9/N5). En producción NO hay valor por defecto: sin la variable se falla (también en Jobs y scripts)."""
import os

_DEV = "dev-only-insecure-key-do-not-use-in-production"


def secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise RuntimeError("SECRET_KEY no está definida (obligatoria en producción)")
    return _DEV
