"""Estadísticas de un formulario (cupos, inscritos, variables) y acceso de CLIENTE por formulario: solo agregados, aislado del evento y de otros formularios."""
import json
from datetime import timedelta

import pytest

from app.timeutil import utcnow
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _open, _put, _status, _submit


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _who(n):
    return {"cedula": f"77700{n:02d}", "nombres": f"Zulema{n}", "apellidos": "Quintero", "correo": f"zq{n}@correo-privado.test"}


def _setup(client, factory, capacity=5, rules=None):
    """Evento con un formulario abierto: cupo total, dos variables de elección y (opcional) cupos por variable. Deja la sesión del admin cerrada."""
    factory.staff("admin", "adm1")
    ev = factory.event("en_proceso")
    login(client, "adm1")
    form = _create(client, ev)
    ciudad = {"id": "ciudad", "type": "select", "label": "Ciudad", "options": ["Bogotá", "Cali", "Quito"], "stats": True}
    cat = {"id": "cat", "type": "radio", "label": "Categoría", "options": ["VIP", "General"]}
    nota = {"id": "nota", "type": "text_long", "label": "Comentario"}
    rules = rules if rules is not None else [
        {"id": "vip1", "label": "VIP Bogotá", "limit": 2, "match": "all", "conds": [{"field": "cat", "op": "equals", "value": "VIP"}, {"field": "ciudad", "op": "equals", "value": "Bogotá"}]},
        {"id": "cali1", "label": "Cali", "limit": 4, "match": "all", "conds": [{"field": "ciudad", "op": "equals", "value": "Cali"}]}]
    assert _put(client, ev, form, design=_design(_basic_fields() + [ciudad, cat, nota]), settings={"quotas": {"rules": rules}}).status_code == 200
    assert _status(client, ev, form, manual_status="activo", capacity=capacity).status_code == 200
    client.post("/logout")
    return ev, form


def _enroll(client, ev, form, n, ciudad, cat):
    r = _submit(client, ev, form, {**_who(n), "ciudad": ciudad, "cat": cat, "nota": "dato privado"}, sid=f"s{n}")
    assert r.status_code == 200, r.text


def _login_client(client, acc):
    """Fase 4: la contraseña que entrega el comercial se cambia al primer ingreso; estas pruebas miran lo que el cliente ve DESPUÉS, así que se da por cambiada."""
    from app.database import SessionLocal
    from app.models import StaffUser

    with SessionLocal() as s:
        s.query(StaffUser).filter_by(username=acc["username"]).update({"must_change_password": False})
        s.commit()
    return login(client, acc["username"], acc["password"])


def _create_access(client, ev, form, **body):
    r = client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_stats_show_capacity_quotas_and_choice_variables_without_personal_data(client, factory):
    ev, form = _setup(client, factory)
    for n, (c, k) in enumerate([("Bogotá", "VIP"), ("Bogotá", "VIP"), ("Cali", "General")], start=1):
        _enroll(client, ev, form, n, c, k)
    login(client, "adm1")
    r = client.get(f"/api/events/{ev.id}/forms/{form['id']}/stats")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["summary"]["registered"] == 3
    assert d["capacity"] == {"total": 5, "used": 3, "left": 2, "pct": 60, "full": False}
    q = {x["label"]: x for x in d["quotas"]}
    assert (q["VIP Bogotá"]["used"], q["VIP Bogotá"]["left"], q["VIP Bogotá"]["pct"], q["VIP Bogotá"]["full"]) == (2, 0, 100, True)
    assert (q["Cali"]["used"], q["Cali"]["left"], q["Cali"]["pct"], q["Cali"]["full"]) == (1, 3, 25, False)
    assert "Categoría es VIP y Ciudad es Bogotá" in q["VIP Bogotá"]["rule"]
    dist = {x["label"]: x for x in d["distributions"]}
    assert [x["label"] for x in d["distributions"]][0] == "Ciudad"                                              # las marcadas «genera estadísticas» van primero
    assert {i["label"]: i["count"] for i in dist["Ciudad"]["items"]} == {"Bogotá": 2, "Cali": 1, "Quito": 0}     # opciones sin respuestas también aparecen
    assert {i["label"]: i["count"] for i in dist["Categoría"]["items"]} == {"VIP": 2, "General": 1}
    assert dist["Ciudad"]["items"][0] == {"label": "Bogotá", "count": 2, "pct": 67}
    assert "Comentario" not in dist and "Cédula" not in dist and "Correo" not in dist                            # solo variables de elección
    raw = json.dumps(d, ensure_ascii=False)
    for private in ("Zulema", "Quintero", "correo-privado", "77700", "dato privado"):
        assert private not in raw


