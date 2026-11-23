"""Archivos comprimidos del importador: el navegador los manda en gzip (Cloud Run rechaza peticiones de más de 32 MB)."""
import zlib

MAX_UNPACKED = 400 * 1024 * 1024  # tope al descomprimir (protege la memoria)


def maybe_gunzip(raw: bytes) -> bytes:
    """Si el contenido es gzip lo descomprime; si no, lo devuelve igual. Lanza ValueError si está dañado o es demasiado grande."""
    if raw[:2] != b"\x1f\x8b":
        return raw
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(raw, MAX_UNPACKED + 1)
        if d.unconsumed_tail or len(out) > MAX_UNPACKED:
            raise ValueError("El archivo comprimido es demasiado grande.")
        out += d.flush()
    except zlib.error as e:
        raise ValueError("El archivo comprimido está dañado.") from e
    if len(out) > MAX_UNPACKED:
        raise ValueError("El archivo comprimido es demasiado grande.")
    return out
