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


# Barra de secciones del CRM (templates/_crm_nav.html). (clave, texto, dirección, solo admin). Una sección aparece cuando su pieza se fusiona: el integrador la agrega a SECTIONS_BUILT.
SECTIONS = (("cuentas", "Cuentas", "/crm", False), ("oportunidades", "Oportunidades", "/crm/oportunidades", False), ("leads", "Leads", "/crm/leads", False),
            ("cotizaciones", "Cotizaciones", "/crm/cotizaciones", False), ("midia", "Mi día", "/crm/mi-dia", False), ("tableros", "Tableros", "/crm/tableros", False),
            ("buscar", "Buscar", "/crm/buscar", False), ("embudos", "Embudos", "/crm/embudos", True), ("importar", "Importar", "/crm/importar", True))
SECTIONS_BUILT = {"cuentas", "oportunidades", "leads", "embudos"}


def sections(is_admin: bool, built=None) -> list:
    """Secciones visibles para quien mira, en orden. `built` solo lo usan las pruebas y el arnés visual (que muestran todas)."""
    have = SECTIONS_BUILT if built is None else built
    return [{"key": k, "label": label, "href": href} for k, label, href, admin_only in SECTIONS if k in have and (is_admin or not admin_only)]
