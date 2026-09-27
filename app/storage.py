"""Almacenamiento de archivos (fotos, adjuntos, archivos de formularios, informes, logos, firmas) detrás de UNA interfaz.

Hoy: carpeta local (`STORAGE_LOCAL_DIR`, por defecto `data`). Después (Cloud Run): Cloud Storage, cambiando solo `STORAGE_BACKEND` y
agregando la clase `GcsStorage` con los mismos métodos — el resto del código nunca toca el sistema de archivos directamente.

Una CLAVE es una ruta relativa con «/» (por ejemplo `acme/known_people/1001.jpg`). Los valores viejos guardados en la base como
`data/acme/...` se aceptan igual (se les quita el prefijo `data/`), así que no hace falta migrar nada.

`response()` devuelve la respuesta HTTP que sirve el archivo: en local lo lee del disco; con Cloud Storage sería una redirección
a una URL firmada de corta vida, sin que las rutas que la usan lo noten."""
import mimetypes
import os
import shutil
from typing import Iterable, List, Optional, Protocol

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def move(self, src: str, dst: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def list(self, prefix: str) -> List[str]: ...
    def response(self, key: str, filename: Optional[str] = None, media_type: Optional[str] = None, headers: Optional[dict] = None) -> Response: ...
    def ping(self) -> None: ...


def normalize_key(key: str) -> str:
    """Clave limpia: sin `data/` delante (valores viejos), sin «..», sin barras iniciales ni rutas absolutas."""
    key = (key or "").replace("\\", "/").lstrip("/")
    if key.startswith("data/"):
        key = key[5:]
    parts = [p for p in key.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or (parts and ":" in parts[0]):
        raise ValueError("clave de almacenamiento inválida")
    return "/".join(parts)


def key_of(*parts: object) -> str:
    """Arma una clave a partir de trozos (tenant, carpeta, archivo...)."""
    return normalize_key("/".join(str(p) for p in parts))


class LocalStorage:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _path(self, key: str) -> str:
        path = os.path.abspath(os.path.join(self.root, normalize_key(key)))
        if os.path.commonpath([path, self.root]) != self.root:
            raise ValueError("clave de almacenamiento inválida")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)                       # nunca queda un archivo a medio escribir
        return normalize_key(key)

    def get(self, key: str) -> bytes:
        with open(self._path(key), "rb") as fh:
            return fh.read()

    def exists(self, key: str) -> bool:
        try:
            return os.path.isfile(self._path(key))
        except ValueError:
            return False

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def move(self, src: str, dst: str) -> None:
        target = self._path(dst)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(self._path(src), target)

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self._path(prefix), ignore_errors=True)

    def list(self, prefix: str) -> List[str]:
        base = self._path(prefix)
        out: List[str] = []
        for folder, _, files in os.walk(base):
            for name in files:
                if not name.endswith(".part"):
                    out.append(normalize_key(os.path.relpath(os.path.join(folder, name), self.root)))
        return sorted(out)

    def response(self, key: str, filename: Optional[str] = None, media_type: Optional[str] = None, headers: Optional[dict] = None) -> Response:
        if not self.exists(key):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        return FileResponse(self._path(key), filename=filename, media_type=media_type or mimetypes.guess_type(key)[0], headers=headers)

    def ping(self) -> None:
        """Comprueba que se puede escribir (para /readyz)."""
        os.makedirs(self.root, exist_ok=True)
        probe = os.path.join(self.root, ".readyz")
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)


_storage: Optional[Storage] = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        backend = os.getenv("STORAGE_BACKEND", "local")
        if backend != "local":
            raise RuntimeError(f"STORAGE_BACKEND={backend!r} todavía no está implementado (Fase 1: Cloud Storage)")
        _storage = LocalStorage(os.getenv("STORAGE_LOCAL_DIR", "data"))
    return _storage


def reset_storage() -> None:
    """Las pruebas lo usan para releer `STORAGE_LOCAL_DIR`."""
    global _storage
    _storage = None


def delete_many(keys: Iterable[str]) -> None:
    store = get_storage()
    for key in keys:
        store.delete(key)


# ------------------------------------------------------------------ claves de los archivos de la aplicación (un solo lugar, para no repetir rutas por todo el código)
def photo_key(tenant_id: str, user_id: str) -> str:
    return key_of(tenant_id, "known_people", f"{user_id}.jpg")


def badge_asset_key(tenant_id: str, filename: str) -> str:
    """Imágenes de plantillas (fondos, logos) y de formularios/ruleta: se comparten en `badge_assets` por cliente. Nunca se confía en la ruta que manda el cliente."""
    return key_of(tenant_id, "badge_assets", os.path.basename(filename))


def form_file_key(tenant_id: str, form_id: int, stored: str = "") -> str:
    return key_of(tenant_id, "form_files", form_id, os.path.basename(stored)) if stored else key_of(tenant_id, "form_files", form_id)
