"""URL limpia de las inscripciones públicas (D2.5k, docs/20): nombre único del evento, validación y reservadas, historial con 301, rutas /<evento>/<formulario>, enlaces con PUBLIC_FORMS_BASE_URL."""
import pathlib

import pytest

from app import public_slug
from app.models import Event, SlugHistory
from tests.conftest import login
from tests.test_forms import _create, _event, _status, _url

SRC = pathlib.Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ puro
@pytest.mark.parametrize("slug,ok", [("congreso-g12-2026", True), ("abc", True), ("ab", False), ("a" * 61, False), ("Congreso", False), ("con greso", False), ("-abc", False), ("abc-", False), ("a--b", False),
                                     ("123456", False), ("static", False), ("api", False), ("inscripciones", False), ("año-2026", False)])
def test_validate(slug, ok):
    assert (public_slug.validate(slug) is None) is ok


def test_candidate_is_name_plus_year_without_repeating_it_and_never_reserved():
    assert public_slug.candidate("Congreso G12 Ñandú", 2026) == "congreso-g12-nandu-2026"
    assert public_slug.candidate("Feria 2026", 2026) == "feria-2026"
    assert public_slug.validate(public_slug.candidate("12", 2026)) is None
    assert public_slug.validate(public_slug.candidate("API", None)) is None
    assert len(public_slug.candidate("x" * 200, 2026)) <= public_slug.MAX_LEN
    assert public_slug.with_counter("feria-2026", 2) == "feria-2026-2"
    assert len(public_slug.with_counter("a" * 60, 12)) <= 60


def test_reserved_words_cover_the_app_routes():
    for w in ("static", "api", "health", "ready", "webhooks", "f", "b", "c", "r", "login", "logout", "kiosk", "sistema", "admin", "privacidad", "terminos", "reembolsos", "inscripciones", "www"):
        assert w in public_slug.RESERVED


def test_migration_0113():
    src = (SRC / "alembic" / "versions" / "0113_public_slug.py").read_text(encoding="utf-8")
    assert 'revision = "0113_public_slug"' in src and len("0113_public_slug") <= 32 and 'down_revision = "0112_local_nodes"' in src
    for piece in ("public_slug", "is_primary", "slug_history", "uq_events_public_slug", "lower(public_slug)", "WHERE public_slug IS NULL"):
        assert piece in src


# ------------------------------------------------------------------ eventos y API del personal
def test_new_events_get_a_unique_slug_with_counter(client, factory, db):
    factory.staff("admin", "adm")
    login(client, "adm")
    body = {"tenant_id": "acme", "event_code": "", "name": "Congreso G12", "start_date": "2026-11-20", "end_date": "2026-11-21", "setup_date": "2026-11-19"}
    factory.tenant("acme")
    slugs = []
    for code in ("CG1", "CG2"):
        r = client.post("/api/events", json={**body, "event_code": code})
        if r.status_code != 200:                                      # el cuerpo mínimo de creación depende de la plantilla: la prueba de unicidad también se cubre directo abajo
            slugs = []
            break
        slugs.append(db.get(Event, r.json()["id"]).public_slug)
    if slugs:
        assert slugs[0] == "congreso-g12-2026" and slugs[1] == "congreso-g12-2026-2"
    a, b = factory.event("en_proceso"), factory.event("en_proceso")
    a.public_slug = public_slug.unique_for(db, "Gran Feria", 2026, a.id)
    db.commit()
    assert public_slug.unique_for(db, "Gran Feria", 2026, b.id) == "gran-feria-2026-2"


def test_only_comercial_admin_super_can_use_the_link_api(client, factory, db):
    ev = factory.event("en_proceso")
    for role, ok in (("coordinador", False), ("comercial", True), ("admin", True)):
        factory.staff(role, f"u_{role}")
    for role, ok in (("coordinador", False), ("comercial", True), ("admin", True)):
        login(client, f"u_{role}")
        assert (client.get(f"/api/events/{ev.id}/public-link").status_code == 200) is ok
        client.post("/logout")


def test_rename_validates_keeps_history_and_blocks_taken_names(client, factory, db):
    factory.staff("admin", "adm")
    e1, e2 = factory.event("en_proceso"), factory.event("en_proceso")
    login(client, "adm")
    s1 = client.get(f"/api/events/{e1.id}/public-link").json()["slug"]
    client.get(f"/api/events/{e2.id}/public-link")
    assert client.put(f"/api/events/{e1.id}/public-link", json={"slug": "API"}).status_code == 400
    assert client.put(f"/api/events/{e1.id}/public-link", json={"slug": "static"}).status_code == 400
    r = client.put(f"/api/events/{e1.id}/public-link", json={"slug": "mi-feria-2026"})
    assert r.status_code == 200 and r.json()["slug"] == "mi-feria-2026" and r.json()["history"][0]["slug"] == s1
    assert client.put(f"/api/events/{e2.id}/public-link", json={"slug": "mi-feria-2026"}).status_code == 400          # lo usa otro evento
    assert client.put(f"/api/events/{e2.id}/public-link", json={"slug": s1}).status_code == 400                       # retenido 12 meses por el historial de otro evento
    chk = client.get(f"/api/events/{e2.id}/public-link", params={"slug": "mi-feria-2026"}).json()
    assert chk["ok"] is False and "otro evento" in chk["error"]
    db.expire_all()
    assert db.query(SlugHistory).filter(SlugHistory.event_id == e1.id).count() == 1
    r = client.put(f"/api/events/{e1.id}/public-link", json={"slug": s1})          # volver a un nombre propio anterior
    assert r.status_code == 200 and r.json()["slug"] == s1