def test_stats_without_capacity_or_quotas_and_with_no_submissions(client, factory):
    ev, form = _setup(client, factory, capacity=None, rules=[])
    login(client, "adm1")
    d = client.get(f"/api/events/{ev.id}/forms/{form['id']}/stats").json()
    assert d["capacity"] is None and d["quotas"] == [] and d["summary"]["registered"] == 0 and d["timeline"] is None
    assert {i["label"]: i["count"] for i in d["distributions"][0]["items"]} == {"Bogotá": 0, "Cali": 0, "Quito": 0}


def test_stats_page_is_staff_only_and_renders(client, factory):
    ev, form = _setup(client, factory)
    assert client.get(f"/kiosk/{ev.id}/formularios/{form['id']}/estadisticas").status_code == 302          # sin sesión
    login(client, "adm1")
    page = client.get(f"/kiosk/{ev.id}/formularios/{form['id']}/estadisticas")
    assert page.status_code == 200 and "form-stats.js" in page.text and f"/api/events/{ev.id}/forms/{form['id']}/stats" in page.text
    assert client.get(f"/kiosk/{ev.id}/formularios/99999/estadisticas").status_code == 302
    assert client.get("/api/events/99999/forms/1/stats").status_code == 404


def test_create_access_shows_password_once_and_the_client_sees_only_their_form(client, factory):
    ev, form = _setup(client, factory)
    _enroll(client, ev, form, 1, "Cali", "General")
    login(client, "adm1")
    acc = _create_access(client, ev, form, days=10, full_name="María de la empresa")
    assert acc["username"].startswith("cliente-f") and len(acc["password"]) >= 12 and "no se vuelve a mostrar" in acc["message"]
    assert acc["password"] not in json.dumps(client.get(f"/api/events/{ev.id}/forms/{form['id']}/client-access").json())      # la lista nunca devuelve la contraseña
    listed = client.get(f"/api/events/{ev.id}/forms/{form['id']}/client-access").json()["users"]
    assert [u["username"] for u in listed] == [acc["username"]] and not listed[0]["expired"]
    client.post("/logout")
    assert _login_client(client, acc).status_code in (200, 302, 303)
    assert client.get("/").headers["location"] == "/mi-formulario"
    page = client.get("/mi-formulario")
    assert page.status_code == 200 and "/api/form-client/stats" in page.text
    d = client.get("/api/form-client/stats").json()
    assert d["form"]["id"] == form["id"] and d["summary"]["registered"] == 1 and d["capacity"]["used"] == 1
    me = client.get("/api/form-client/me").json()
    assert me["form"]["name"] == form["name"]
    # nada del evento ni del formulario (editor, respuestas, analítica, personas)
    for url in (f"/api/events/{ev.id}/forms/{form['id']}/stats", f"/api/events/{ev.id}/forms/{form['id']}", f"/api/events/{ev.id}/forms/{form['id']}/submissions",
                f"/api/events/{ev.id}/forms/{form['id']}/analytics", f"/api/events/{ev.id}/forms", f"/api/events/{ev.id}/forms/{form['id']}/client-access",
                f"/api/events/{ev.id}/stats/variables", f"/api/events/{ev.id}/analytics/registro", f"/api/users?event_id={ev.id}", f"/api/events/{ev.id}/staff-users"):
        assert client.get(url).status_code in (403, 404, 422), url
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json={}).status_code == 403          # no crea más accesos
    for page_url in (f"/kiosk/{ev.id}", f"/kiosk/{ev.id}/estadisticas", f"/kiosk/{ev.id}/formularios", f"/kiosk/{ev.id}/formularios/{form['id']}/estadisticas", "/clientes"):
        assert client.get(page_url).status_code == 302 and client.get(page_url).headers["location"] in ("/", "/login", f"/kiosk/{ev.id}"), page_url
    assert client.get("/api/events").status_code in (200, 403) and ev.event_code not in client.get("/api/events").text


def test_client_of_one_form_never_sees_another_form_of_the_same_event(client, factory):
    ev, form1 = _setup(client, factory)
    login(client, "adm1")
    form2 = _create(client, ev, name="Otro formulario")
    _status(client, ev, form2, manual_status="activo", capacity=9)
    acc2 = _create_access(client, ev, form2)
    client.post("/logout")
    _enroll(client, ev, form1, 1, "Cali", "General")
    _enroll(client, ev, form1, 2, "Cali", "General")
    assert _login_client(client, acc2).status_code in (200, 302, 303)
    d = client.get("/api/form-client/stats").json()
    assert d["form"]["id"] == form2["id"] and d["summary"]["registered"] == 0 and d["capacity"]["total"] == 9           # su formulario, no el primero
    assert client.get(f"/api/events/{ev.id}/forms/{form1['id']}/stats").status_code == 403
    assert client.get("/api/form-client/stats", params={"form_id": form1["id"]}).json()["form"]["id"] == form2["id"]    # un parámetro no cambia el formulario


