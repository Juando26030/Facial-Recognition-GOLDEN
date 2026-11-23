"""A1: componente de cámara compartido en /aceptar, estilo y logo de la app, textos fijos de la auditora y el interruptor de la foto biométrica en la escarapela."""
import io
from datetime import date

from PIL import Image

from app import acceptlink, digital_badge, legal_texts
from app.models import EventAttendee
from app.storage import get_storage, photo_key
from tests.conftest import login

VOLUNTARY = "Este proceso es 100% voluntario. Si no deseas usar tu rostro, puedes ingresar con tu cédula o QR"
OPERATOR = "Tecnología biométrica y tratamiento de datos operados por Golden Eventos y Logística S.A.S."
CAMERA_NOTE = "Solo guardamos la foto final que decidas enviar. No grabamos video ni almacenamos tus intentos."


def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "JPEG")
    return buf.getvalue()


def _event(factory, db, **kw):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, start_date=date(2026, 10, 29), **kw)
    u = factory.person(ev, "1001", "Ana", "Mora", registered=True)
    u.birth_date = date(1990, 4, 2)
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = acceptlink.issue(db, att, True)
    db.commit()
    return ev, att, token


# ------------------------------------------------------------------------------------------------------------------------------------ /aceptar
def test_the_accept_page_has_the_three_fixed_texts_and_the_shared_camera(client, factory, db):
    ev, _att, token = _event(factory, db)
    html = client.get(f"/aceptar/{ev.event_code}/{token}").text
    assert VOLUNTARY in html and OPERATOR in html
    assert html.index(VOLUNTARY) < html.index('id="yes"') < html.index(OPERATOR)                          # encima y debajo del botón de aceptar
    assert "js/photo-capture.js" in html and 'id="selfieBox"' in html and "Agrandir" in html
    js = open("static/js/photo-capture.js", encoding="utf-8").read()
    assert CAMERA_NOTE in js and "ALLOW_AFTER_FAILS = 2" in js and "getUserMedia" in js and 'type: \'file\'' in js and "Usar esta foto" in js and "Repetir" in js


def test_the_fixed_texts_do_not_touch_the_legal_text_or_its_hash(factory, db):
    ev, _att, _token = _event(factory, db)
    t = legal_texts.render(ev, web=True)
    body = " ".join(t["body"])
    assert VOLUNTARY not in body and OPERATOR not in body and CAMERA_NOTE not in body
    assert t["hash"] == legal_texts.render(ev, web=True)["hash"]


def test_the_page_shows_the_golden_logo_or_the_events_own(client, factory, db):
    ev, _att, token = _event(factory, db)
    html = client.get(f"/aceptar/{ev.event_code}").text
    assert "logo" in html.lower() and f"/api/aceptar/{ev.event_code}/logo" not in html                    # sin logo propio: el de Golden
    assert client.get(f"/api/aceptar/{ev.event_code}/logo").status_code == 404
    key = f"{ev.tenant_id}/event_logos/{ev.id}.png"
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), (200, 10, 10)).save(buf, "PNG")
    get_storage().put(key, buf.getvalue())
    ev.logo_mode, ev.logo_path = "custom", key
    db.commit()
    assert f"/api/aceptar/{ev.event_code}/logo" in client.get(f"/aceptar/{ev.event_code}/{token}").text
    logo = client.get(f"/api/aceptar/{ev.event_code}/logo")
    assert logo.status_code == 200 and logo.content == buf.getvalue()                                     # sin sesión (página pública)
    ev.aceptar_enabled = False
    db.commit()
    assert client.get(f"/api/aceptar/{ev.event_code}/logo").status_code == 404                            # solo mientras la página esté disponible


# ------------------------------------------------------------------------------------------------------------------------------------ foto biométrica en la escarapela
def test_the_biometric_photo_is_not_printed_unless_a_super_admin_allows_it(client, factory, db):
    ev, att, _token = _event(factory, db)
    get_storage().put(photo_key(ev.tenant_id, "1001"), _jpg())
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    data = client.get(f"/api/users/1001/badge-print-data?event_id={ev.id}").json()
    assert data["has_photo"] is False                                                                      # apagado por defecto: recuadro vacío
    assert client.get(f"/api/users/1001/photo?event_id={ev.id}").status_code == 404
    assert client.put(f"/api/events/{ev.id}/badge-bio-photo", json={"enabled": True}).status_code == 403    # un coordinador no puede encenderlo
    client.cookies.clear()
    factory.staff("super_admin", "super1")
    login(client, "super1")
    assert client.put(f"/api/events/{ev.id}/badge-bio-photo", json={"enabled": True}).json() == {"badge_bio_photo_allowed": True}
    assert client.get(f"/api/users/1001/badge-print-data?event_id={ev.id}").json()["has_photo"] is True
    assert client.get(f"/api/users/1001/photo?event_id={ev.id}").status_code == 200
    assert 'id="badgeBioPhoto"' in client.get(f"/kiosk/{ev.id}/parametros").text


def test_the_digital_badge_also_hides_the_biometric_photo_while_the_switch_is_off(client, factory, db):
    ev, att, _token = _event(factory, db, digital_badge_enabled=True)
    get_storage().put(photo_key(ev.tenant_id, "1001"), _jpg())
    tok = digital_badge.ensure_token(db, att)
    db.commit()
    assert client.get(f"/b/{tok}/data").json()["person"]["has_photo"] is False
    assert client.get(f"/b/{tok}/photo").status_code == 404
    ev.badge_bio_photo_allowed = True
    db.commit()
    assert client.get(f"/b/{tok}/data").json()["person"]["has_photo"] is True
    assert client.get(f"/b/{tok}/photo").status_code == 200
