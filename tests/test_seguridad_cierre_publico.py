"""Cierre de hallazgos de seguridad del lado público (nov-2026): X1–X7. Pruebas de código fuente y de funciones puras, y unas pocas con base (Postgres de pruebas)."""
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from app import formsvc
from app.routers import certificates_public, forms_public
from app.timeutil import utcnow
from tests.test_form_extras import _badge_form
from tests.test_forms import _create, _event, _open, _put, _state, _submit, _url, _person_values  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
JS_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")          # los mismos patrones que valida static/js/form-render.js
JS_PHONE = re.compile(r"^[+\d][\d\s().-]{5,19}$")


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------- X1 / X2: promoción de una inscripción a la base del evento
def test_x2_existing_person_names_and_contact_are_protected_keys():
    assert {"email", "phone", "first_name", "last_name", "role", "entity"} <= formsvc.PUBLIC_FORM_PROTECTED_KEYS


def test_x1_existing_person_badge_goes_only_to_the_contact_on_file(client, factory, outbox, db):
    from app.models import EventAttendee, User
    ev, form = _badge_form(client, factory)
    u = factory.person(ev, "1001", "Ana", "Mora")
    u.email = "real@example.com"
    db.commit()
    vals = {**_person_values(), "nombres": "Impostor", "correo": "atacante@example.com"}
    assert _submit(client, ev, form, vals).status_code == 200
    db.expire_all()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    user = db.query(User).filter_by(id="1001", tenant_id=ev.tenant_id).one()
    assert att.digital_contact == "real@example.com"                                 # no se reemplazó por el del formulario
    assert [m["to"] for m in outbox] == ["real@example.com"]
    assert user.first_name == "Ana" and user.email == "real@example.com"             # X2: el nombre de quien ya existe no se pisa


