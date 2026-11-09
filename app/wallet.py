"""Pases de Wallet de la credencial digital (Fase 8, docs/21_QR_DINAMICO_WALLET.md): Google Wallet (enlace «Guardar» con un JWT RS256 firmado por la cuenta de servicio) y Apple Wallet (.pkpass firmado PKCS#7).

TODO por variables de entorno; SIN credenciales no hay botón (`availability()` devuelve falso) y la página personal sigue igual. Nada de secretos en el repo.
  Google: WALLET_GOOGLE_ISSUER_ID, WALLET_GOOGLE_SA_JSON (el JSON de la cuenta de servicio, de Secret Manager)
  Apple:  WALLET_APPLE_PASS_TYPE_ID, WALLET_APPLE_TEAM_ID, WALLET_APPLE_CERT_PEM, WALLET_APPLE_KEY_PEM, WALLET_APPLE_WWDR_PEM, [WALLET_APPLE_KEY_PASSWORD]
Los PEM pueden venir con «\\n» literales (como los guardan los gestores de secretos).
El código del pase es el ESTÁTICO firmado (app/dynamic_qr.make_static): un pase no rota cada 30 s. Solo sirve para entrada y se revoca regenerando el enlace de la persona."""
import base64
import hashlib
import io
import json
import os
import re
import time
import zipfile
from typing import Optional

BRAND = "Golden Eventos y Logística S.A.S."
CLASS_SUFFIX = "gw_credencial"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _pem(name: str) -> bytes:
    return _env(name).replace("\\n", "\n").encode()


def _google_sa() -> Optional[dict]:
    raw = _env("WALLET_GOOGLE_SA_JSON")
    if not raw or not _env("WALLET_GOOGLE_ISSUER_ID"):
        return None
    try:
        sa = json.loads(raw)
    except ValueError:
        return None
    return sa if sa.get("client_email") and sa.get("private_key") else None


def _apple_ready() -> bool:
    return all(_env(k) for k in ("WALLET_APPLE_PASS_TYPE_ID", "WALLET_APPLE_TEAM_ID", "WALLET_APPLE_CERT_PEM", "WALLET_APPLE_KEY_PEM", "WALLET_APPLE_WWDR_PEM"))


def availability() -> dict:
    return {"google": _google_sa() is not None, "apple": _apple_ready()}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ------------------------------------------------------------------------------------------------ Google Wallet
def google_save_url(*, att_id: int, person_name: str, event_name: str, code: str, origin: str = "", now: Optional[float] = None) -> str:
    """https://pay.google.com/gp/v/save/<JWT>. Lanza RuntimeError si Google Wallet no está configurado."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    sa = _google_sa()
    if sa is None:
        raise RuntimeError("Google Wallet no está configurado")
    issuer = _env("WALLET_GOOGLE_ISSUER_ID")
    class_id = f"{issuer}.{CLASS_SUFFIX}"
    obj_id = f"{issuer}.{_SAFE.sub('_', 'gw-' + str(att_id))}"
    payload = {
        "genericClasses": [{"id": class_id}],
        "genericObjects": [{
            "id": obj_id, "classId": class_id, "state": "ACTIVE",
            "cardTitle": {"defaultValue": {"language": "es-CO", "value": "Golden Eventos"}},
            "header": {"defaultValue": {"language": "es-CO", "value": (person_name or "Asistente")[:60]}},
            "subheader": {"defaultValue": {"language": "es-CO", "value": (event_name or "")[:60]}},
            "barcode": {"type": "QR_CODE", "value": code},
            "hexBackgroundColor": "#0a0e2e",
        }],
    }
    claims = {"iss": sa["client_email"], "aud": "google", "typ": "savetowallet", "iat": int(now if now is not None else time.time()), "payload": payload}
    if origin:
        claims["origins"] = [origin]
    head = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"https://pay.google.com/gp/v/save/{head}.{body}.{_b64url(sig)}"


# ------------------------------------------------------------------------------------------------ Apple Wallet
def _icons() -> dict:
    """Iconos del pase a partir del logo de Golden (Pillow): icon 29/58, logo 160x50."""
    from PIL import Image

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img", "logo-golden.png")
    out = {}
    with Image.open(path) as im:
        im = im.convert("RGBA")
        for name, size in (("icon.png", (29, 29)), ("icon@2x.png", (58, 58)), ("logo.png", (160, 50)), ("logo@2x.png", (320, 100))):
            copy = im.copy()
            copy.thumbnail(size)
            buf = io.BytesIO()
            copy.save(buf, "PNG")
            out[name] = buf.getvalue()
    return out


def apple_pass_json(*, att_id: int, person_name: str, event_name: str, code: str) -> dict:
    return {
        "formatVersion": 1,
        "passTypeIdentifier": _env("WALLET_APPLE_PASS_TYPE_ID"),
        "teamIdentifier": _env("WALLET_APPLE_TEAM_ID"),
        "serialNumber": f"gw-{int(att_id)}",
        "organizationName": BRAND,
        "description": "Credencial del evento",
        "logoText": "Golden Eventos",
        "backgroundColor": "rgb(10,14,46)", "foregroundColor": "rgb(255,255,255)", "labelColor": "rgb(212,175,55)",
        "barcodes": [{"format": "PKBarcodeFormatQR", "message": code, "messageEncoding": "iso-8859-1"}],
        "generic": {
            "primaryFields": [{"key": "name", "label": "NOMBRE", "value": (person_name or "Asistente")[:60]}],
            "secondaryFields": [{"key": "event", "label": "EVENTO", "value": (event_name or "")[:60]}],
        },
    }


def apple_pkpass(*, att_id: int, person_name: str, event_name: str, code: str) -> bytes:
    """Archivo .pkpass (zip: pass.json + iconos + manifest.json + signature). Lanza RuntimeError si Apple Wallet no está configurado."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    if not _apple_ready():
        raise RuntimeError("Apple Wallet no está configurado")
    files = {"pass.json": json.dumps(apple_pass_json(att_id=att_id, person_name=person_name, event_name=event_name, code=code), ensure_ascii=False).encode("utf-8")}
    files.update(_icons())
    manifest = json.dumps({name: hashlib.sha1(data).hexdigest() for name, data in files.items()}).encode()
    password = _env("WALLET_APPLE_KEY_PASSWORD").encode() or None
    cert = x509.load_pem_x509_certificate(_pem("WALLET_APPLE_CERT_PEM"))
    key = serialization.load_pem_private_key(_pem("WALLET_APPLE_KEY_PEM"), password=password)
    wwdr = x509.load_pem_x509_certificate(_pem("WALLET_APPLE_WWDR_PEM"))
    signature = (pkcs7.PKCS7SignatureBuilder().set_data(manifest).add_signer(cert, key, hashes.SHA256()).add_certificate(wwdr)
                 .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature]))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("manifest.json", manifest)
        z.writestr("signature", signature)
    return buf.getvalue()
