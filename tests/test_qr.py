"""QR como método de registro (Sprint 4): no es un módulo aparte — entrega la cédula en Registro, Áreas e Inventario."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import login

QR_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "qr.js"


def _parse_in_node(raw):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no está instalado")
    out = subprocess.run(
        [node, "-e", f"console.log(JSON.stringify(require({json.dumps(str(QR_JS))}).parse({json.dumps(raw)})))"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


# ------------------------------- formato del contenido del QR (qr.js) -------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("1016100329", {"cedula": "1016100329", "nombres": "", "apellidos": "", "isQr": False}),   # ID suelto: como escribir la cédula
    ("  1016100329 \n", {"cedula": "1016100329", "nombres": "", "apellidos": "", "isQr": False}),
    ("1016100329|Ana|Prueba Mora", {"cedula": "1016100329", "nombres": "Ana", "apellidos": "Prueba Mora", "isQr": True}),
    ("Ana|Prueba|1.016.100.329", {"cedula": "1016100329", "nombres": "Ana", "apellidos": "Prueba", "isQr": True}),  # orden distinto: la cédula es el trozo numérico
    ("1016100329|Ana Prueba", {"cedula": "1016100329", "nombres": "Ana Prueba", "apellidos": "", "isQr": True}),
    ("1016100329|", {"cedula": "1016100329", "nombres": "", "apellidos": "", "isQr": True}),
    ("Ana|Prueba", {"cedula": "Ana", "nombres": "Prueba", "apellidos": "", "isQr": True}),         # sin ningún número: el primero es la cédula
])
def test_qr_content_parsing(raw, expected):
    assert _parse_in_node(raw) == expected


def test_empty_qr_is_ignored():
    assert _parse_in_node("   ") is None


# ------------------------------- Registro: mismo flujo que la cédula, con método "qr" -------------------------------
def test_registro_qr_is_logged_as_qr_and_follows_cedula_then_name(client, factory, db):
    from app.models import AccessLog

    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", "Ana", "Prueba", attend=False)
    login(client, "root")
    ok = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "method": "qr"}).json()
    assert ok["result"] == "SÍ"
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").one().registration_method == "qr"
    # QR con cédula que no existe pero con nombre: no acredita solo, propone por nombre (igual que la cédula)
    by_name = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "9999", "first_name": "Ana", "last_name": "Prueba", "method": "qr"}).json()
    assert by_name["result"] == "NO_MATCH" and [m["id"] for m in by_name["name_matches"]] == ["1001"]
    # QR desconocido
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "9999", "method": "qr"}).json()["name_matches"] == []


def test_registro_qr_duplicate_is_warned_like_cedula(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", attend=False)
    login(client, "root")
    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "method": "qr"})
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "method": "qr"}).json()["result"] == "DUPLICADO"


def test_unknown_method_value_is_not_stored_as_qr(client, factory, db):
    from app.models import AccessLog

    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", attend=False)
    login(client, "root")
    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "method": "<script>"})
    assert db.query(AccessLog).filter_by(user_id="1001").one().registration_method == "autoregistro"


def test_registro_qr_needs_event_in_progress(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("finalizado")
    factory.person(ev, "1001", attend=False)
    login(client, "root")
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "method": "qr"}).status_code == 403


# ------------------------------- Control de Áreas e Inventario -------------------------------
def _area_event(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", "Ana", "Prueba")
    login(client, "root")
    client.put(f"/api/events/{ev.id}/modules", json={"areas_enabled": True, "inventory_enabled": True})
    return ev


def test_areas_accepts_qr_in_place_of_cedula(client, factory, db):
    from app.models import AreaMovement

    ev = _area_event(client, factory)
    area = client.post(f"/api/events/{ev.id}/areas", json={"name": "VIP"}).json()
    r = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json={"cedula": "1001", "direction": "auto", "method": "qr"}).json()
    assert r["result"] == "OK" and r["direction"] == "in"
    assert db.query(AreaMovement).one().method == "qr"
    out = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json={"cedula": "1001", "direction": "auto", "method": "qr"}).json()
    assert out["direction"] == "out"                                            # funciona igual que con la cédula: alterna entrada/salida
    ghost = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json={"cedula": "9999", "method": "qr"})
    assert ghost.status_code == 404                                             # QR de alguien que no está en el evento


def test_areas_no_reentry_rule_applies_to_qr_too(client, factory):
    ev = _area_event(client, factory)
    area = client.post(f"/api/events/{ev.id}/areas", json={"name": "Backstage", "allow_reentry": False}).json()
    url = f"/api/events/{ev.id}/areas/{area['id']}/movement"
    assert client.post(url, json={"cedula": "1001", "direction": "in", "method": "qr"}).json()["result"] == "OK"
    client.post(url, json={"cedula": "1001", "direction": "out", "method": "qr"})
    assert client.post(url, json={"cedula": "1001", "direction": "in", "method": "qr"}).json()["result"] == "ALREADY_ENTERED"


def test_inventory_delivery_works_for_a_person_selected_by_qr(client, factory):
    """En Inventario el QR solo elige a la persona (mismo id que la cédula); la entrega es la de siempre."""
    ev = _area_event(client, factory)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Camiseta", "initial_qty": 2}).json()
    ok = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": item["id"], "qty": 1}]}).json()
    assert ok["result"] == "OK" and ok["delivered"] == [{"name": "Camiseta", "qty": 1}]
    assert client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "9999", "items": [{"item_id": item["id"], "qty": 1}]}).status_code == 404


def test_digital_badge_page_offers_a_qr_with_the_cedula(client, factory, db):
    from app.models import EventAttendee

    ev = factory.event("en_proceso", digital_badge_enabled=True)
    factory.person(ev, "1001", "Ana", "Prueba")
    db.query(EventAttendee).filter_by(user_id="1001").update({"digital_token": "TOK1"})
    db.commit()
    page = client.get("/b/TOK1")
    assert page.status_code == 200 and 'id="qrEntry"' in page.text and "qrcode(0" in page.text


def test_no_separate_qr_module_or_placeholder_in_event_menu(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    login(client, "root")
    menu = client.get(f"/kiosk/{ev.id}").text
    assert "Código QR" not in menu and "Próximamente" not in menu
    registro = client.get(f"/kiosk/{ev.id}/registro").text
    assert 'id="scanQrBtn"' in registro and "js/qr.js" in registro                 # el QR vive DENTRO de Registro
