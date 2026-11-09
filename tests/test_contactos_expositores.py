"""Captura de contactos para expositores (Fase 8, pieza 6): la persona decide, el expositor solo ve a quien comparte, la tarjeta .vcf."""
import datetime

from app import contacts
from app.models import AuditContactShare, ExhibitorLead, User
from tests.conftest import login


# ------------------------------------------------------------------ vCard y lectura del QR (puras)
def test_vcard_drops_unicode_line_breaks_and_control_chars():
    """F5-9 B: un nombre con NEL, separadores de línea Unicode o \r no puede inyectar una línea nueva (p. ej. un EMAIL o URL falsos) en la tarjeta."""
    v = contacts.vcard("Ana\u2028EMAIL:x@evil.com", "Mora\x85URL:http://evil", "Acme\r\nTEL:1", "", "", "")
    lines = v.split("\r\n")
    assert not any(l.startswith(("EMAIL", "URL", "TEL")) for l in lines)
    assert "\u2028" not in v and "\x85" not in v


def test_vcard_escapes_and_has_required_lines():
    v = contacts.vcard("Ana;María", "Pérez, Díaz", "Acme\nSAS", "Gerente", "+573001112233", "ana@example.com", "Feria")
    assert v.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n") and v.rstrip().endswith("END:VCARD")
    assert r"N:Pérez\, Díaz;Ana\;María;;;" in v and "ORG:Acme\\nSAS" in v and "TEL" in v and "EMAIL" in v
    assert all(len(line.encode()) <= 75 for line in v.split("\r\n"))


def test_parse_scanned_card_url_and_cedula():
    assert contacts.parse_scanned("https://app.golden-eventos.com/tarjeta/" + "a" * 30) == {"kind": "card", "token": "a" * 30}
    assert contacts.parse_scanned("1.234.567")["cedula"] == "1234567"
    assert contacts.parse_scanned("1234567|Ana|Mora")["cedula"] == "1234567"
    assert contacts.parse_scanned("")["kind"] == "none"


# ------------------------------------------------------------------ flujo completo
def _setup(client, factory, db):
    factory.staff("coordinador", "coord8")
    ev = factory.event("en_proceso")
    login(client, "coord8")
    factory.person(ev, "1001", "Ana", "Mora")
    ex = client.post(f"/api/events/{ev.id}/exhibitors", json={"name": "Stand Uno", "email": "stand@example.com"}).json()
    card = contacts.person_card(db, ev, "1001")
    db.commit()
    client.post("/logout")
    return ev, ex, card


def _share(client, card, accept=True):
    return client.post(f"/contacto/{card.token}/share", json={"accept": accept, "adult": True})


