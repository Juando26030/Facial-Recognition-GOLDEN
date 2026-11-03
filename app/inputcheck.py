"""Validación de texto de entrada (Fase 0C, pasada 2: familia XSS).

La defensa principal es escapar al pintar (cada `esc()` del panel escapa & < > " '), pero lo que se guarda
como nombre de usuario, nombre de persona, evento, lugar o rótulo no necesita llevar marcas HTML ni comillas
de control: se rechazan al guardar (defensa en profundidad). Solo se aplica a escrituras nuevas."""
import re

from pydantic import field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9._@\-]{3,64}$")
_BAD_TEXT = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]")


def check_text(value, what: str = "El texto"):
    """Devuelve el texto sin cambios o lanza ValueError si trae «<», «>» o caracteres de control."""
    if value is None:
        return value
    if _BAD_TEXT.search(str(value)):
        raise ValueError(f"{what} no puede incluir «<», «>» ni caracteres de control")
    return value


def check_username(value: str) -> str:
    v = (value or "").strip()
    if not USERNAME_RE.match(v):
        raise ValueError("El usuario solo admite letras, números y . _ @ - (3 a 64 caracteres)")
    return v


def text_validator(*fields: str):
    """Decorador de clase-modelo: `_v = text_validator('name', 'city')` dentro de un BaseModel."""
    def _f(cls, v, info):
        return check_text(v, f"«{info.field_name}»")
    return field_validator(*fields)(classmethod(_f))


def username_validator(*fields: str):
    return field_validator(*fields)(classmethod(lambda cls, v: check_username(v)))
