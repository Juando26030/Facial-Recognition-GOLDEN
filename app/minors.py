"""Menores de edad (L3, Res. SIC 52185/2025 y dictamen de la auditora): quien tiene menos de 18 años NO pasa por captura biométrica (sin cámara, sin pantalla de autorización, sin vector,
`users.is_biometric_enabled = False`) y solo ingresa por cédula/QR. La edad sale de la fecha de nacimiento que da la persona (la cédula no dice la edad)."""
import re
from datetime import date
from typing import Optional

ADULT_AGE = 18


def parse_birth(raw) -> Optional[date]:
    """AAAA-MM-DD (también DD/MM/AAAA) → fecha; None si falta o no es válida o es futura."""
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text) or re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    a, b, c = (int(x) for x in m.groups())
    try:
        d = date(a, b, c) if len(m.group(1)) == 4 else date(c, b, a)
    except ValueError:
        return None
    return d if d <= date.today() and d.year >= 1900 else None


def age_years(birth: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def is_minor(birth: Optional[date], today: Optional[date] = None) -> bool:
    """True solo si hay fecha y da menos de 18. Sin fecha NO se sabe (devuelve False): la declaración de mayoría de edad de la pantalla cubre ese caso."""
    return birth is not None and age_years(birth, today) < ADULT_AGE
