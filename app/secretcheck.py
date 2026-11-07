"""S11: la clave que firma la cookie de sesión (SECRET_KEY). Con una clave conocida cualquiera fabrica una cookie de super_admin, así que fuera de desarrollo la app NO arranca
si falta, si es uno de los valores de ejemplo del repositorio o si tiene menos de MIN_LENGTH caracteres. Sin dependencias: se prueba sin levantar la app."""
from typing import Optional

MIN_LENGTH = 32
EXAMPLE_KEYS = frozenset({
    "cambia-esto-por-un-valor-aleatorio-largo",              # .env.example
    "dev-only-insecure-key-do-not-use-in-production",       # la de respaldo de app/main.py en desarrollo
    "ci-only-secret",                                        # .github/workflows/ci.yml
})


def problem(environment: Optional[str], key: Optional[str]) -> Optional[str]:
    """Mensaje si la clave no sirve para este entorno; None si sirve. En «development» (o sin ENVIRONMENT) no se exige nada."""
    if (environment or "development").strip().lower() == "development":
        return None
    key = (key or "").strip()
    if not key:
        return "SECRET_KEY no está definida. Es obligatoria fuera de desarrollo para firmar la sesión."
    if key in EXAMPLE_KEYS:
        return "SECRET_KEY tiene un valor de ejemplo del repositorio. Genera una clave aleatoria propia (p. ej. python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
    if len(key) < MIN_LENGTH:
        return f"SECRET_KEY es muy corta ({len(key)} caracteres). Usa una clave aleatoria de al menos {MIN_LENGTH}."
    return None
