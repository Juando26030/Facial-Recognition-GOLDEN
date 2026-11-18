"""QR en vCard (Fase 10, bloque C): guardar el contacto al escanear con el celular, sin perder el escaneo de Golden (Registro, Áreas, Inventario, expositores, Wallet)."""
import json
import pathlib
import shutil
import subprocess

import pytest

from app import dynamic_qr, qr_vcard

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba"


# ------------------------------------------------------------------ Python puro
def test_build_has_the_minimal_card_with_the_code_in_note():
    card = qr_vcard.build("Ana", "Pérez", "300 123 4567", note="1016100329|Ana|Pérez")
    assert card.split("\n") == ["BEGIN:VCARD", "VERSION:3.0", "N:Pérez;Ana;;;", "FN:Ana Pérez", "TEL:300 123 4567", "NOTE:GW:1016100329|Ana|Pérez", "END:VCARD"]
    assert "TEL" not in qr_vcard.build("Ana", "P", "", note="x") and "FN:Asistente" in qr_vcard.build(note="x")


@pytest.mark.parametrize("payload", ["1016100329", "1016100329|Ana|Pérez", "Ana, la; de\\Mora|1.016.100.329", "gwq1.5.12345678." + "a" * 20, "gwq1s.5." + "b" * 20])
def test_round_trip_and_old_format_untouched(payload):
    assert qr_vcard.unwrap(qr_vcard.build("Ana", "Mora", "3001234567", note=payload)) == payload
    assert qr_vcard.unwrap(payload) == payload                                   # el formato anterior pasa igual
    assert qr_vcard.unwrap(qr_vcard.build("Ana", note=payload).replace("\n", "\r\n")) == payload


def test_foreign_vcard_and_flattened_scanner_output():
    foreign = "BEGIN:VCARD\nVERSION:3.0\nFN:Otro\nEND:VCARD"
    assert qr_vcard.unwrap(foreign) == foreign
    assert qr_vcard.unwrap(qr_vcard.build("Ana", note="1016100329").replace("\n", "")) == "1016100329"       # un lector que se come los saltos de línea
    assert qr_vcard.unwrap(None) == "" and qr_vcard.unwrap("") == ""


def test_signed_codes_still_verify_when_wrapped_in_a_vcard():
    now = 1_000_000.0
    dyn = dynamic_qr.make_dynamic(5, TOKEN, dynamic_qr.window_of(now))
    static = dynamic_qr.make_static(5, TOKEN)
    for code, kind in ((dyn, "d"), (static, "s")):
        wrapped = qr_vcard.build("Ana", "Mora", "3001234567", note=code)
        parsed = dynamic_qr.parse(wrapped)
        assert parsed and parsed["kind"] == kind and dynamic_qr.looks_like(wrapped)
        assert dynamic_qr.verify(parsed, TOKEN, now) == "ok"
        assert dynamic_qr.verify(dynamic_qr.parse(code), TOKEN, now) == "ok"          # y sin vCard, como siempre
    assert dynamic_qr.parse(qr_vcard.build("Ana", note="1016100329")) is None         # una cédula en vCard no es un código firmado


def test_exhibitor_scan_reads_both_formats():
    from app import contacts
    assert contacts.parse_scanned("1016100329|Ana|Mora") == {"kind": "cedula", "cedula": "1016100329"}
    assert contacts.parse_scanned(qr_vcard.build("Ana", "Mora", "3001234567", note="1016100329|Ana|Mora")) == {"kind": "cedula", "cedula": "1016100329"}
    assert contacts.parse_scanned(qr_vcard.build("Ana", note="1016100329")) == {"kind": "cedula", "cedula": "1016100329"}
    tok = "A" * 20
    assert contacts.parse_scanned(qr_vcard.build("Ana", note=f"https://x.co/tarjeta/{tok}")) == {"kind": "card", "token": tok}


# ------------------------------------------------------------------ JS (se corre en Node; paridad con Python)
def _node(*args):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no está instalado")
    return subprocess.run([node, *args], capture_output=True, text=True, cwd=ROOT, timeout=60)


def test_js_check_passes():
    r = _node("tests/js/qr_vcard_check.js")
    assert r.returncode == 0 and "qr_vcard_check OK" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]


@pytest.mark.parametrize("args", [("Ana", "Pérez", "300 123 4567", "1016100329|Ana|Pérez"), ("A;B,C", "D", "", "x"), ("", "", "", "1016100329")])
def test_js_and_python_build_the_same_card(args):
    first, last, phone, note = args
    expr = f"console.log(JSON.stringify(require('./static/js/vcard.js').build({{first_name:{json.dumps(first)},last_name:{json.dumps(last)},phone:{json.dumps(phone)},note:{json.dumps(note)}}})))"
    r = _node("-e", expr)
    assert json.loads(r.stdout) == qr_vcard.build(first, last, phone, note)


