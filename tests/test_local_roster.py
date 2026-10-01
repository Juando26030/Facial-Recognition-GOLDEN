"""Fase 3, commit 1: roster local del quiosco (`GET /api/events/{id}/local-roster`): contenido mínimo (sin fotos, encodings, teléfono ni correo), permisos por evento, límite de tasa,
ETag, evento finalizado y un evento de ~8.000 personas (tamaño y tiempo)."""
import gzip
import hashlib
import json
import time

from app.models import AccessLog, EventAttendee, User
from app.routers import api
from tests.conftest import login


def _get(client, ev, **kw):
    return client.get(f"/api/events/{ev.id}/local-roster", **kw)


def _fp(salt, cedula):
    return hashlib.sha256(f"{salt}:{cedula}".encode()).hexdigest()[:16]


def test_roster_has_only_the_minimum_and_a_salted_fingerprint(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    u = factory.person(ev, "1001.234", "Ana", "Prueba")
    u.phone, u.email, u.opt_1, u.face_encoding = "3001112233", "ana@example.com", "VIP", json.dumps([0.1] * 128)
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=u.id).one()
    att.set_categories(["Prensa", "Staff"])
    factory.person(ev, "2002", "Luis", "Gómez")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="2002", event_id=ev.id, record_type="Existente"))
    db.commit()
    login(client, "root")
    r = _get(client, ev)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"v", "generated_at", "max_age_s", "event", "salt", "count", "people"} and body["count"] == 2 and body["max_age_s"] == 86400
    assert body["event"] == {"id": ev.id, "status": "en_proceso"}
    by_name = {p["n"]: p for p in body["people"]}
    ana, luis = by_name["Ana Prueba"], by_name["Luis Gómez"]
    assert set(ana) == {"h", "n", "c", "s"}                                              # nada más: ni cédula, ni teléfono, ni correo, ni encoding
    assert ana["h"] == _fp(body["salt"], "1001234")                                      # normalizada: sin puntos ni espacios (igual que el cliente)
    assert ana["c"] == ["Prensa", "Staff"] and ana["s"] == "No registrado" and luis["s"] == "Registrado"
    for secret in ("1001", "2002", "3001112233", "ana@example.com", "VIP", "0.1"):
        assert secret not in r.text, secret
    other = factory.event("en_proceso")
    login(client, "root")
    assert _get(client, other).json()["salt"] != body["salt"]                            # sal distinta por evento
    assert _get(client, ev).json()["salt"] == body["salt"]                               # y estable


def test_roster_permissions_per_event(client, factory):
    factory.staff("admin", "root")
    dig_ok, cli = factory.staff("digitador", "dig_ok"), factory.staff("cliente", "cli")
    factory.staff("digitador", "dig_other")
    ev = factory.event("en_proceso")
    factory.authorize(ev, dig_ok)
    factory.authorize(ev, cli)
    assert _get(client, ev).status_code in (401, 403)                                    # sin sesión
    login(client, "dig_other")
    assert _get(client, ev).status_code == 403                                           # digitador sin autorización para ESTE evento
    login(client, "cli")
    assert _get(client, ev).status_code == 403                                           # el cliente puede ver, no acreditar: tampoco descarga el roster
    login(client, "dig_ok")
    assert _get(client, ev).status_code == 200


def test_roster_is_refused_for_a_finished_event(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("finalizado")
    login(client, "root")
    assert _get(client, ev).status_code == 409


def test_roster_etag_returns_304_and_changes_with_the_directory(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "root")
    first = _get(client, ev)
    etag = first.headers["etag"]
    assert _get(client, ev, headers={"If-None-Match": etag}).status_code == 304
    factory.person(ev, "1002")
    again = _get(client, ev, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.json()["count"] == 2 and again.headers["etag"] != etag


def test_roster_download_is_rate_limited_per_user_and_event(client, factory, monkeypatch):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "root")
    monkeypatch.setattr(api, "ROSTER_LIMIT", 3)
    assert [_get(client, ev).status_code for _ in range(3)] == [200, 200, 200]
    assert _get(client, ev).status_code == 429
    other = factory.event("en_proceso")
    login(client, "root")
    assert _get(client, other).status_code == 200                                        # el límite es por evento


def test_roster_of_8000_people_is_small_and_fast(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    n = 8000
    users = [User(id=f"{1000000000 + i}", tenant_id=ev.tenant_id, first_name=f"Nombre{i}", last_name=f"Apellido{i}", phone="3001234567", email=f"p{i}@example.com", entity="Entidad de prueba S.A.S.")
             for i in range(n)]
    db.bulk_save_objects(users)
    db.commit()
    db.bulk_save_objects([EventAttendee(event_id=ev.id, user_id=u.id, tenant_id=ev.tenant_id, categories=json.dumps(["General"])) for u in users])
    db.add_all([AccessLog(tenant_id=ev.tenant_id, user_id=users[i].id, event_id=ev.id, record_type="Existente") for i in range(0, n, 4)])
    db.commit()
    login(client, "root")
    t = time.perf_counter()
    r = _get(client, ev)
    elapsed = time.perf_counter() - t
    body = r.json()
    raw, zipped = len(r.content), len(gzip.compress(r.content))
    registered = sum(p["s"] == "Registrado" for p in body["people"])
    print(f"roster 8000: {raw / 1024:.0f} KB sin comprimir, {zipped / 1024:.0f} KB gzip, {elapsed * 1000:.0f} ms")
    assert body["count"] == n and registered == n // 4
    assert len({p["h"] for p in body["people"]}) == n                                    # sin colisiones de huella
    assert raw < 1_500_000 and zipped < 500_000
    assert elapsed < 5.0


def test_registration_page_loads_the_contingency_client_before_directory_js():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "templates" / "kiosk_registro.html").read_text(encoding="utf8")
    assert html.index("js/contingency.js") < html.index("js/directory.js")
    assert "GoldenContingency.init({ eventId: window.EVENT_ID })" in html and "canAccredit && window.GoldenContingency" in html
