"""Datos de la empresa para los textos legales NUEVOS (autorización biométrica, política v1.1): COMPANY_NAME, COMPANY_NIT, PRIVACY_EMAIL, DOMAIN (variables de entorno, nada quemado).
Mientras no estén definidas se usa un marcador visible «[COMPANY_NAME]». En producción un texto legal con un marcador sin resolver NO se publica (ver `blocked`)."""
import os
import re

NAMES = ("COMPANY_NAME", "COMPANY_NIT", "PRIVACY_EMAIL", "DOMAIN")
_MARK = re.compile(r"\[(?:%s)\]" % "|".join(NAMES))


def get(name: str) -> str:
    return (os.getenv(name) or "").strip() or f"[{name}]"


def policy_url() -> str:
    return f"https://{get('DOMAIN')}/privacidad"


def unresolved(text: str) -> list:
    """Marcadores sin resolver que aún tiene un texto, p. ej. ['[COMPANY_NIT]']."""
    return sorted(set(_MARK.findall(text or "")))


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "production"


def blocked(text: str) -> list:
    """En producción, los marcadores sin resolver que impiden publicar el texto (vacío = se puede publicar; fuera de producción nunca bloquea)."""
    return unresolved(text) if is_production() else []
