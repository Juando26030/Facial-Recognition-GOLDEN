"""Código del evento protegido (orden del 21-oct-2026): el código va en direcciones públicas (/aceptar/<código>, QR del cartel, enlaces personales enviados), así que
(1) no se cambia una vez creado, (2) /aceptar lo encuentra sin distinguir mayúsculas ni espacios al borde solo si es único, (3) los eventos NUEVOS usan un código
seguro para URL, (4) se ve claro en el menú del evento y (5) un enlace que ya no aplica muestra una página amable, igual para todos los casos."""
import inspect
import re

import pytest

from app import acceptlink
from app.models import Event, EventAttendee
from app.routers import aceptar as aceptar_router
from app.routers import events as events_router
from tests.conftest import login


@pytest.fixture()
def env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com",
                 "DOMAIN": "ejemplo.test", "PUBLIC_BASE_URL": "https://app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)


def _open_event(factory, db, code=None, **kw):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, **kw)
    if code is not None:
        ev.event_code = code
        db.commit()
    return ev


def _create(client, factory, code):
    factory.staff("admin", "root")
    coord = factory.staff("coordinador", "coord")
    factory.tenant("acme")
    login(client, "root")
    return client.post("/api/events", json={"tenant_id": "acme", "event_code": code, "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
                                           "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
                                           "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord.id, "commercial_staff_id": factory.staff("comercial").id})


# ---------------------------------------------------------------------------------------------------------------- 1) el código no se cambia
def test_the_event_code_cannot_be_changed_through_the_api_once_created(client, factory, db):
    factory.staff("super_admin", "su")
    ev = factory.event("creado")
    original = ev.event_code
    login(client, "su")
    r = client.patch(f"/api/events/{ev.id}", json={"event_code": "OTRO-CODIGO"})
    assert r.status_code == 400 and r.json()["detail"] == events_router.EVENT_CODE_LOCKED
    db.expire_all()
    assert db.get(Event, ev.id).event_code == original
    assert client.patch(f"/api/events/{ev.id}", json={"event_code": original, "name": "Renombrado"}).status_code == 200      # enviar el MISMO código no es cambiarlo
    db.expire_all()
    assert db.get(Event, ev.id).name == "Renombrado"


# ---------------------------------------------------------------------------------------------------------------- 3) códigos nuevos seguros para URL
@pytest.mark.parametrize("bad", ["FERIA 2026", "Feria-Ñandú", "a/b", "evento#1", "X 1", "café"])          # espacios por dentro: no (los de los bordes se quitan solos, ver abajo)
def test_new_events_need_a_url_safe_code_with_a_friendly_message(client, factory, db, bad):
    r = _create(client, factory, bad)
    assert r.status_code == 400 and r.json()["detail"] == events_router.EVENT_CODE_HELP and "Ejemplo: FERIA-2026" in r.json()["detail"]
    assert db.query(Event).filter(Event.name == "Nuevo").count() == 0


def test_spaces_around_the_code_are_trimmed(client, factory, db):
    """16-nov-2026: el código se limpia de espacios en los bordes (y vacío se propone el siguiente); « X1 » queda «X1»."""
    assert _create(client, factory, " X1 ").status_code == 200
    assert db.query(Event).filter(Event.name == "Nuevo").one().event_code == "X1"


@pytest.mark.parametrize("good", ["FERIA-2026", "8", "001", "congreso_oct.v2"])
def test_url_safe_and_numeric_only_codes_are_allowed(client, factory, db, good):
    assert _create(client, factory, good).status_code == 200


def test_a_new_code_that_only_differs_in_case_from_an_existing_one_is_rejected(client, factory, db):
    old = factory.event("creado")
    old.event_code = "FERIA-X"
    db.commit()
    r = _create(client, factory, "feria-x")
    assert r.status_code == 400 and "otras mayúsculas" in r.json()["detail"]


def test_existing_codes_are_not_rewritten(db, factory):
    ev = factory.event("creado")
    ev.event_code = "código viejo con espacios"                                                    # un código antiguo que hoy no sería válido
    db.commit()
    db.expire_all()
    assert db.get(Event, ev.id).event_code == "código viejo con espacios"


# ---------------------------------------------------------------------------------------------------------------- 2) /aceptar sin distinguir mayúsculas, nunca ambiguo
def test_aceptar_finds_the_code_exactly_first_then_case_and_space_insensitive_only_if_unique(client, factory, db, env):
    ev = _open_event(factory, db, "FERIA-X")
    assert ev.name in client.get("/aceptar/FERIA-X").text                                        # exacta
    for variant in ("feria-x", "Feria-X", "feria-x%20"):
        page = client.get(f"/aceptar/{variant}")
        assert page.status_code == 200 and ev.name in page.text, variant
    assert client.get("/api/aceptar/feria-x/text").status_code == 200                            # la API usa la misma búsqueda


def test_aceptar_never_picks_between_two_codes_that_only_differ_in_case(client, factory, db, env):
    upper = _open_event(factory, db, "AbC")
    lower = _open_event(factory, db, "abc")
    assert upper.name in client.get("/aceptar/AbC").text and lower.name in client.get("/aceptar/abc").text      # la exacta manda
    amb = client.get("/aceptar/ABC")                                                             # sin exacta y con dos candidatas: no se elige
    assert amb.status_code == 404 and upper.name not in amb.text and lower.name not in amb.text


def test_the_links_already_emitted_do_not_change(client, factory, db, env):
    ev = _open_event(factory, db, "FERIA-X")
    factory.person(ev, "1001")
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = acceptlink.issue(db, att, trusted=True)
    db.commit()
    assert acceptlink.url(ev, token) == f"https://app.ejemplo.test/aceptar/FERIA-X/{token}"         # el enlace sigue llevando el código tal cual
    assert client.get(f"/aceptar/FERIA-X/{token}").status_code == 200


# ---------------------------------------------------------------------------------------------------------------- 5) página amable
def _norm(html):
    return re.sub(r"\s+", " ", html)


def test_a_link_that_no_longer_applies_shows_a_friendly_page_without_any_data(client, factory, db, env):
    closed = _open_event(factory, db, "CERRADO-1")
    closed.status = "finalizado"
    db.commit()
    live = _open_event(factory, db, "VIVO-1")
    pages = {"evento cerrado": client.get("/aceptar/CERRADO-1"), "enlace de evento cerrado": client.get("/aceptar/CERRADO-1/tok123"),
             "código inexistente": client.get("/aceptar/NO-EXISTE"), "token inexistente": client.get("/aceptar/VIVO-1/token-que-no-existe")}
    bodies = set()
    for case, r in pages.items():
        assert r.status_code == 404 and r.headers["content-type"].startswith("text/html"), case
        html = r.text
        assert '{"detail"' not in html, case
        assert aceptar_router.UNAVAILABLE_TITLE in html and aceptar_router.UNAVAILABLE_TEXT in html and "Si tienes dudas, escríbenos a" in html, case
        assert 'href="mailto:soporteit@goldenlogisticas.com"' in html and "css/agrandir.css" in html and "<img" in html, case
        assert closed.name not in html and live.name not in html and "CERRADO-1" not in html and "VIVO-1" not in html, case      # ningún dato del evento
        bodies.add(_norm(html))
    assert len(bodies) == 1                                                                      # la misma página en todos los casos: no revela nada
    assert client.get("/api/aceptar/CERRADO-1/text").json() == {"detail": "Esta página no está disponible"}      # la API (la usa el JavaScript) sigue igual


def test_the_already_accepted_status_page_is_unchanged():
    """Quien ya aceptó y abre su enlace (evento vigente) sigue viendo su estado, como hasta hoy: no se cambia el flujo de autorización."""
    src = inspect.getsource(aceptar_router.personal_page)
    assert 'already=done["message"]' in src and "_unavailable(request)" in src


# ---------------------------------------------------------------------------------------------------------------- 4) el código en el menú
def test_the_event_menu_shows_the_code_clearly(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}").text
    assert f'id="eventCodeLine">Código del evento: <strong>{ev.event_code}</strong>' in page


def test_the_new_event_form_guides_the_code_format():
    """Fase 2: el formulario sale de la plantilla de evento; la guía del código (formato y que no se cambia) viene en su ayuda y el formato se revisa en el navegador (y siempre en el servidor)."""
    from app import event_template as et
    code = [f for f in et.default_template()["fields"] if f["key"] == "event_code"][0]
    assert "no se puede cambiar después" in code["help"] and "FERIA-2026" in code["help"]
    js = open("static/js/nuevo-evento.js", encoding="utf-8").read()
    assert "const CODE_RE = /^[A-Za-z0-9._-]+$/;" in js
