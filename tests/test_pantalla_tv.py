"""Fase 8 (1): pantalla de ingreso para TV con el enlace de solo lectura de las estadísticas del evento (y la sesión del personal)."""
import re

from app import tv_screen
from app.models import AccessLog
from app.timeutil import utcnow
from tests.conftest import login

TOKEN = re.compile(r"/ver/(?:e|tv)/([A-Za-z0-9_\-]+)$")


def test_short_name_hides_the_full_last_name():
    assert tv_screen.short_name("Juan", "Pérez Gómez") == "Juan P."
    assert tv_screen.short_name("  Ana ", "") == "Ana"
    assert tv_screen.short_name(None, None) == "Asistente"


def _log(db, ev, uid, record_type="Existente"):
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, timestamp=utcnow(), record_type=record_type, event_id=ev.id))
    db.commit()


def _setup(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    for uid, first, last in (("2001", "Ana", "Rojas"), ("2002", "Luis", "Mora"), ("2003", "Eva", "Paz")):
        factory.person(ev, uid, first_name=first, last_name=last)
    factory.person(ev, "PRUEBA", first_name="Prueba", last_name="Test")
    _log(db, ev, "2001")
    _log(db, ev, "2002")
    _log(db, ev, "2002", "Actualizado")           # una edición de perfil no es un ingreso
    _log(db, ev, "PRUEBA")                        # la persona de prueba no cuenta
    login(client, "coord1")
    return ev


def test_snapshot_counts_only_real_entries_and_hides_the_id(client, factory, db):
    ev = _setup(client, factory, db)
    tv_screen._cache._data.clear()
    snap = tv_screen.compute(db, ev)
    assert snap["registered"] == 2 and snap["expected"] == 3 and snap["percent"] == 67
    names = [r["name"] for r in snap["recent"]]
    assert sorted(names) == ["Ana R.", "Luis M."] and len(names) == len(set(names))
    assert "2001" not in str(snap) and "Prueba" not in str(snap)


def test_staff_api_and_page(client, factory, db):
    ev = _setup(client, factory, db)
    r = client.get(f"/api/events/{ev.id}/tv")
    assert r.status_code == 200 and r.json()["registered"] == 2 and r.headers["cache-control"] == "no-store"
    page = client.get(f"/kiosk/{ev.id}/tv")
    assert page.status_code == 200 and f"/api/events/{ev.id}/tv" in page.text and "tv-screen.js" in page.text


def test_digitador_cannot_open_the_staff_tv_data(client, factory, db):
    ev = _setup(client, factory, db)
    factory.staff("digitador", "dig1")
    factory.authorize(ev, factory.staff("digitador", "dig2"))
    client.post("/logout")
    login(client, "dig2")
    assert client.get(f"/api/events/{ev.id}/tv").status_code == 403


def test_public_tv_with_the_read_only_link(client, factory, db):
    ev = _setup(client, factory, db)
    made = client.post(f"/api/events/{ev.id}/stats-links", json={"scope": "event"}).json()
    assert "/ver/tv/" in made["tv_url"] and "/ver/e/" in made["url"]
    token = TOKEN.search(made["tv_url"]).group(1)
    client.post("/logout")
    client.cookies.clear()
    page = client.get(f"/ver/tv/{token}")
    assert page.status_code == 200 and f"/api/ver/{token}/tv" in page.text and page.headers["cache-control"] == "no-store"
    data = client.get(f"/api/ver/{token}/tv")
    assert data.status_code == 200 and data.json()["registered"] == 2
    assert client.get("/ver/tv/token-que-no-existe-12345678901234567890").status_code == 404
    assert client.get("/api/ver/token-que-no-existe-12345678901234567890/tv").status_code == 404


def test_form_scope_link_does_not_open_the_tv(client, factory, db):
    ev = _setup(client, factory, db)
    made = client.post(f"/api/events/{ev.id}/stats-links", json={"scope": "event"}).json()
    assert made["tv_url"]
    token = TOKEN.search(made["tv_url"]).group(1)
    client.post("/logout")
    client.cookies.clear()
    assert client.get(f"/api/ver/{token}/stats/variables").status_code == 200       # el mismo enlace de solo lectura sigue sirviendo a las estadísticas
    assert client.get(f"/api/ver/{token}/logo").status_code == 404                  # sin logo propio no hay nada que servir