def test_nothing_is_shared_by_default(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    assert client.get(f"/tarjeta/{card.share_token}/vcard").status_code == 404
    assert client.get(f"/tarjeta/{card.share_token}/data").status_code == 404
    r = client.post(f"{ex['private_path']}/scan", json={"text": "1001"})
    assert r.json()["status"] == "not_sharing"
    assert client.get(f"{ex['private_path']}/data").json()["count"] == 0


def test_accept_then_exhibitor_scans_and_downloads(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    assert _share(client, card).json() == {"sharing": True}
    row = db.query(AuditContactShare).one()
    assert row.shared and row.reason == "consent" and row.cedula_hash and row.text_hash == contacts.text_hash()
    v = client.get(f"/tarjeta/{card.share_token}/vcard")
    assert v.status_code == 200 and v.headers["content-type"].startswith("text/vcard") and "FN:Ana Mora" in v.text
    r = client.post(f"{ex['private_path']}/scan", json={"text": f"https://x.test/tarjeta/{card.share_token}"}).json()
    assert r["status"] == "new" and r["person"]["first_name"] == "Ana"
    assert client.post(f"{ex['private_path']}/scan", json={"text": "1001"}).json()["status"] == "known"
    d = client.get(f"{ex['private_path']}/data").json()
    assert d["count"] == 1 and d["leads"][0]["card"] == card.share_token
    assert client.get(f"{ex['private_path']}/vcard/{card.share_token}").status_code == 200
    x = client.get(f"{ex['private_path']}/leads.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_revoking_hides_everything_immediately(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    _share(client, card)
    client.post(f"{ex['private_path']}/scan", json={"text": "1001"})
    assert _share(client, card, accept=False).json() == {"sharing": False}
    assert client.get(f"{ex['private_path']}/data").json()["count"] == 0
    assert client.get(f"/tarjeta/{card.share_token}/vcard").status_code == 404
    assert client.get(f"{ex['private_path']}/vcard/{card.share_token}").status_code == 404
    assert db.query(AuditContactShare).count() == 2          # la constancia no se borra: solo se agrega


def test_minor_cannot_share(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    db.query(User).filter_by(id="1001").update({"birth_date": datetime.date.today().replace(year=datetime.date.today().year - 10)})
    db.commit()
    assert _share(client, card).status_code == 400
    assert db.query(AuditContactShare).count() == 0


def test_adult_confirmation_required_when_birth_date_unknown(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    r = client.post(f"/contacto/{card.token}/share", json={"accept": True, "adult": False})
    assert r.status_code == 400


def test_unknown_person_and_not_sharing_look_identical(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    a = client.post(f"{ex['private_path']}/scan", json={"text": "1001"}).json()
    b = client.post(f"{ex['private_path']}/scan", json={"text": "999999"}).json()
    assert a == b


def test_exhibitor_does_not_see_other_events(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    other = factory.event("en_proceso")
    factory.person(other, "2002")
    other_card = contacts.person_card(db, other, "2002")
    db.commit()
    client.post(f"/contacto/{other_card.token}/share", json={"accept": True, "adult": True})
    r = client.post(f"{ex['private_path']}/scan", json={"text": f"/tarjeta/{other_card.share_token}"}).json()
    assert r["status"] == "not_sharing"
    assert db.query(ExhibitorLead).count() == 0


def test_scan_rate_limit(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    codes = [client.post(f"{ex['private_path']}/scan", json={"text": "5555"}).status_code for _ in range(contacts.EXHIBITOR_MAX_SCANS[0] + 3)]
    assert 429 in codes


# ------------------------------------------------------------------ enlaces del expositor y del personal
def test_exhibitor_card_and_rotation_and_pause(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    assert "text/vcard" in client.get(f"{ex['card_path']}/vcard").headers["content-type"]
    login(client, "coord8")
    new = client.post(f"/api/events/{ev.id}/exhibitors/{ex['id']}/rotate").json()
    assert new["private_path"] != ex["private_path"]
    client.post("/logout")
    assert client.get(f"{ex['private_path']}/data").status_code == 404
    assert client.get(f"{ex['card_path']}/vcard").status_code == 404
    login(client, "coord8")
    client.patch(f"/api/events/{ev.id}/exhibitors/{ex['id']}", json={"active": False})
    client.post("/logout")
    assert client.get(f"{new['private_path']}/data").status_code == 404


def test_staff_api_needs_coordinator(client, factory, db):
    dig = factory.staff("digitador", "dig8")
    ev = factory.event("en_proceso")
    factory.authorize(ev, dig)
    login(client, "dig8")
    assert client.get(f"/api/events/{ev.id}/exhibitors").status_code == 403
    assert client.post(f"/api/events/{ev.id}/exhibitors", json={"name": "X"}).status_code == 403


def test_pages_are_public_no_store_and_unknown_token_404(client, factory, db):
    ev, ex, card = _setup(client, factory, db)
    for path in (f"/contacto/{card.token}", ex["private_path"]):
        r = client.get(path)
        assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    assert client.get("/contacto/nope").status_code == 404
    assert client.get("/expositor/nope").status_code == 404
    assert client.get("/tarjeta/nope").status_code == 404


def test_digital_badge_links_to_contact_page(client, factory, db):
    ev = factory.event("en_proceso", digital_badge_enabled=True)
    factory.person(ev, "1001")
    from app.models import EventAttendee
    att = db.query(EventAttendee).filter_by(user_id="1001").one()
    att.digital_token = "t" * 32
    db.commit()
    r = client.get("/b/" + "t" * 32 + "/contact", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/contacto/")
