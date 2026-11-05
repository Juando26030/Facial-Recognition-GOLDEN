"""Enlaces de SOLO LECTURA a las estadísticas del evento y de un formulario (sin usuario ni contraseña, con vencimiento, revocables)."""
import re
from datetime import timedelta

import pytest

from app import stats_links
from app.models import StatsLink
from app.timeutil import utcnow
from tests.conftest import login
from tests.test_forms import _create as _create_form

TOKEN = re.compile(r"/ver/[ef]/([A-Za-z0-9_\-]+)$")


@pytest.fixture()
def env(client, factory, db):
    factory.staff("coordinador", "coord1")
    factory.staff("digitador", "dig1")
    ev = factory.event("en_proceso")
    factory.person(ev, "2001", first_name="Ana")
    login(client, "coord1")
    return ev


def _make(client, ev, scope="event", **body):
    r = client.post(f"/api/events/{ev.id}/stats-links", json={"scope": scope, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _token(url):
    return TOKEN.search(url).group(1)


def _anon(client):
    client.post("/logout")
    client.cookies.clear()


def test_event_link_opens_without_login_and_is_read_only(client, env):
    d = _make(client, env, days=3, label="Cliente")
    token = _token(d["url"])
    _anon(client)
    r = client.get(f"/ver/e/{token}")
    assert r.status_code == 200
    assert "solo lectura" in r.text and f"/api/ver/{token}" in r.text
    assert all(f'id="{i}"' not in r.text for i in ("exportBtn", "purgePhotosBtn", "timingReport", "statsShare"))      # sin exportar, sin borrar, sin tiempos, sin compartir
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"] and r.headers["referrer-policy"] == "no-referrer"
    assert client.get(f"/api/ver/{token}/stats/variables").status_code == 200
    assert client.get(f"/api/ver/{token}/stats/data", params={"variable": "entity"}).status_code == 200
    assert client.get(f"/api/ver/{token}/stats/data", params={"variable": "no_existe"}).status_code == 400
    dash = client.get(f"/api/ver/{token}/analytics/registro").json()
    assert all(c.get("id") != "by_operator" for c in dash["charts"])                      # los nombres del personal no salen


def test_link_gives_no_other_access(client, env):
    token = _token(_make(client, env)["url"])
    _anon(client)
    for method, path in (("get", "/api/users?event_id=%d" % env.id), ("post", "/api/report/start"), ("get", f"/api/events/{env.id}/stats/variables"), ("get", f"/kiosk/{env.id}/estadisticas")):
        r = getattr(client, method)(path, follow_redirects=False)
        assert r.status_code in (302, 303, 401, 403), (path, r.status_code)
    assert client.get(f"/ver/f/{token}").status_code == 404                              # un enlace de evento no abre el de formulario
    assert client.post(f"/api/ver/{token}/stats/data").status_code in (404, 405)       # nada que escriba


def test_expired_revoked_and_unknown_links_look_the_same(client, env, db):
    d = _make(client, env)
    token = _token(d["url"])
    _anon(client)
    assert client.get(f"/ver/e/{token}").status_code == 200
    link = db.query(StatsLink).filter_by(id=d["id"]).first()
    link.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    expired = client.get(f"/ver/e/{token}")
    unknown = client.get("/ver/e/" + "x" * 43)
    assert expired.status_code == unknown.status_code == 404 and expired.text == unknown.text
    assert client.get(f"/api/ver/{token}/stats/variables").status_code == 404
    login(client, "coord1")
    d2 = _make(client, env)
    assert client.delete(f"/api/events/{env.id}/stats-links/{d2['id']}").status_code == 200
    t2 = _token(d2["url"])
    _anon(client)
    assert client.get(f"/ver/e/{t2}").status_code == 404


def test_only_the_hash_is_stored_and_days_are_capped(client, env, db):
    d = _make(client, env, days=999)
    token = _token(d["url"])
    row = db.query(StatsLink).filter_by(id=d["id"]).first()
    assert row.token_hash == stats_links.hash_token(token) and token not in (row.token_hash or "")
    assert row.expires_at - row.created_at <= timedelta(days=stats_links.MAX_DAYS, seconds=5)
    assert "url" not in client.get(f"/api/events/{env.id}/stats-links").json()["links"][0]       # el enlace completo no se vuelve a mostrar


def test_form_link_shows_only_that_form_and_not_the_event_page(client, env):
    f = _create_form(client, env)
    token = _token(_make(client, env, scope="form", form_id=f["id"])["url"])
    _anon(client)
    r = client.get(f"/ver/f/{token}")
    assert r.status_code == 200 and "solo lectura" in r.text and f"/api/ver/{token}/form-stats" in r.text and "fs-tests" not in r.text and 'action="/logout"' not in r.text
    s = client.get(f"/api/ver/{token}/form-stats")
    assert s.status_code == 200 and s.json()["form"]["id"] == f["id"]
    assert client.get(f"/ver/e/{token}").status_code == 404


def test_only_coordinators_up_create_and_only_for_their_event(client, env, factory):
    _anon(client)
    login(client, "dig1")
    assert client.post(f"/api/events/{env.id}/stats-links", json={"scope": "event"}).status_code == 403
    _anon(client)
    factory.tenant("otro")
    factory.staff("coordinador", "coord_otro", tenant_id="otro")
    login(client, "coord_otro")
    r = client.post(f"/api/events/{env.id}/stats-links", json={"scope": "event"})
    assert r.status_code in (403, 404)
