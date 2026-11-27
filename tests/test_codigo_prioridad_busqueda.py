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
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_search_registro": "code_first"})
    assert r.status_code == 200 and r.json()["code_search_registro"] == "id_first"          # sin código activo no queda prendida
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_search_registro": "code_first"})
    assert r.status_code == 200 and r.json()["code_search_registro"] == "code_first"
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": False})
    assert r.json()["code_search_registro"] == "id_first"


def test_find_user_respects_priority(db, factory):
    from app.models import EventAttendee
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1002").first().code = "1001X"
    db.commit()
    assert person_code.find_user(db, ev, "1001")[1] == "id"
    assert person_code.find_user(db, ev, "1001x")[1] == "code"
    ev.code_search_registro = "code_first"
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
    assert 'id="codeOptions"' in html and "data-code-search" in html and "body[m.dataset.codeSearch]" in html
    assert "window.EVENT_CODE_FIRST" in (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/directory.js").read_text(encoding="utf-8")
    assert "codeFirst: window.EVENT_CODE_FIRST === true" in js and "idOnly: window.EVENT_ID_ONLY === true" in js and "const doc = isCode ||" in js


def test_code_only_is_exclusive_with_priority_and_ignores_the_cedula(client, factory, db):
    """0168: «Solo buscar por código»: excluyente con «Dar prioridad al código». El buscador de la pantalla no compara la cédula; el servidor manda el código y,
    si no hay código igual, acepta la identificación de una persona INSCRITA en el evento (hotfix 26-nov-2026: es lo que la pantalla envía al entregar ya elegida)."""
    from app.models import EventAttendee
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_search_first": True})          # las claves viejas siguen sirviendo: aplican a las 3 pantallas
    assert {r.json()[c] for c in person_code.MODULES.values()} == {"code_first"}
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_search_only": True})
    assert {r.json()[c] for c in person_code.MODULES.values()} == {"code_only"}
    factory.person(ev, "3001")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="3001").first().code = "C-9"
    db.commit()
    db.refresh(ev)
    assert person_code.find_user(db, ev, "3001")[1] == "id"                                         # la persona ya elegida (inscrita): sí
    assert person_code.find_user(db, ev, "999999") == (None, "")                                    # ni código ni inscrita: nada
    assert person_code.find_user(db, ev, "c-9")[0].id == "3001"
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": False})
    assert r.json()["code_search_registro"] == "id_first"


def test_inventory_and_areas_pages_wiring():
    inv = (ROOT / "templates/kiosk_inventario.html").read_text(encoding="utf-8")
    ar = (ROOT / "templates/kiosk_areas.html").read_text(encoding="utf-8")
    for html in (inv, ar):
        assert "js/person-card.js" in html and "window.EVENT_CODE_ONLY" in html and "window.REG_CARD_FIELDS" in html
        assert 'staff_role not in ["admin", "super_admin"] %} hidden' in html          # el resumen general solo lo ve el administrador
    assert 'id="invHero"' in inv and "Categorías o productos con existencias" in inv
    assert 'id="areaHero"' in ar and 'id="personBanner"' in ar
    js = (ROOT / "static/js/inventario.js").read_text(encoding="utf-8")
    assert "deliverHereBtn" in js and "qty-none" in js and "function paintHero" in js
    assert "showPerson(result.data" in (ROOT / "static/js/areas.js").read_text(encoding="utf-8")
    par = (ROOT / "templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert 'data-code-search="{{ col }}"' in par and '("code_search_zonas", "Control de zonas")' in par


def test_inventory_delivery_lives_inside_the_person_card():
    """26-nov-2026: debajo de «Registrado», grande: una celda por regalo (la base lo define) o lo marcado con un solo «Entregar» (inventario elegido)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    inv = (root / "static/js/inventario.js").read_text(encoding="utf-8")
    asg = (root / "static/js/inventario-asignado.js").read_text(encoding="utf-8")
    css = (root / "static/css/gw-areas-inv.css").read_text(encoding="utf-8")
    assert 'id="pcardAssign"' in inv and 'id="pcardSel"' in inv and "function paintCardSel" in inv
    assert "function renderCells" in asg and "gw-pcard__go\" data-assign-key" in asg and "data-assign-all" in asg
    assert ".gw-pcard__go" in css and ".gw-pcard__cell" in css


# ------------------------------------------------------------------------------------------ 0169 (26-nov-2026): un modo de búsqueda POR PANTALLA

def test_each_screen_has_its_own_search_mode(client, factory, db):
    """Juan David: en Registro se busca por cédula (ahí se asigna el código) y en Inventario y Zonas solo por código."""
    from app.models import EventAttendee
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_search_registro": "id_only", "code_search_inventario": "code_only", "code_search_zonas": "code_first"})
    assert r.status_code == 200, r.text
    assert (r.json()["code_search_registro"], r.json()["code_search_inventario"], r.json()["code_search_zonas"]) == ("id_only", "code_only", "code_first")
    assert client.put(f"/api/events/{ev.id}/modules", json={"code_search_zonas": "cualquiera"}).status_code == 400
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_search_registro": "id_first"})          # cambiar una no toca las otras
    assert (r.json()["code_search_registro"], r.json()["code_search_inventario"], r.json()["code_search_zonas"]) == ("id_first", "code_only", "code_first")
    client.put(f"/api/events/{ev.id}/modules", json={"code_search_registro": "id_only"})
    factory.person(ev, "4001")
    factory.person(ev, "4002")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="4001").first().code = "4002"          # el código de una es la cédula de la otra
    db.commit()
    db.refresh(ev)
    assert person_code.search_mode(ev, "registro") == "id_only"
    assert person_code.find_user(db, ev, "4002", "registro")[0].id == "4002"          # Registro: solo cédula
    assert person_code.find_user(db, ev, "Z-1", "registro") == (None, "")
    assert person_code.find_user(db, ev, "4002", "inventario")[0].id == "4001"        # Inventario: solo código
    assert person_code.find_user(db, ev, "4002", "zonas")[0].id == "4001"             # Zonas: primero el código
    ev.code_enabled = False
    db.commit()
    assert person_code.search_mode(ev, "inventario") == "id_first"                     # sin «Usar código» el modo no aplica
    assert person_code.find_user(db, ev, "4002", "inventario")[0].id == "4002"


def test_pages_get_their_own_mode():
    for tpl, col in (("kiosk_registro.html", "code_search_registro"), ("kiosk_inventario.html", "code_search_inventario"), ("kiosk_areas.html", "code_search_zonas")):
        html = (ROOT / "templates" / tpl).read_text(encoding="utf-8")
        assert f"event.{col} if event.code_enabled" in html and "window.EVENT_ID_ONLY" in html
        assert "event.code_search_first" not in html and "event.code_search_only" not in html
    src = (ROOT / "app/routers/areas_inventory.py").read_text(encoding="utf-8")
    assert src.count('"inventario")') >= 2 and src.count('"zonas")') >= 2
    assert 'find_user(db, event, cedula, "registro")' in (ROOT / "app/routers/api.py").read_text(encoding="utf-8")
    mig = (ROOT / "alembic/versions/0169_code_search_by_module.py").read_text(encoding="utf-8")
    assert len("0169_code_search_by_module") <= 32 and "WHEN code_search_only THEN 'code_only'" in mig