def test_event_clients_are_unchanged_and_have_no_form_access(client, factory):
    ev = factory.event("en_proceso")
    cli = factory.staff("cliente", "cli1")
    factory.authorize(ev, cli)
    login(client, "cli1")
    assert client.get("/").headers["location"] == f"/kiosk/{ev.id}"                    # sigue entrando directo a su evento
    assert client.get("/mi-formulario").headers["location"] == "/"
    assert client.get("/api/form-client/stats").status_code == 403
    assert client.get(f"/kiosk/{ev.id}/estadisticas").status_code == 200              # y ve las estadísticas del evento como siempre


def test_expired_access_is_refused_and_revoking_removes_it(client, factory, db):
    from app.models import FormClientUser, StaffUser
    ev, form = _setup(client, factory)
    login(client, "adm1")
    acc = _create_access(client, ev, form, days=1)
    bad = client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json={"days": 999})
    assert bad.status_code == 400
    client.post("/logout")
    _login_client(client, acc)
    assert client.get("/api/form-client/stats").status_code == 200
    g = db.query(FormClientUser).one()
    g.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    r = client.get("/api/form-client/stats")
    assert r.status_code == 403 and "venció" in r.json()["detail"]
    page = client.get("/mi-formulario")
    assert page.status_code == 403 and "venció" in page.text
    g.expires_at = utcnow() + timedelta(days=1)
    db.commit()
    client.post("/logout")
    login(client, "adm1")
    uid = db.query(StaffUser).filter_by(username=acc["username"]).one().id
    assert client.delete(f"/api/events/{ev.id}/forms/{form['id']}/client-access/{uid}").status_code == 200
    assert client.delete(f"/api/events/{ev.id}/forms/{form['id']}/client-access/{uid}").status_code == 404
    client.post("/logout")
    assert login(client, acc["username"], acc["password"]).status_code in (400, 401, 403)
    db.expire_all()
    assert db.query(StaffUser).filter_by(id=uid).one().is_active is False and db.query(FormClientUser).count() == 0


def test_only_commercial_or_admin_create_access_and_tenant_isolation(client, factory, monkeypatch):
    ev, form = _setup(client, factory)
    factory.staff("coordinador", "coo1")
    login(client, "coo1")
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json={}).status_code == 403
    assert client.get(f"/api/events/{ev.id}/forms/{form['id']}/client-access").status_code == 200                       # sí puede ver la lista y las estadísticas
    client.post("/logout")
    factory.staff("comercial", "com1")
    login(client, "com1")
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json={}).status_code == 200
    client.post("/logout")
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("otro")
    factory.staff("admin", "adm_otro", tenant_id="otro")
    login(client, "adm_otro")
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/client-access", json={}).status_code == 404
    assert client.get(f"/api/events/{ev.id}/forms/{form['id']}/stats").status_code == 404
    other = factory.event("en_proceso")
    assert client.post(f"/api/events/{other.id}/forms/{form['id']}/client-access", json={}).status_code == 404         # el formulario debe ser de ESE evento


def test_deleting_the_form_cuts_the_access(client, factory, db):
    from app.models import FormClientUser, StaffUser
    ev, form = _setup(client, factory)
    login(client, "adm1")
    acc = _create_access(client, ev, form)
    factory.staff("super_admin", "sup1")
    client.post("/logout")
    login(client, "sup1")
    assert client.post(f"/api/events/{ev.id}/forms/{form['id']}/archive").status_code == 200
    assert client.delete(f"/api/events/{ev.id}/forms/{form['id']}").status_code == 200
    db.expire_all()
    assert db.query(FormClientUser).count() == 0 and db.query(StaffUser).filter_by(username=acc["username"]).one().is_active is False


def test_generated_passwords_pass_the_strict_policy():
    from app import form_client, security
    for _ in range(50):
        pw = form_client.new_password()
        assert len(pw) == 14 and security.password_problem(pw, "cliente-f1-ab12", strict=True) is None


def test_an_expired_form_client_cannot_use_the_rest_of_the_api(client, factory, db):
    """Fase 3 (B10): vencido el acceso, la cuenta sigue activa pero solo ve su propio mensaje; badge-assets, estados y sondeos le dan 401."""
    from app.models import FormClientUser
    ev, form = _setup(client, factory)
    login(client, "adm1")
    acc = _create_access(client, ev, form, days=1)
    client.post("/logout")
    _login_client(client, acc)
    assert client.get("/api/ping-auth").status_code == 200
    g = db.query(FormClientUser).one()
    g.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get("/api/form-client/stats").status_code == 403           # su propia ruta: mensaje de acceso vencido
    assert client.get("/api/ping-auth").status_code == 401
    assert client.get("/api/badge-assets/acme/x.png").status_code == 401