# ------------------------------------------------------------------ texto de las páginas (corre sin base)
def test_every_page_with_a_reader_or_renderer_loads_vcard_js_first():
    for page in ("kiosk_registro", "kiosk_areas", "kiosk_inventario", "expositor"):
        src = (ROOT / "templates" / f"{page}.html").read_text(encoding="utf-8")
        assert "js/vcard.js" in src and src.index("js/vcard.js") < src.index("js/qr.js"), page
    for page in ("digital_badge", "badge_print", "badge_editor", "certificate_public", "kiosk_certificados"):
        src = (ROOT / "templates" / f"{page}.html").read_text(encoding="utf-8")
        assert "js/vcard.js" in src and src.index("js/vcard.js") < src.index("js/badge-render.js"), page


def test_badge_render_draws_the_vcard_with_level_l_and_utf8_and_keeps_the_old_format_as_fallback():
    br = (ROOT / "static/js/badge-render.js").read_text(encoding="utf-8")
    assert "GWVcard" in br and "V.QR_LEVEL" in br and "stringToBytesFuncs['UTF-8']" in br and ": payload" in br
    dig = (ROOT / "templates/digital_badge.html").read_text(encoding="utf-8")
    assert "GWVcard" in dig and "V.QR_LEVEL" in dig and "note: code" in dig


def test_every_scanner_entry_point_unwraps_the_vcard():
    qr = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert qr.count("unwrap(raw)") >= 4 and "onCode(unwrap(text), format)" in qr                          # parse, classify, isDynamic, resolveDynamic y la cámara
    for js in ("static/js/areas.js", "static/js/inventario.js", "static/js/directory.js"):
        assert "QrCode.collect" in (ROOT / js).read_text(encoding="utf-8"), js                           # lector de mano: la vCard llega en varias líneas
    assert "QrCode.collect" in (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "unwrapVcard" in (ROOT / "static/js/search-core.js").read_text(encoding="utf-8")


def test_wallet_pass_carries_the_vcard_with_the_static_signed_code():
    src = (ROOT / "app/routers/digital_public.py").read_text(encoding="utf-8")
    assert "qr_vcard.build(" in src and "note=dynamic_qr.make_static(" in src


# ------------------------------------------------------------------ con base de datos
def test_resolve_accepts_a_vcard_with_the_signed_code(client, factory, db):
    from app import digital_badge
    from app.models import EventAttendee
    from tests.conftest import login
    ev = factory.event("en_proceso", digital_badge_enabled=True)
    factory.person(ev, "1001", "Ana", "Mora")
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = digital_badge.ensure_token(db, att)
    db.commit()
    factory.staff("coordinador", "coord")
    login(client, "coord")
    live = dynamic_qr.make_dynamic(att.id, token, dynamic_qr.window_of())
    card = qr_vcard.build("Ana", "Mora", "3001234567", note=live)
    r = client.post("/api/qr/resolve", json={"text": card, "event_id": ev.id})
    assert r.status_code == 200 and r.json() == {"kind": "d", "cedula": "1001", "first_name": "Ana", "last_name": "Mora"}
    stat = qr_vcard.build("Ana", "Mora", "", note=dynamic_qr.make_static(att.id, token))
    assert client.post("/api/qr/resolve", json={"text": stat, "event_id": ev.id}).json()["kind"] == "s"


# ---- 19-nov-2026: la vCard trae todos los datos de contacto que vengan con valor (empresa, rol, teléfono, correo, categorías) además del nombre y el código
def test_full_card_has_every_contact_field_and_the_code_stays_last():
    card = qr_vcard.build("Ana", "Mora", "300 123 4567", note="1016100329", email="ana@x.co", org="Acme, S.A.", title="Gerente; ventas", categories="VIP, Staff")
    lines = card.split("\n")
    assert "ORG:Acme\\, S.A." in lines and "TITLE:Gerente\; ventas" in lines and "EMAIL:ana@x.co" in lines and "CATEGORIES:VIP,Staff" in lines and "TEL:300 123 4567" in lines
    assert lines[-2] == "NOTE:GW:1016100329" and lines[-1] == "END:VCARD"
    assert qr_vcard.unwrap(card) == "1016100329"


def test_empty_contact_fields_are_left_out_and_a_bad_email_is_ignored():
    card = qr_vcard.build("Ana", note="x", email="no-es-correo", org=" ", title="", categories=" , ")
    assert not any(k in card for k in ("ORG:", "TITLE:", "EMAIL:", "CATEGORIES:"))


def test_js_and_python_build_the_same_full_card():
    import json
    import subprocess
    args = dict(first_name="Ana", last_name="Mora", phone="3001234567", note="1016100329", email="ana@x.co", org="Acme, S.A.", title="Gerente; ventas", categories="VIP, Staff")
    r = subprocess.run(["node", "-e", f"console.log(JSON.stringify(require('./static/js/vcard.js').build({json.dumps(args)})))"], capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent), timeout=30)
    assert json.loads(r.stdout) == qr_vcard.build("Ana", "Mora", "3001234567", "1016100329", email="ana@x.co", org="Acme, S.A.", title="Gerente; ventas", categories="VIP, Staff")
