"""Datos de la empresa para los textos legales NUEVOS (autorización biométrica, política v1.1): COMPANY_NAME, COMPANY_NIT, PRIVACY_EMAIL, DOMAIN (variables de entorno, nada quemado).
Mientras no estén definidas se usa un marcador visible «[COMPANY_NAME]». En producción un texto legal con un marcador sin resolver NO se publica (ver `blocked`)."""
import os
import re

NAMES = ("COMPANY_NAME", "COMPANY_NIT", "PRIVACY_EMAIL", "DOMAIN")
_MARK = re.compile(r"\[(?:%s)\]" % "|".join(NAMES))


def nit_display(raw: str) -> str:
    """901542833-2 → 901.542.833-2 (así se muestra en pantalla y en los textos legales). Si no tiene la forma de un NIT con dígito de verificación, se devuelve tal cual."""
    m = re.fullmatch(r"(\d{3})\.?(\d{3})\.?(\d{3})-?(\d)", (raw or "").strip())
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}-{m.group(4)}" if m else (raw or "").strip()


def get(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        return f"[{name}]"
    return nit_display(value) if name == "COMPANY_NIT" else value


def policy_url() -> str:
    """Dirección pública de la política: el host de la APP (PUBLIC_BASE_URL, p. ej. https://app.golden-eventos.com) y, si no está, https://app.<DOMAIN>."""
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        domain = get("DOMAIN")
        base = f"https://app.{domain}" if not domain.startswith("[") else f"https://{domain}"
    return f"{base}/privacidad"


def unresolved(text: str) -> list:
    """Marcadores sin resolver que aún tiene un texto, p. ej. ['[COMPANY_NIT]']."""
    return sorted(set(_MARK.findall(text or "")))


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "production"


def blocked(text: str) -> list:
    """En producción, los marcadores sin resolver que impiden publicar el texto (vacío = se puede publicar; fuera de producción nunca bloquea)."""
    return unresolved(text) if is_production() else []
