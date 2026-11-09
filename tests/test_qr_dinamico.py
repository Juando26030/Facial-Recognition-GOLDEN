"""Fase 8: QR dinámico de la credencial digital (firma + vigencia validadas en el servidor) y pases de Wallet (docs/21_QR_DINAMICO_WALLET.md)."""
import datetime
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app import digital_badge, dynamic_qr, wallet
from app.models import EventAttendee
from tests.conftest import login

QR_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "qr.js"
TOKEN = "tok-abc"


# ------------------------------------------------------------------ puro: firmar y verificar
def test_dynamic_code_is_valid_only_inside_its_window():
    now = 1_000_000.0
    w = dynamic_qr.window_of(now)
    code = dynamic_qr.make_dynamic(5, TOKEN, w)
    parsed = dynamic_qr.parse(code)
    assert parsed and parsed["kind"] == "d" and parsed["att_id"] == 5 and parsed["window"] == w
    assert dynamic_qr.verify(parsed, TOKEN, now) == "ok"
    assert dynamic_qr.verify(parsed, TOKEN, now + dynamic_qr.STEP_SECONDS * dynamic_qr.BACK_WINDOWS) == "ok"          # aún se lee un rato después
    assert dynamic_qr.verify(parsed, TOKEN, now + dynamic_qr.STEP_SECONDS * (dynamic_qr.BACK_WINDOWS + 1)) == "expired"   # una captura caduca
    assert dynamic_qr.verify(dynamic_qr.parse(dynamic_qr.make_dynamic(5, TOKEN, w + 50)), TOKEN, now) == "expired"        # del futuro lejano: no vale


def test_tampering_and_regenerated_link_invalidate_codes():
    now = 1_000_000.0
    code = dynamic_qr.make_dynamic(5, TOKEN, dynamic_qr.window_of(now))
    assert dynamic_qr.verify(dynamic_qr.parse(code), "otro-token", now) == "invalid"          # regenerar el enlace de la persona mata sus códigos
    other = code.replace(".5.", ".6.", 1)                                                       # cambiar de persona
    assert dynamic_qr.verify(dynamic_qr.parse(other), TOKEN, now) == "invalid"
    assert dynamic_qr.verify(None, TOKEN, now) == "invalid" and dynamic_qr.verify(dynamic_qr.parse(code), "", now) == "invalid"


def test_static_code_has_no_window_and_never_expires():
    code = dynamic_qr.make_static(5, TOKEN)
    parsed = dynamic_qr.parse(code)
    assert parsed["kind"] == "s" and parsed["window"] is None
    assert dynamic_qr.verify(parsed, TOKEN, 1.0) == "ok" and dynamic_qr.verify(parsed, TOKEN, 9e9) == "ok"
    assert dynamic_qr.parse("gwq1s.5.3." + "a" * 20) is None and dynamic_qr.parse("gwq1.5." + "a" * 20) is None          # forma mezclada
    for bad in ("1016100329", "1016100329|Ana|Mora", "gwq1.5.1.zz", "", None):
        assert dynamic_qr.parse(bad) is None and not dynamic_qr.looks_like(bad)


def test_batch_gives_consecutive_windows():
    b = dynamic_qr.batch(5, TOKEN, 1_000_000.0)
    assert b["step"] == 30 and len(b["codes"]) == dynamic_qr.BATCH
    assert [c["from_ms"] for c in b["codes"]] == [(dynamic_qr.window_of(1_000_000.0) + i) * 30000 for i in range(dynamic_qr.BATCH)]


