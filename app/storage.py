"""Almacenamiento de archivos (fotos, adjuntos, archivos de formularios, informes, logos, firmas) detrás de UNA interfaz.

Hoy: carpeta local (`STORAGE_LOCAL_DIR`, por defecto `data`). Después (Cloud Run): Cloud Storage, cambiando solo `STORAGE_BACKEND` y
agregando la clase `GcsStorage` con los mismos métodos — el resto del código nunca toca el sistema de archivos directamente.

Una CLAVE es una ruta relativa con «/» (por ejemplo `acme/known_people/1001.jpg`). Los valores viejos guardados en la base como
`data/acme/...` se aceptan igual (se les quita el prefijo `data/`), así que no hace falta migrar nada.

`response()` devuelve la respuesta HTTP que sirve el archivo: en local lo lee del disco; con Cloud Storage lo transmite por la app en
trozos (sin URLs firmadas: no piden el permiso de firmar a la cuenta de servicio, y fotos/firmas se sirven descifradas por la app de
todos modos). Las rutas que lo usan no notan la diferencia.

Cloud Storage: `STORAGE_BACKEND=gcs`, `GCS_BUCKET` y, opcional, `GCS_PREFIX` (carpeta dentro del bucket). Credenciales: las de la
cuenta de servicio del servicio de Cloud Run (nunca una llave en archivo)."""
import mimetypes
from datetime import timedelta
import os
import shutil
from typing import Iterable, List, Optional, Protocol
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse


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


class GcsStorage:
    """Mismos métodos que LocalStorage sobre un bucket de Cloud Storage (`google-cloud-storage`, importado solo si se usa)."""

    def __init__(self, bucket: str, prefix: str = "", client=None):
        from google.cloud import storage as gcs
        from google.cloud.exceptions import NotFound
        self._missing = NotFound
        self.client = client or gcs.Client()
        self.bucket = self.client.bucket(bucket)
        self.prefix = normalize_key(prefix)

    def _name(self, key: str) -> str:
        k = normalize_key(key)
        return f"{self.prefix}/{k}" if self.prefix and k else (self.prefix or k)

    def _folder(self, prefix: str) -> str:
        name = self._name(prefix)
        return f"{name}/" if name else ""        # «acme/» y no «acme»: borrar/listar acme nunca toca acme2

    def put(self, key: str, data: bytes) -> str:
        self.bucket.blob(self._name(key)).upload_from_string(data, content_type=mimetypes.guess_type(key)[0] or "application/octet-stream")
        return normalize_key(key)                # una subida a Cloud Storage es atómica: nunca queda a medias

    def get(self, key: str) -> bytes:
        try:
            return self.bucket.blob(self._name(key)).download_as_bytes()
        except self._missing:
            raise FileNotFoundError(key)

    def exists(self, key: str) -> bool:
        try:
            return self.bucket.blob(self._name(key)).exists()
        except ValueError:
            return False

    def delete(self, key: str) -> None:
        try:
            self.bucket.blob(self._name(key)).delete()
        except self._missing:
            pass

    def move(self, src: str, dst: str) -> None:
        try:
            self.bucket.rename_blob(self.bucket.blob(self._name(src)), self._name(dst))
        except self._missing:
            raise FileNotFoundError(src)

    def delete_prefix(self, prefix: str) -> None:
        for blob in self.client.list_blobs(self.bucket, prefix=self._folder(prefix)):
            try:
                blob.delete()
            except self._missing:
                pass

    def list(self, prefix: str) -> List[str]:
        cut = len(self.prefix) + 1 if self.prefix else 0
        return sorted(b.name[cut:] for b in self.client.list_blobs(self.bucket, prefix=self._folder(prefix)))

    def response(self, key: str, filename: Optional[str] = None, media_type: Optional[str] = None, headers: Optional[dict] = None) -> Response:
        blob = self.bucket.blob(self._name(key))
        try:
            blob.reload()
        except self._missing:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        out = {"content-length": str(blob.size), **(headers or {})}
        if filename:                              # mismo encabezado que arma FileResponse
            quoted = quote(filename)
            out["content-disposition"] = f"attachment; filename*=utf-8''{quoted}" if quoted != filename else f'attachment; filename="{filename}"'

        def chunks():
            with blob.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    yield chunk
        return StreamingResponse(chunks(), media_type=media_type or blob.content_type or mimetypes.guess_type(key)[0], headers=out)

    def signed_put_url(self, key: str, content_type: str, max_bytes: int, expires_seconds: int) -> tuple:
        """URL firmada v4 para que el NAVEGADOR suba directo al bucket (app/uploads.py). Devuelve (url, encabezados que el navegador
        debe mandar tal cual: van firmados). En Cloud Run la cuenta de servicio no tiene llave privada: se firma con la API IAM
        (signBlob), que exige `roles/iam.serviceAccountTokenCreator` de la cuenta sobre sí misma. El bucket necesita CORS para PUT
        desde el dominio de la app (deploy/gcs-app-cors.json)."""
        from google.auth.credentials import Signing
        headers = {"Content-Type": content_type, "x-goog-content-length-range": f"0,{max_bytes}"}
        creds, kwargs = self.client._credentials, {}
        if not isinstance(creds, Signing):
            from google.auth.transport.requests import Request as AuthRequest
            if not creds.valid:
                creds.refresh(AuthRequest())
            kwargs = {"service_account_email": creds.service_account_email, "access_token": creds.token}
        url = self.bucket.blob(self._name(key)).generate_signed_url(
            version="v4", method="PUT", expiration=timedelta(seconds=expires_seconds), headers=headers, **kwargs)
        return url, headers

    def ping(self) -> None:
        """Lectura mínima del bucket (para /readyz; /readyz solo lo usa el arranque, nunca los chequeos frecuentes)."""
        next(iter(self.client.list_blobs(self.bucket, max_results=1)), None)


_storage: Optional[Storage] = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        backend = os.getenv("STORAGE_BACKEND") or "local"      # vacío = local (así lo documentan .env.example y .env.staging.example)
        if backend == "gcs":
            bucket = os.getenv("GCS_BUCKET")
            if not bucket:
                raise RuntimeError("STORAGE_BACKEND=gcs necesita GCS_BUCKET")
            _storage = GcsStorage(bucket, os.getenv("GCS_PREFIX", ""))
        elif backend == "local":
            _storage = LocalStorage(os.getenv("STORAGE_LOCAL_DIR", "data"))
        else:
            raise RuntimeError(f"STORAGE_BACKEND={backend!r} no existe (use local o gcs)")
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
