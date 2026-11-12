"""CRM de GoldenWeb (módulo dentro de este servicio; docs/crm/README.md). Pieza C1a: solo tablas, códigos consecutivos y registro de cambios; sin pantallas ni rutas todavía.

`CRM_ENABLED` (por defecto 0): con 0 no hay rutas del CRM y `create_tenant` sigue entregando el código hexadecimal de siempre (así queda el servidor local, que NO corre el CRM).
Con 1 (solo en la nube, y solo DESPUÉS de fijar el contador con scripts/crm_set_counter.py): `create_tenant` entrega el siguiente número consecutivo.
"""
import os
import re
import unicodedata
from typing import Optional

# Estados de una cuenta. Se validan en el código (no con CHECK en la base) para poder ajustar la lista cuando se vea la exportación de SuiteCRM: editar esta tupla y listo, sin migración.
ACCOUNT_STATUSES = ("activo", "inactivo", "masivo")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def crm_enabled() -> bool:
    return os.getenv("CRM_ENABLED", "0").strip().lower() in _TRUE


def validate_status(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    if v not in ACCOUNT_STATUSES:
        raise ValueError(f"Estado de cuenta no válido: «{value}». Usa uno de: {', '.join(ACCOUNT_STATUSES)}.")
    return v


def normalize(text: Optional[str]) -> str:
    """Texto para buscar y detectar duplicados: minúsculas, sin tildes, espacios colapsados."""
    s = unicodedata.normalize("NFKD", (text or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)
