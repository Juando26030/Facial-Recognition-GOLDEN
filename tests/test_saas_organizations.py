"""SaaS, pieza 1 (0162, docs/27_SAAS_EMPRESAS.md): empresas, planes, primer administrador, tope de eventos del mes. Pruebas CON base.
Las puras y de texto (sin base) están en tests/test_saas_organizations_puro.py."""
import pytest
from sqlalchemy import inspect, text

from tests.conftest import login


@pytest.fixture()
def root(client, factory):
    staff = factory.staff("super_admin", "dueno")
    login(client, "dueno")
    return staff


def _event(tenant_id, coord_id, code):
    return {"tenant_id": tenant_id, "event_code": code, "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
            "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord_id}


def _new_org(client, **extra):
    r = client.post("/api/platform/orgs", json={"name": "Eventos del Caribe", "plan": "basico", **extra})
    assert r.status_code == 200, r.text
    return r.json()


ADMIN = {"username": "laura.caribe", "full_name": "Laura Gómez", "email": "laura@caribe.test", "phone": "+573001112233"}


# ------------------------------- migración -------------------------------
def test_migration_adds_the_table_and_the_two_columns_with_default_one(db):
    insp = inspect(db.get_bind())
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert {"id", "slug", "name", "legal_name", "nit", "contact_email", "contact_phone", "plan", "entitlements_json", "status", "created_at", "notes"} == cols
    for table in ("tenants", "staff_users"):
        assert "org_id" in {c["name"] for c in insp.get_columns(table)}
        assert f"ix_{table}_org_id" in {i["name"] for i in insp.get_indexes(table)}
    assert "org_id" not in {c["name"] for c in insp.get_columns("events")}          # SOLO esas dos tablas en esta pieza
    db.execute(text("INSERT INTO tenants (id, client_code, name) VALUES ('viejo', 'CVIEJO', 'Cliente de antes')"))          # una fila escrita como las de siempre queda en Golden
    db.execute(text("INSERT INTO staff_users (username, password_hash, role, is_active) VALUES ('de_antes', 'x', 'coordinador', true)"))
    db.commit()
    assert db.execute(text("SELECT org_id FROM tenants WHERE id = 'viejo'")).scalar() == 1
    assert db.execute(text("SELECT org_id FROM staff_users WHERE username = 'de_antes'")).scalar() == 1


def test_golden_is_row_one_and_the_next_company_never_takes_its_id(client, root, db):
    from app.models import Organization
    assert db.query(Organization).count() == 0          # las pruebas vacían la tabla: la fila 1 se repone sola
    listed = client.get("/api/platform/orgs").json()
    assert [(o["id"], o["slug"], o["plan"], o["internal"]) for o in listed["orgs"]] == [(1, "golden", "interno", True)]
    org = _new_org(client)
    assert org["id"] != 1 and org["slug"] == "eventos-del-caribe" and org["plan"] == "basico" and org["status"] == "active" and org["internal"] is False
    assert org["entitlements"]["events_per_month"] == 1 and org["usage"]["events_per_month"] == 0


# ------------------------------- permisos -------------------------------
def test_only_the_super_admin_reaches_the_platform(client, factory):
    assert client.get("/api/platform/orgs").status_code == 401
    assert client.get("/plataforma").status_code == 302
    factory.staff("admin", "admin1")
    login(client, "admin1")
    for method, path in (("get", "/api/platform/orgs"), ("get", "/api/platform/catalog"), ("post", "/api/platform/orgs"), ("patch", "/api/platform/orgs/1"),
                         ("post", "/api/platform/orgs/1/suspend"), ("post", "/api/platform/orgs/1/reactivate"), ("post", "/api/platform/orgs/1/admin"), ("get", "/api/platform/orgs/1/usage")):
        kwargs = {} if method == "get" else {"json": {}}
        assert getattr(client, method)(path, **kwargs).status_code == 403, path
    page = client.get("/plataforma")
    assert page.status_code == 302 and page.headers["location"] == "/"


def test_the_page_opens_for_the_super_admin_and_the_sidebar_offers_it(client, root):
    page = client.get("/plataforma")
    assert page.status_code == 200 and "Empresas (SaaS)" in page.text and "plataforma.js" in page.text and 'href="/plataforma" class="active"' in page.text


# ------------------------------- empresas -------------------------------
def test_create_edit_and_validate_a_company(client, root, db):
    from app.models import AuditAction
    org = _new_org(client, legal_name="Eventos del Caribe S.A.S.", nit="900.123.456-7", contact_email="gerencia@caribe.test", entitlements={"events_per_month": 3, "facial": True})
    assert org["own_entitlements"] == {"events_per_month": 3, "facial": True} and org["entitlements"]["events_per_month"] == 3 and org["entitlements"]["users"] == 5
    assert client.post("/api/platform/orgs", json={"name": "Eventos del Caribe", "plan": "pro"}).status_code == 400          # mismo identificador
    for bad in ({"name": "", "plan": "pro"}, {"name": "Otra", "plan": "interno"}, {"name": "Otra", "plan": "pro", "slug": "Con Espacios"}, {"name": "<b>Otra</b>", "plan": "pro"},
                {"name": "Otra", "plan": "pro", "contact_email": "sin-arroba"}, {"name": "Otra", "plan": "pro", "entitlements": {"users": -1}}, {"name": "Otra", "plan": "pro", "entitlements": {"x": 1}}):
        r = client.post("/api/platform/orgs", json=bad)
        assert r.status_code == 400 and isinstance(r.json()["detail"], str), bad
    r = client.patch(f"/api/platform/orgs/{org['id']}", json={"plan": "pro", "entitlements": {"users": None}, "notes": "Prueba hasta diciembre"})
    assert r.status_code == 200 and r.json()["plan"] == "pro" and r.json()["entitlements"]["events_per_month"] == 4 and r.json()["entitlements"]["users"] is None
    assert client.patch(f"/api/platform/orgs/{org['id']}", json={"plan": "interno"}).status_code == 400
    assert client.patch("/api/platform/orgs/999", json={"name": "X"}).status_code == 404
    actions = {(a.action, a.entity) for a in db.query(AuditAction).all()}
    assert {("create", "organization"), ("update", "organization")} <= actions


def test_golden_keeps_its_plan_and_cannot_be_suspended(client, root):
    client.get("/api/platform/orgs")
    assert client.patch("/api/platform/orgs/1", json={"plan": "basico"}).status_code == 400
    assert client.patch("/api/platform/orgs/1", json={"entitlements": {"events_per_month": 0}}).status_code == 400
    assert client.post("/api/platform/orgs/1/suspend").status_code == 400
    assert client.patch("/api/platform/orgs/1", json={"nit": "900.000.000-1"}).json()["nit"] == "900.000.000-1"          # sus datos sí se editan


# ------------------------------- primer administrador -------------------------------
def test_an_outside_company_gets_no_account_while_isolation_is_off(client, root, db, monkeypatch):
    from app.models import StaffUser
    monkeypatch.delenv("ENFORCE_STAFF_TENANT", raising=False)
    org = _new_org(client)
    r = client.post(f"/api/platform/orgs/{org['id']}/admin", json=ADMIN)
    assert r.status_code == 409 and "ENFORCE_STAFF_TENANT" in r.json()["detail"]
    assert db.query(StaffUser).filter_by(username=ADMIN["username"]).first() is None
    r = client.post("/api/platform/orgs", json={"name": "Otra Empresa", "plan": "pro", "admin": ADMIN})          # empresa + administrador en una transacción: si el administrador no se puede, la empresa tampoco queda
    assert r.status_code == 409
    assert "otra-empresa" not in [o["slug"] for o in client.get("/api/platform/orgs").json()["orgs"]]


def test_first_admin_gets_a_one_time_password_and_must_change_it(client, root, db, monkeypatch):
    from app import security
    from app.auth import verify_password
    from app.models import StaffUser, Tenant
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    org = _new_org(client, plan="pro")
    r = client.post(f"/api/platform/orgs/{org['id']}/admin", json=ADMIN)
    assert r.status_code == 200, r.text
    out = r.json()
    password = out["temp_password"]
    assert out["username"] == ADMIN["username"] and security.password_problem(password, ADMIN["username"], strict=True) is None and "no se vuelve a mostrar" in out["notice"]
    admin = db.query(StaffUser).filter_by(username=ADMIN["username"]).one()
    assert admin.role == "admin" and admin.org_id == org["id"] and admin.must_change_password is True and admin.created_by_id == root.id
    assert admin.password_hash != password and verify_password(password, admin.password_hash)
    home = db.query(Tenant).filter_by(id=admin.tenant_id).one()          # nace ATADA al cliente propio de su empresa: el aislamiento de hoy (ENFORCE_STAFF_TENANT) la deja solo ahí
    assert home.org_id == org["id"] and home.name == "Eventos del Caribe"
    assert password not in client.get("/api/platform/orgs").text          # se mostró una vez; no vuelve a salir
    for bad in ({**ADMIN, "username": "x"}, {**ADMIN, "username": "otro.usuario", "email": ""}, {**ADMIN, "username": "otro.usuario", "phone": ""}, ADMIN,
                {**ADMIN, "username": "otro.usuario"}):          # (el último: teléfono repetido)
        assert client.post(f"/api/platform/orgs/{org['id']}/admin", json=bad).status_code == 400, bad
    client.post("/logout")
    assert client.post("/login", data={"username": ADMIN["username"], "password": password}).status_code in (302, 303)
    nxt = client.get("/", headers={"accept": "text/html"})
    assert nxt.status_code == 302 and nxt.headers["location"] == "/cambiar-contrasena"          # el mecanismo de «clave primera vez» (docs/FASE_4_CLAVE_PRIMERA_VEZ.md)
    assert client.get("/api/platform/orgs").status_code == 403


def test_golden_admin_needs_no_switch_and_stays_global(client, root, db, monkeypatch):
    from app.models import StaffUser
    monkeypatch.delenv("ENFORCE_STAFF_TENANT", raising=False)
    client.get("/api/platform/orgs")
    r = client.post("/api/platform/orgs/1/admin", json=ADMIN)
    assert r.status_code == 200, r.text
    admin = db.query(StaffUser).filter_by(username=ADMIN["username"]).one()
    assert admin.org_id == 1 and admin.tenant_id is None and admin.role == "admin" and admin.must_change_password is True


def test_user_limit_applies_to_the_admin_of_an_outside_company(client, root, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    org = _new_org(client, entitlements={"users": 1})
    assert client.post(f"/api/platform/orgs/{org['id']}/admin", json=ADMIN).status_code == 200
    r = client.post(f"/api/platform/orgs/{org['id']}/admin", json={**ADMIN, "username": "segundo.admin", "phone": "+573009998877"})
    assert r.status_code == 400 and r.json()["detail"] == "Tu plan permite 1 usuario; contacta a soporte"


# ------------------------------- límite de eventos del mes -------------------------------
def test_event_limit_blocks_the_company_and_never_golden(client, root, factory, db):
    from app.models import Event, Tenant
    coord = factory.staff("coordinador", "coord")
    factory.staff("comercial", "comer")
    factory.tenant("acme")
    org = _new_org(client)          # Básico: 1 evento por mes
    db.add(Tenant(id="caribe", client_code="CCARIBE", name="Caribe", org_id=org["id"]))
    db.commit()
    commercial = {"commercial_staff_id": db.execute(text("SELECT id FROM staff_users WHERE username = 'comer'")).scalar()}
    assert client.post("/api/events", json={**_event("caribe", coord.id, "CARIBE-1"), **commercial}).status_code == 200
    r = client.post("/api/events", json={**_event("caribe", coord.id, "CARIBE-2"), **commercial})
    assert r.status_code == 403 and r.json()["detail"] == "Tu plan permite 1 evento por mes; contacta a soporte"
    assert db.query(Event).filter_by(tenant_id="caribe").count() == 1
    for n in range(3):          # Golden (empresa 1, plan interno): sin tope
        assert client.post("/api/events", json={**_event("acme", coord.id, f"GOLDEN-{n}"), **commercial}).status_code == 200
    usage = client.get(f"/api/platform/orgs/{org['id']}/usage").json()
    line = next(ln for ln in usage["lines"] if ln["key"] == "events_per_month")
    assert line == {"key": "events_per_month", "label": "Eventos por mes", "used": 1, "limit": 1, "over": True}
    assert client.patch(f"/api/platform/orgs/{org['id']}", json={"entitlements": {"events_per_month": 2}}).status_code == 200          # subirle el tope desde la pantalla basta: sin código
    assert client.post("/api/events", json={**_event("caribe", coord.id, "CARIBE-2"), **commercial}).status_code == 200


def test_events_of_past_months_do_not_count(client, root, factory, db):
    from datetime import timedelta
    from app import orgs
    from app.models import Event, Tenant
    from app.timeutil import utcnow
    org = _new_org(client)
    db.add(Tenant(id="caribe", client_code="CCARIBE", name="Caribe", org_id=org["id"]))
    db.commit()
    db.add(Event(tenant_id="caribe", event_code="VIEJO-1", name="Del mes pasado", status="finalizado", created_at=orgs.month_start(utcnow()) - timedelta(days=1)))
    db.commit()
    row = orgs.get_org(db, org["id"])
    assert orgs.usage(db, row)["events_per_month"] == 0 and orgs.usage(db, row)["events_total"] == 1
    assert orgs.check_limit(db, row, "events_per_month") == (True, "")


def test_a_suspended_company_creates_nothing_until_reactivated(client, root, factory, db):
    from app.models import Tenant
    coord = factory.staff("coordinador", "coord")
    comer = factory.staff("comercial", "comer")
    org = _new_org(client, plan="pro")
    db.add(Tenant(id="caribe", client_code="CCARIBE", name="Caribe", org_id=org["id"]))
    db.commit()
    assert client.post(f"/api/platform/orgs/{org['id']}/suspend").json()["status"] == "suspended"
    r = client.post("/api/events", json={**_event("caribe", coord.id, "CARIBE-1"), "commercial_staff_id": comer.id})
    assert r.status_code == 403 and "suspendida" in r.json()["detail"]
    assert client.post(f"/api/platform/orgs/{org['id']}/reactivate").json()["status"] == "active"
    assert client.post("/api/events", json={**_event("caribe", coord.id, "CARIBE-1"), "commercial_staff_id": comer.id}).status_code == 200


def test_usage_ignores_the_test_person_and_temporary_door_accounts(client, root, factory, db):
    from app import orgs, testperson
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    factory.person(ev, testperson.TEST_ID, "Persona", "De prueba")
    factory.staff("digitador", "puerta1")
    factory.staff("coordinador", "coord", is_active=False)
    factory.staff("admin", "admin1")
    used = orgs.usage(db, orgs.golden(db))
    assert used["attendees_total"] == 2 and used["attendees_per_event"] == 2 and used["users"] == 1 and used["clients"] == 1 and used["events_per_month"] == 1