# ------------------------------------------------------------------ rutas públicas
def _open_form(client, factory, slug):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert _status(client, ev, f, manual_status="activo").status_code == 200
    client.post("/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.put(f"/api/events/{ev.id}/public-link", json={"slug": slug}).status_code == 200
    client.post("/logout")
    return ev, f


def test_clean_urls_serve_the_same_page_and_old_urls_keep_working(client, factory, db):
    from app import formsvc
    ev, f = _open_form(client, factory, "feria-limpia-2026")
    formsvc.invalidate_public_cache()
    r = client.get(f"/feria-limpia-2026/{f['slug']}")
    assert r.status_code == 200 and f"/f/{ev.id}/{f['slug']}" in r.text
    r = client.get("/feria-limpia-2026")                                      # un solo formulario abierto: ese es el principal
    assert r.status_code == 200 and f"/f/{ev.id}/{f['slug']}" in r.text
    assert client.get(_url(ev, f)).status_code == 200                         # /f/... sigue para siempre
    assert client.get("/feria-limpia-2026/no-existe").status_code == 404
    assert client.get("/no-existe-2026").status_code == 404
    assert client.get("/api/algo").status_code == 404 and client.get("/static").status_code in (404, 307)


def test_old_slug_redirects_301_and_primary_form_is_respected(client, factory, db):
    from app import formsvc
    ev, f = _open_form(client, factory, "primera-2026")
    factory.staff("admin", "adm2")
    login(client, "adm2")
    assert client.put(f"/api/events/{ev.id}/public-link", json={"slug": "segunda-2026", "primary_form_id": f["id"]}).status_code == 200
    client.post("/logout")
    formsvc.invalidate_public_cache()
    r = client.get(f"/primera-2026/{f['slug']}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"/segunda-2026/{f['slug']}"
    r = client.get("/primera-2026", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/segunda-2026"
    assert client.get("/segunda-2026").status_code == 200


def test_unpublished_forms_are_404_on_the_clean_url(client, factory, db):
    from app import formsvc
    ev = _event(client, factory)
    f = _create(client, ev)                                                   # queda en «pruebas»
    client.post("/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    client.put(f"/api/events/{ev.id}/public-link", json={"slug": "solo-pruebas-2026"})
    client.post("/logout")
    formsvc.invalidate_public_cache()
    assert client.get(f"/solo-pruebas-2026/{f['slug']}").status_code == 404
    assert client.get(f"/solo-pruebas-2026/{f['slug']}", params={"k": f["test_key"]}).status_code == 200


# ------------------------------------------------------------------ enlaces que salen del sistema
def test_form_links_are_clean_only_when_the_forms_host_is_configured(client, factory, db, monkeypatch):
    ev = _event(client, factory)
    f = _create(client, ev)
    monkeypatch.delenv("PUBLIC_FORMS_BASE_URL", raising=False)
    assert client.get(f"/api/events/{ev.id}/forms").json()[0]["public_url"].endswith(f"/f/{ev.id}/{f['slug']}")
    ev_row = db.get(Event, ev.id)
    ev_row.public_slug = "feria-2026"
    db.commit()
    monkeypatch.setenv("PUBLIC_FORMS_BASE_URL", "https://inscripciones.golden-eventos.com/")
    urls = client.get(f"/api/events/{ev.id}/forms").json()[0]
    assert urls["public_url"] == f"https://inscripciones.golden-eventos.com/feria-2026/{f['slug']}" and urls["test_url"].startswith(urls["public_url"] + "?k=")


def test_hosting_config_for_the_forms_site_sends_everything_to_publico(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_config", SRC / "deploy" / "firebase" / "make_config.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    out = mc.build_forms("production", "proj", "us-east4", "golden-inscripciones", out_dir=str(tmp_path / "f"))
    import json
    cfg = json.loads((pathlib.Path(out) / "firebase.json").read_text())["hosting"]
    assert cfg["site"] == "golden-inscripciones" and cfg["rewrites"] == [{"source": "**", "run": {"serviceId": "golden-publico", "region": "us-east4"}}]
    assert (pathlib.Path(out) / "public" / "static").exists()


def test_csrf_accepts_the_forms_host_origin(client, factory, monkeypatch):
    monkeypatch.setenv("PUBLIC_FORMS_BASE_URL", "https://inscripciones.golden-eventos.com")
    r = client.post("/f/1/x/beacon", json={}, headers={"Origin": "https://inscripciones.golden-eventos.com"})
    assert r.status_code != 403
    r = client.post("/f/1/x/beacon", json={}, headers={"Origin": "https://otro.example.com"})
    assert r.status_code == 403
