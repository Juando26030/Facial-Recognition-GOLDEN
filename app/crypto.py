"""Cifrado en reposo del dato biométrico (Ley 1581: dato sensible): el `face_encoding` de la base y las fotos de `data/<cliente>/known_people/`.

- Algoritmo: Fernet (AES-128-CBC + HMAC-SHA256, de la librería `cryptography`). Llave en `FACE_ENCRYPTION_KEY` (`.env`; generarla con `scripts/gen_face_key.py`).
  Acepta VARIAS llaves separadas por coma: la primera cifra y todas descifran (así se rota una llave sin perder datos).
- SIN llave configurada la app sigue funcionando y guarda en claro (desarrollo/pruebas y el periodo previo a activar el cifrado); lo ya cifrado NO se puede leer
  sin su llave (se devuelve vacío y se registra el error, nunca se rompe una pantalla).
- Lo cifrado se reconoce por su marca (`enc1:` en texto, `GWENC1:` en archivos), así que conviven datos viejos en claro y nuevos cifrados; `scripts/encrypt_faces.py`
  cifra lo que haya en claro.
- ⚠️ PERDER LA LLAVE = PERDER LOS DATOS BIOMÉTRICOS cifrados. La llave vive en el `.env` (que el respaldo nocturno copia al bucket con versionado); guárdala también en
  un gestor de contraseñas.
"""
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

log = logging.getLogger("golden.crypto")
TEXT_PREFIX = "enc1:"
FILE_MAGIC = b"GWENC1:"
_cache: dict = {}


def _fernet() -> Optional[MultiFernet]:
    raw = os.getenv("FACE_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    if raw not in _cache:
        _cache.clear()
        _cache[raw] = MultiFernet([Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()])
    return _cache[raw]


def enabled() -> bool:
    return _fernet() is not None


def encrypt_text(value: str) -> str:
    f = _fernet()
    if f is None or value is None or value.startswith(TEXT_PREFIX):
        return value
    return TEXT_PREFIX + f.encrypt(value.encode()).decode()


def decrypt_text(value: str) -> Optional[str]:
    if value is None or not value.startswith(TEXT_PREFIX):
        return value                     # dato viejo en claro
    f = _fernet()
    try:
        if f is None:
            raise InvalidToken()
        return f.decrypt(value[len(TEXT_PREFIX):].encode()).decode()
    except InvalidToken:
        log.error("No se pudo descifrar un dato biométrico: falta o no coincide FACE_ENCRYPTION_KEY")
        return None


def encrypt_bytes(data: bytes) -> bytes:
    f = _fernet()
    return data if f is None or data.startswith(FILE_MAGIC) else FILE_MAGIC + f.encrypt(data)


def decrypt_bytes(data: bytes) -> Optional[bytes]:
    if not data.startswith(FILE_MAGIC):
        return data
    f = _fernet()
    try:
        if f is None:
            raise InvalidToken()
        return f.decrypt(data[len(FILE_MAGIC):])
    except InvalidToken:
        log.error("No se pudo descifrar una foto: falta o no coincide FACE_ENCRYPTION_KEY")
        return None


def save_image(pil_image, path: str) -> None:
    """Guarda una imagen PIL como JPEG, cifrada si hay llave."""
    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG")
    with open(path, "wb") as fh:
        fh.write(encrypt_bytes(buf.getvalue()))


def read_bytes(path: str) -> Optional[bytes]:
    """Contenido de una foto ya descifrado (o None si no se puede descifrar)."""
    with open(path, "rb") as fh:
        return decrypt_bytes(fh.read())


def read_array(path: str):
    """La foto como arreglo numpy RGB (lo que espera `face_recognition`), o None."""
    import io

    import numpy as np
    from PIL import Image
    raw = read_bytes(path)
    return None if raw is None else np.array(Image.open(io.BytesIO(raw)).convert("RGB"))


class EncryptedText(TypeDecorator):
    """Columna de texto cifrada de forma transparente: el resto del código lee y escribe el valor en claro."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_text(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return decrypt_text(value) if isinstance(value, str) else value
