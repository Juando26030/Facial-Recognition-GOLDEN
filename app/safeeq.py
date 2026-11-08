"""Comparación de secretos en tiempo constante que NUNCA lanza.

`hmac.compare_digest(str, str)` lanza TypeError si algún texto trae caracteres no ASCII, y quien manda el valor (una cabecera, un código, un checksum) es anónimo: eso daba un 500 sin
autenticar (Fase 3, E4). Aquí ambos lados se pasan a bytes UTF-8 y un valor que no es texto simplemente no coincide.
"""
import hmac


def _b(value) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8", "surrogatepass")


def safe_eq(a, b) -> bool:
    """True si `a` y `b` son iguales (tiempo constante). None en cualquiera de los dos = False."""
    if a is None or b is None:
        return False
    try:
        return hmac.compare_digest(_b(a), _b(b))
    except Exception:  # noqa: BLE001 — una comparación nunca debe tumbar la petición
        return False
