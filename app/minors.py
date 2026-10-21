"""Menores de edad (L3, Res. SIC 52185/2025 y dictamen de la auditora): quien tiene menos de 18 años NO pasa por captura biométrica (sin cámara, sin pantalla de autorización, sin vector,
`users.is_biometric_enabled = False`) y solo ingresa por cédula/QR. La edad sale de la fecha de nacimiento que da la persona (la cédula no dice la edad)."""
import re
from datetime import date, datetime, timedelta
from typing import Optional

ADULT_AGE = 18


def parse_birth(raw) -> Optional[date]:
    """Fecha de nacimiento desde lo que traiga la celda o el campo: AAAA-MM-DD (también AAAA/MM/DD, con o sin hora «00:00:00»), DD/MM/AAAA (también con - o .; día y mes de 1 o 2 dígitos; en
    Colombia el día va primero), una fecha de Excel (número de serie, p. ej. 40612 = 2011-03-10) o un date/datetime. None si falta, no es válida, es futura o es anterior a 1900."""
    if isinstance(raw, datetime):
        d = raw.date()
    elif isinstance(raw, date):
        d = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?", text)
        n = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
        serial = re.fullmatch(r"(\d{4,6})(?:\.0+)?", text)
        try:
            if m:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif n:
                d = date(int(n.group(3)), int(n.group(2)), int(n.group(1)))
            elif serial and 1000 <= int(serial.group(1)) <= 80000:          # fecha de Excel: días desde 1899-12-30 (cubre el error del año bisiesto 1900 para fechas posteriores a marzo de 1900)
                d = date(1899, 12, 30) + timedelta(days=int(serial.group(1)))
            else:
                return None
        except (ValueError, OverflowError):
            return None
    return d if d <= date.today() and d.year >= 1900 else None


def age_years(birth: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def is_minor(birth: Optional[date], today: Optional[date] = None) -> bool:
    """True solo si hay fecha y da menos de 18. Sin fecha NO se sabe (devuelve False): la declaración de mayoría de edad de la pantalla cubre ese caso."""
    return birth is not None and age_years(birth, today) < ADULT_AGE
