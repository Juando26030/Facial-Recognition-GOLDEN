"""Subida directa de archivos grandes: el navegador sube al almacenamiento y la app solo firma y después procesa.

Cloud Run rechaza peticiones de más de 32 MiB (HTTP/1) y Firebase Hosting las reenvía por HTTP/1 con un tope de 60 s, así que los
archivos grandes NO pueden pasar por la app. Flujo:

  1. `POST /api/uploads` (staff) o `POST /f/<evento>/<slug>/upload` (formulario público) → `create()` valida propósito, extensión y
     tamaño y devuelve `{url, headers, token}`. Con Cloud Storage `url` es una URL firmada v4 (PUT, 15 min, tamaño máximo firmado en
     `x-goog-content-length-range`); con almacenamiento local es `/api/uploads/local/<token>` (misma app; solo desarrollo y la VM).
  2. El navegador hace PUT del archivo a `url` con esos encabezados.
  3. La petición normal (carga masiva, documento, envío del formulario) manda el `token` en vez del archivo; el endpoint llama a
     `fetch()`, que verifica firma, vencimiento, propósito y alcance (evento/formulario/campo), lee el objeto y comprueba el tamaño.
     El contenido se valida igual que si hubiera llegado en la petición (firma de bytes, imagen, etc.).
  4. `discard()` borra el archivo temporal cuando ya se procesó. Lo abandonado vive bajo `uploads/`: en el bucket lo borra la regla de
     ciclo de vida (deploy/gcs-app-lifecycle.json, 1 día).

El token es la única autorización del PUT local y de `fetch()`: va firmado con SECRET_KEY y lleva la clave del objeto (generada aquí,
nunca elegida por el navegador), así que nadie puede leer ni pisar archivos ajenos."""
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.storage import get_storage, key_of

URL_SECONDS = 15 * 60          # vigencia de la URL de subida
TOKEN_SECONDS = 6 * 60 * 60    # el token sirve para procesar hasta 6 h después (NEEDS_LABELS reenvía la misma carga)

# propósito → (extensiones permitidas, bytes máximos)
PURPOSES = {
    "bulk_roster": ({".xlsx", ".csv"}, 50 * 1024 * 1024),
    "bulk_zip": ({".zip"}, 2 * 1024 * 1024 * 1024),
    "event_doc": ({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods",
                   ".png", ".jpg", ".jpeg", ".webp", ".gif"}, 25_000_000),
    "expense_evidence": ({".png", ".jpg", ".jpeg", ".webp", ".gif"}, 25_000_000),
    "form_file": (None, 20 * 1024 * 1024),       # extensiones y tope reales: los del campo (los valida el endpoint público)
}


@dataclass
class Uploaded:
    filename: str
    content_type: str
    content: bytes
    token: str


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="direct-upload")


def safe_name(name: str) -> str:
    base = os.path.basename(name or "archivo")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80] or "archivo"


def create(purpose: str, scope: dict, tenant_id: str, filename: str, size: int, content_type: str,
           max_bytes: Optional[int] = None, extensions: Optional[set] = None) -> dict:
    """Firma una subida. `scope` ata el token a quien lo pidió (p. ej. {"e": 12} o {"f": 3, "fid": "cv"}); `fetch` exige el mismo."""
    if purpose not in PURPOSES:
        raise HTTPException(status_code=400, detail="Tipo de subida no válido")
    allowed, limit = PURPOSES[purpose]
    allowed, limit = extensions or allowed, min(limit, max_bytes or limit)
    ext = os.path.splitext(filename or "")[1].lower()
    if allowed is not None and ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Formato no permitido — usa uno de: {', '.join(sorted(allowed))}")
    if not isinstance(size, int) or size <= 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if size > limit:
        raise HTTPException(status_code=400, detail=f"El archivo pesa más de {limit // (1024 * 1024)} MB")
    content_type = (content_type or "application/octet-stream")[:100]
    key = key_of("uploads", tenant_id, purpose, uuid.uuid4().hex, safe_name(filename))
    token = _serializer().dumps({"k": key, "p": purpose, "s": scope, "m": limit, "n": os.path.basename(filename)[:200], "c": content_type})
    store = get_storage()
    if hasattr(store, "signed_put_url"):
        url, headers = store.signed_put_url(key, content_type, limit, URL_SECONDS)
    else:
        url, headers = f"/api/uploads/local/{token}", {"Content-Type": content_type}
    return {"url": url, "method": "PUT", "headers": headers, "token": token}


def read_token(token: str, max_age: int = TOKEN_SECONDS) -> dict:
    try:
        return _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        raise HTTPException(status_code=400, detail="La subida del archivo venció: vuelve a seleccionarlo")
    except BadSignature:
        raise HTTPException(status_code=400, detail="Subida de archivo no válida")


def fetch(token: Optional[str], purpose: str, scope: dict) -> Optional[Uploaded]:
    """El archivo ya subido con `token`, o None si no vino token. 400 si el token no corresponde a este propósito/alcance."""
    if not token:
        return None
    data = read_token(token)
    if data.get("p") != purpose or data.get("s") != scope:
        raise HTTPException(status_code=400, detail="Subida de archivo no válida")
    try:
        content = get_storage().get(data["k"])
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="El archivo no terminó de subir: vuelve a intentarlo")
    if not content or len(content) > data["m"]:
        raise HTTPException(status_code=400, detail="El archivo está vacío o supera el tamaño permitido")
    return Uploaded(filename=data["n"], content_type=data["c"], content=content, token=token)


def discard(*items) -> None:
    """Borra los archivos temporales (acepta Uploaded, tokens o None). Nunca falla: lo que quede lo limpia el ciclo de vida."""
    store = get_storage()
    for item in items:
        token = getattr(item, "token", item)
        if not token:
            continue
        try:
            store.delete(read_token(token)["k"])
        except Exception:  # noqa: BLE001
            pass