def test_x1_existing_person_without_contact_uses_the_form_email_once(client, factory, outbox, db):
    """Regla de Juan David: sin contacto previo se usa el correo del formulario; con contacto previo gana el que ya estaba (prueba de arriba)."""
    from app.models import EventAttendee
    ev, form = _badge_form(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    assert _submit(client, ev, form, {**_person_values(), "correo": "nuevo@example.com"}).status_code == 200
    db.expire_all()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    assert att.digital_contact == "nuevo@example.com" and [m["to"] for m in outbox] == ["nuevo@example.com"]


def test_x1_new_person_still_uses_the_form_email(client, factory, outbox, db):
    ev, form = _badge_form(client, factory)
    assert _submit(client, ev, form, _person_values()).status_code == 200
    assert [m["to"] for m in outbox] == ["ana@example.com"]


# ------------------------------- X2: nombre escapado en la confirmación de duplicado
def test_x2_duplicate_confirmation_escapes_the_name():
    js = _src("static/js/toast.js")
    block = js[js.index("window.confirmDuplicateRegistration"):]
    block = block[:block.index("};")]
    assert "<strong>${window.escapeHtml(name)}</strong>" in block and "<strong>${name}</strong>" not in block


# ------------------------------- X3: la cédula enviada es la verificada
def test_x3_normalize_id_matches_lookup():
    assert forms_public.normalize_id(" 1.016.100 329 ") == "1016100329" and forms_public.normalize_id(None) == ""


def test_x3_submit_must_use_the_verified_id(client, factory, db):
    ev = _event(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    f = _create(client, ev)
    _put(client, ev, f, settings={"security": {"enabled": True, "type": "cedula"}, "prefill": {"mode": "cedula", "source": "event"}})
    _open(client, ev, f)
    tok = _state(client, ev, f)["token"]
    ok = client.post(f"{_url(ev, f)}/lookup", json={"id": "1.001", "t": tok}).json()
    other = _submit(client, ev, f, {**_person_values(), "cedula": "2002"}, token=ok["token"])
    assert other.status_code == 403 and "misma con la que ingresaste" in other.json()["detail"]
    assert _submit(client, ev, f, _person_values(), token=ok["token"]).status_code == 200


# ------------------------------- X4: pre-llenado y certificados
@pytest.mark.parametrize("ftype,value", [("email", "ana.maria@empresa.com.co"), ("email", "a@b.co"), ("phone", "+57 300 123 4567"), ("phone", "1" * 30), ("phone", "12")])
def test_x4_masks_keep_a_format_the_browser_accepts(ftype, value):
    masked = forms_public.mask_prefill_value({"type": ftype, "key": "x"}, value)
    assert masked != value and (JS_EMAIL if ftype == "email" else JS_PHONE).match(masked)


def test_x4_mask_rules():
    m = forms_public.mask_prefill_value
    assert m({"type": "text_short", "key": "first_name"}, "Ana María") == "A** M****"
    assert m({"type": "text_short", "key": "id"}, "1001") == "1001"                                  # la cédula la escribió la persona misma
    assert m({"type": "text_short", "key": "x", "doc_types": ["cc"]}, "AB12") == "AB12"
    assert m({"type": "select", "key": "role"}, "VIP") == "VIP"


def test_x4_public_prefill_masks_readonly_and_drops_editable_contact():
    design = {"fields": {
        "ced": {"type": "text_short", "key": "id"},
        "nom": {"type": "text_short", "key": "first_name", "readonly_when_prefilled": True, "mask_asterisks": True},
        "mail_ro": {"type": "email", "key": "email", "readonly_when_prefilled": True},
        "cel": {"type": "phone", "key": "phone"},
        "ent": {"type": "text_short", "key": "entity"},
    }}
    person = {"id": "1001", "first_name": "Ana", "email": "ana@empresa.com", "phone": "3001234567", "entity": "ACME"}
    prefill, readonly = forms_public.public_prefill(design, person)
    assert prefill == {"ced": "1001", "nom": "A**", "mail_ro": "a**@e******.com", "ent": "ACME"} and sorted(readonly) == ["mail_ro", "nom"]


def test_x4_submit_still_takes_readonly_values_from_the_base():
    src = _src("app/routers/forms_public.py")
    assert re.search(r"for fid, val in formsvc\.prefill_values\(design, person\)\.items\(\):\s+if fields\[fid\]\.get\(\"readonly_when_prefilled\"\):\s+values\[fid\] = val", src)


def test_x4_certificates_single_message_and_no_contact_data():
    assert certificates_public.NOT_REQUESTED == certificates_public.NOT_FOUND
    src = _src("app/routers/certificates_public.py")
    body = src[src.index("def certificate_lookup"):src.index("def certificate_asset")]
    assert "user.phone" not in body and "user.email" not in body and "in_event" not in body


# ------------------------------- X5: rechazo sin fecha verificada no borra la foto
def test_x5_reject_purges_only_with_a_verified_birth_date():
    src = _src("app/routers/aceptar.py")
    branch = src[src.index('if decision == "reject"'):src.index('return {"status": "rejected"')]
    assert "if date_ok and not consent.has_any_acceptance" in branch


# ------------------------------- X6: tope de pagos pendientes por IP
def test_x6_hold_is_configurable_and_cap_is_configurable(monkeypatch):
    assert formsvc.PENDING_HOLD == timedelta(minutes=formsvc._hold_minutes())      # D2: 10 min por defecto, FORM_HOLD_MINUTES
    monkeypatch.delenv("FORM_PENDING_MAX_PER_IP", raising=False)
    monkeypatch.delenv("PUBLIC_LIMIT_FACTOR", raising=False)
    assert formsvc.pending_max_per_ip() == 3
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "0")
    assert formsvc.pending_max_per_ip() == 0
    monkeypatch.setenv("FORM_PENDING_MAX_PER_IP", "3")
    monkeypatch.setenv("PUBLIC_LIMIT_FACTOR", "10")
    assert formsvc.pending_max_per_ip() == 30


def test_x6_cap_is_checked_under_the_lock_and_marked_in_the_same_transaction():      # H2 (ronda de ataque 2): antes se leía sin candado
    src = _src("app/routers/forms_public.py")
    body = src[src.index("def _reserve_and_store"):src.index("def _widget_params")]
    assert body.index("formsvc.reserve_slot(") < body.rindex("formsvc.pending_from_ip(")
    assert body.index("formsvc.mark_pending_ip(") < body.index("db.commit()")


def test_x6_pending_from_ip_counts_only_live_pending_of_that_ip(client, factory, db):
    from app.models import FormSubmission, RateLimitEvent, WebForm
    ev = _event(client, factory)
    f = _create(client, ev)
    form = db.query(WebForm).filter_by(id=f["id"]).one()
    subs = []
    for i, status in enumerate([formsvc.PENDING, formsvc.PENDING, "confirmed", formsvc.PENDING]):
        s = FormSubmission(form_id=form.id, event_id=ev.id, data_json="{}", status=status, sid=f"s{i}", person_id=f"90{i}")
        db.add(s)
        db.flush()
        subs.append(s)
    for s in subs[:3]:
        formsvc.mark_pending_ip(db, form, s, "203.0.113.7")
    formsvc.mark_pending_ip(db, form, subs[3], "198.51.100.9")
    formsvc.mark_pending_ip(db, form, subs[3], None)                  # sin IP confiable no se anota nada
    db.commit()
    assert formsvc.pending_from_ip(db, form, "203.0.113.7") == 2      # la confirmada no cuenta
    assert formsvc.pending_from_ip(db, form, "203.0.113.7", sid="s0") == 1
    assert formsvc.pending_from_ip(db, form, "203.0.113.7", person_id="901") == 2      # R9: la cédula la escribe cualquiera, ya NO excluye (una IP no acumula pendientes con la de otra persona)
    assert formsvc.pending_from_ip(db, form, "198.51.100.9") == 1
    db.query(RateLimitEvent).filter_by(kind=formsvc.PENDING_IP_KIND).update({"created_at": utcnow() - formsvc.PENDING_HOLD - timedelta(minutes=1)})
    db.commit()
    assert formsvc.pending_from_ip(db, form, "203.0.113.7") == 0      # pasado PENDING_HOLD ya no aparta nada


# ------------------------------- X7: editor de escarapela
def test_x7_badge_editor_escapes_categories_and_static_text():
    html = _src("templates/badge_editor.html")
    assert "`<option value=\"${window.escapeHtml(c)}\">${window.escapeHtml(c)}</option>`" in html
    assert "<textarea id=\"p_content\" rows=\"2\">${window.escapeHtml(el.content || '')}</textarea>" in html
    assert ">${c}</option>" not in html and ">${el.content || ''}</textarea>" not in html


# ------------------------------- asteriscos configurables: las condiciones se resuelven con el valor real sin entregarlo
def test_mask_default_is_off_except_email_and_phone():
    design = {"fields": {
        "nom": {"type": "text_short", "key": "first_name", "readonly_when_prefilled": True},
        "mail": {"type": "email", "key": "email", "readonly_when_prefilled": True},
        "mail_open": {"type": "email", "key": "email", "readonly_when_prefilled": True, "mask_asterisks": False},
    }}
    person = {"first_name": "Ana María", "email": "ana@empresa.com"}
    prefill, _ = forms_public.public_prefill(design, person)
    assert prefill["nom"] == "Ana María" and prefill["mail"] != "ana@empresa.com" and prefill["mail_open"] == "ana@empresa.com"


def test_masked_field_conditions_are_frozen_with_the_real_value():
    design = {"fields": {
        "ciu": {"type": "text_short", "key": "city", "readonly_when_prefilled": True, "mask_asterisks": True},
        "txt": {"type": "paragraph", "content": "x", "show_if": {"match": "any", "rules": [{"field": "ciu", "op": "equals", "value": "Cali"}, {"field": "otro", "op": "filled"}]},
                "variants": {"content": {"items": [{"when": {"field": "ciu", "op": "equals", "value": "Bogotá"}, "value": "Hola"}]}}},
    }}
    person = {"city": "Cali"}
    prefill, _, hidden = forms_public._prefill_parts(design, person)
    assert prefill["ciu"] == "C***" and hidden == {"ciu": "Cali"}
    out = forms_public.formlib.freeze_conditions(design, hidden)
    assert out["fields"]["txt"]["show_if"]["rules"][0] == {"field": "ciu", "op": "filled"}          # «Cali» se cumple
    assert out["fields"]["txt"]["variants"]["content"]["items"][0]["when"] == {"field": "ciu", "op": "in", "value": []}      # «Bogotá» no
    assert out["fields"]["txt"]["show_if"]["rules"][1] == {"field": "otro", "op": "filled"}
    assert "Cali" not in json.dumps(out["fields"]["txt"])
    assert design["fields"]["txt"]["show_if"]["rules"][0]["value"] == "Cali"          # no muta el original


def test_sanitize_keeps_mask_asterisks_only_when_decided():
    base = {"type": "text_short", "label": "Nombre", "key": "first_name"}
    for given, want in ((True, True), (False, False)):
        d = forms_public.formlib.sanitize_design({"rows": [{"items": ["a"]}], "fields": {"a": {**base, "mask_asterisks": given}}}, set())
        assert d["fields"]["a"]["mask_asterisks"] is want
    d = forms_public.formlib.sanitize_design({"rows": [{"items": ["a"]}], "fields": {"a": base}}, set())
    assert "mask_asterisks" not in d["fields"]["a"]