# ------------------------------------------------------------------ JS (qr.js)
def _node(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no está instalado")
    return json.loads(subprocess.run([node, "-e", f"console.log(JSON.stringify({expr}))"], capture_output=True, text=True, check=True).stdout)


def test_qr_js_recognises_dynamic_codes_and_leaves_the_rest_alone():
    q = f"require({json.dumps(str(QR_JS))})"
    assert _node(f"{q}.isDynamic({json.dumps('gwq1.5.33333.' + 'a' * 20)})") is True
    assert _node(f"{q}.isDynamic({json.dumps('gwq1s.5.' + 'a' * 20)})") is True
    for plain in ("1016100329", "1016100329|Ana|Mora", "gwq1.5.1.zz"):
        assert _node(f"{q}.isDynamic({json.dumps(plain)})") is False
    assert _node(f"{q}.parse({json.dumps('1016100329|Ana|Mora')})")["cedula"] == "1016100329"          # el QR de la escarapela sigue igual


# ------------------------------------------------------------------ servidor
def _person(db, factory, **ev_extra):
    ev = factory.event("en_proceso", digital_badge_enabled=True, **ev_extra)
    factory.person(ev, "1001", "Ana", "Mora")
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = digital_badge.ensure_token(db, att)
    db.commit()
    return ev, att, token


def test_resolve_accepts_dynamic_and_static_and_rejects_the_rest(client, factory, db):
    ev, att, token = _person(db, factory)
    staff = factory.staff("coordinador", "coord")
    login(client, "coord")
    live = dynamic_qr.make_dynamic(att.id, token, dynamic_qr.window_of())
    r = client.post("/api/qr/resolve", json={"text": live, "event_id": ev.id})
    assert r.status_code == 200 and r.json() == {"kind": "d", "cedula": "1001", "first_name": "Ana", "last_name": "Mora"}
    assert client.post("/api/qr/resolve", json={"text": dynamic_qr.make_static(att.id, token), "event_id": ev.id}).json()["kind"] == "s"
    old = dynamic_qr.make_dynamic(att.id, token, dynamic_qr.window_of() - 10)
    assert client.post("/api/qr/resolve", json={"text": old, "event_id": ev.id}).status_code == 410        # captura vieja
    assert client.post("/api/qr/resolve", json={"text": live[:-1] + ("0" if live[-1] != "0" else "1"), "event_id": ev.id}).status_code == 400
    other = factory.event("en_proceso", digital_badge_enabled=True)
    assert client.post("/api/qr/resolve", json={"text": live, "event_id": other.id}).status_code == 400   # es de OTRO evento
    assert staff and client.post("/api/qr/resolve", json={"text": live}).status_code == 400


def test_resolve_needs_a_session_and_dies_when_the_link_is_regenerated(client, factory, db):
    ev, att, token = _person(db, factory)
    live = dynamic_qr.make_dynamic(att.id, token, dynamic_qr.window_of())
    assert client.post("/api/qr/resolve", json={"text": live, "event_id": ev.id}).status_code == 401
    factory.staff("coordinador", "coord")
    login(client, "coord")
    att.digital_token = "nuevo-enlace"          # revocar: se regenera el enlace de la persona
    db.commit()
    assert client.post("/api/qr/resolve", json={"text": live, "event_id": ev.id}).status_code == 400


def test_personal_page_serves_a_rotating_code_batch_without_the_cedula(client, factory, db):
    ev, att, token = _person(db, factory)
    r = client.get(f"/b/{token}/qr")
    body = r.json()
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    assert len(body["codes"]) == dynamic_qr.BATCH and all(dynamic_qr.looks_like(c["code"]) for c in body["codes"])
    assert "1001" not in r.text                  # el código no lleva la cédula
    assert client.get("/b/no-existe/qr").status_code == 404
    ev.digital_badge_enabled = False
    db.commit()
    assert client.get(f"/b/{token}/qr").status_code == 404


def test_wallet_buttons_are_hidden_and_endpoints_404_without_credentials(client, factory, db, monkeypatch):
    for k in ("WALLET_GOOGLE_ISSUER_ID", "WALLET_GOOGLE_SA_JSON", "WALLET_APPLE_PASS_TYPE_ID", "WALLET_APPLE_TEAM_ID", "WALLET_APPLE_CERT_PEM", "WALLET_APPLE_KEY_PEM", "WALLET_APPLE_WWDR_PEM"):
        monkeypatch.delenv(k, raising=False)
    ev, att, token = _person(db, factory)
    assert client.get(f"/b/{token}/data").json()["wallet"] == {"google": False, "apple": False}
    assert client.get(f"/b/{token}/wallet/google").status_code == 404 and client.get(f"/b/{token}/wallet/apple").status_code == 404


# ------------------------------------------------------------------ Wallet: pases con credenciales de prueba
def _rsa_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def test_google_wallet_link_is_a_signed_jwt_with_the_static_code(monkeypatch):
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key, pem = _rsa_pem()
    monkeypatch.setenv("WALLET_GOOGLE_ISSUER_ID", "3388000000012345")
    monkeypatch.setenv("WALLET_GOOGLE_SA_JSON", json.dumps({"client_email": "sa@proyecto.iam.gserviceaccount.com", "private_key": pem}))
    assert wallet.availability()["google"] is True
    code = dynamic_qr.make_static(7, TOKEN)
    url = wallet.google_save_url(att_id=7, person_name="Ana Mora", event_name="Feria", code=code, origin="https://app.example.com", now=1.0)
    assert url.startswith("https://pay.google.com/gp/v/save/")
    head, body, sig = url.rsplit("/", 1)[1].split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
    claims = json.loads(base64.urlsafe_b64decode(pad(body)))
    assert claims["aud"] == "google" and claims["typ"] == "savetowallet" and claims["origins"] == ["https://app.example.com"]
    obj = claims["payload"]["genericObjects"][0]
    assert obj["barcode"] == {"type": "QR_CODE", "value": code} and obj["header"]["defaultValue"]["value"] == "Ana Mora"
    key.public_key().verify(base64.urlsafe_b64decode(pad(sig)), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())          # firma RS256 válida


def test_apple_pkpass_is_a_signed_zip(monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    def cert(cn):
        key, _ = _rsa_pem()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        c = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1) \
            .not_valid_before(datetime.datetime(2025, 1, 1)).not_valid_after(datetime.datetime(2035, 1, 1)).sign(key, hashes.SHA256())
        return key, c

    key, c = cert("pase")
    _, wwdr = cert("wwdr")
    esc = lambda b: b.decode().replace("\n", "\\n")  # noqa: E731
    monkeypatch.setenv("WALLET_APPLE_PASS_TYPE_ID", "pass.co.golden.credencial")
    monkeypatch.setenv("WALLET_APPLE_TEAM_ID", "ABCDE12345")
    monkeypatch.setenv("WALLET_APPLE_CERT_PEM", esc(c.public_bytes(serialization.Encoding.PEM)))
    monkeypatch.setenv("WALLET_APPLE_KEY_PEM", esc(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
    monkeypatch.setenv("WALLET_APPLE_WWDR_PEM", esc(wwdr.public_bytes(serialization.Encoding.PEM)))
    assert wallet.availability()["apple"] is True
    code = dynamic_qr.make_static(7, TOKEN)
    data = wallet.apple_pkpass(att_id=7, person_name="Ana Mora", event_name="Feria", code=code)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"pass.json", "manifest.json", "signature", "icon.png", "icon@2x.png", "logo.png"} <= set(z.namelist())
    pass_json = json.loads(z.read("pass.json"))
    assert pass_json["barcodes"][0]["message"] == code and pass_json["serialNumber"] == "gw-7" and pass_json["teamIdentifier"] == "ABCDE12345"
    import hashlib
    manifest = json.loads(z.read("manifest.json"))
    assert all(hashlib.sha1(z.read(n)).hexdigest() == h for n, h in manifest.items()) and len(z.read("signature")) > 500


def test_wallet_endpoints_with_credentials(client, factory, db, monkeypatch):
    _, pem = _rsa_pem()
    monkeypatch.setenv("WALLET_GOOGLE_ISSUER_ID", "3388000000012345")
    monkeypatch.setenv("WALLET_GOOGLE_SA_JSON", json.dumps({"client_email": "sa@proyecto.iam.gserviceaccount.com", "private_key": pem}))
    ev, att, token = _person(db, factory)
    assert client.get(f"/b/{token}/data").json()["wallet"]["google"] is True
    r = client.get(f"/b/{token}/wallet/google")
    assert r.status_code == 200 and r.json()["url"].startswith("https://pay.google.com/gp/v/save/")
    assert client.get(f"/b/{token}/wallet/apple").status_code == 404          # Apple sin credenciales
