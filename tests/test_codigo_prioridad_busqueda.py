"""0166 (25-nov-2026): «Dar prioridad al código al buscar persona» (Parámetros › Campos › Código de la persona) y hotfix del código obligatorio en Editar persona."""
from pathlib import Path

from app import person_code
from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def _setup(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    login(client, "root")
    return ev


def test_switch_saves_and_needs_code_enabled(client, factory, db):
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_search_first": True})
    assert r.status_code == 200 and r.json()["code_search_first"] is False          # sin código activo no queda prendida
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_search_first": True})
    assert r.status_code == 200 and r.json()["code_search_first"] is True
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": False})
    assert r.json()["code_search_first"] is False


def test_find_user_respects_priority(db, factory):
    from app.models import EventAttendee
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1002").first().code = "1001X"
    db.commit()
    assert person_code.find_user(db, ev, "1001")[1] == "id"
    assert person_code.find_user(db, ev, "1001x")[1] == "code"
    ev.code_search_first = True
    db.commit()
    assert person_code.find_user(db, ev, "1001X")[0].id == "1002"
    assert person_code.find_user(db, ev, "1001")[1] == "id"          # sin código igual, sigue encontrando por cédula


def test_edit_person_with_required_code_saves(client, factory, db):
    ev = _setup(client, factory)
    assert client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_required": True}).status_code == 200
    factory.person(ev, "2001")
    r = client.patch(f"/api/users/2001?event_id={ev.id}", json={"first_name": "Ana", "code": "C-55"})
    assert r.status_code == 200, r.text                                # antes: 400 «Faltan campos obligatorios: Código de la persona (QR)»
    r = client.patch(f"/api/users/2001?event_id={ev.id}", json={"first_name": "Ana María"})
    assert r.status_code == 200, r.text                                # el código ya guardado cuenta


def test_front_wiring():
    html = (ROOT / "templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert 'id="codeSearchFirst"' in html and "code_search_first: en.checked && sf.checked" in html
    assert "window.EVENT_CODE_FIRST" in (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/directory.js").read_text(encoding="utf-8")
    assert "codeFirst: window.EVENT_CODE_FIRST === true" in js and "const doc = isCode ||" in js
