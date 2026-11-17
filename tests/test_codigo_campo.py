"""«Código de la persona» como campo del evento (17-nov-2026): interruptor en Parámetros › Campos (arriba de las categorías), campo en «Campos de la persona»,
Registrar/Editar y formulario de persona, y variable del diseñador de escarapelas — todo SOLO con el interruptor activo."""
from pathlib import Path

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ textos y plantillas (sin base de datos)
def test_switch_lives_in_fields_above_categories():
    html = _read("templates/kiosk_parametros.html")
    campos = html.index('id="grp_campos"')
    code = html.index("<h4>Código de la persona (QR)</h4>")
    cats = html.index("<h4>Categorías del evento</h4>")
    zonas = html.index('id="grp_zonas"') if 'id="grp_zonas"' in html else None
    assert campos < code < cats                                        # dentro de «Campos» y ANTES de las categorías
    if zonas is not None:
        assert not (zonas < code < campos)
    assert html.count('id="codeEnabled"') == 1 and html.count('data-psave="mod_code"') == 1


def test_required_checkbox_in_fields_table_follows_the_event():
    html = _read("templates/kiosk_parametros.html")
    assert "'birth_date', 'last_name', 'code'].includes(cfg.key)" in html


def test_registration_and_edit_use_the_field_config_not_a_hardcoded_box():
    assert "regCodeBox" not in _read("templates/kiosk_registro.html")
    reg = _read("templates/kiosk_registro.html")
    assert 'cfg.key == "code"' in reg and 'cfg.key not in ("last_name", "code")' in reg
    js = _read("static/js/directory.js")
    assert "fieldRow('Código del QR', 'code'" not in js
    assert "(cfg.key === 'last_name' || cfg.key === 'code')" in js
    assert "payload.code = val('code')" in js


def test_person_form_does_not_let_the_design_decide_if_code_is_required():
    from app import personform
    assert "code" in personform.EVENT_DECIDES and "code" not in personform.ALWAYS_REQUIRED
    assert "EVENT_DECIDES = ['last_name', 'code']" in _read("static/js/person-form-designer.js")


def test_badge_designer_offers_code_only_when_enabled():
    html = _read("templates/badge_editor.html")
    assert 'window.EVENT_CODE_ENABLED = {{ "true" if event.code_enabled else "false" }}' in html
    assert "if (window.EVENT_CODE_ENABLED) FIXED_VARIABLES.splice(5, 0, ['code', 'Código de la persona (QR)'])" in html


def test_public_web_forms_never_offer_the_code():
    assert '"digital_contact", "code")' in _read("app/routers/forms.py")


# ------------------------------------------------------------------ con base de datos
def _admin(client, factory):
    factory.staff("admin", "root")
    assert login(client, "root").status_code == 302


def test_code_field_exists_only_when_enabled_and_follows_required(client, factory):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    keys = lambda: {c["key"]: c for c in client.get(f"/api/events/{ev.id}/field-configs").json()}  # noqa: E731
    assert "code" not in keys()
    assert client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_required": False}).status_code == 200
    cfg = keys()["code"]
    assert cfg["locked"] is True and cfg["required"] is False and cfg["label"] == "Código de la persona (QR)"
    assert list(keys())[3] == "code"                                              # justo después de cédula, nombres y apellidos
    assert client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_required": True}).status_code == 200
    assert keys()["code"]["required"] is True
    r = client.put(f"/api/events/{ev.id}/field-configs/code", json={"label": "Serial QR", "sort_order": 9})
    assert r.status_code == 200 and r.json()["label"] == "Serial QR"              # nombre y posición sí se pueden cambiar
    assert client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": False, "code_required": False}).status_code == 200
    assert "code" not in keys()


def test_badge_print_data_carries_the_code_only_when_enabled(client, factory, db):
    from app.models import EventAttendee
    _admin(client, factory)
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").update({"code": "QR-77"})
    db.commit()
    data = client.get(f"/api/users/1001/badge-print-data?event_id={ev.id}").json()
    assert data["code"] == "QR-77"
    off = factory.event("en_proceso")
    factory.person(off, "1002")
    assert "code" not in client.get(f"/api/users/1002/badge-print-data?event_id={off.id}").json()
