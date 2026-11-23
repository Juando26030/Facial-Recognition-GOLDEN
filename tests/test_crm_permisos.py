"""CRM C1b-1: quién entra a qué. Comercial, admin y super_admin editan; el coordinador puro, el digitador y el cliente no entran; archivar y suprimir son de admin+. Necesitan PostgreSQL."""
import pytest

from tests.conftest import login
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def _seed(client, factory):
    admin = factory.staff("admin", "seed_admin")
    login(client, admin.username)
    a = new_account(client, "Semilla")
    c = new_contact(client, a["id"])
    return a, c


READ = ("get", "/api/crm/accounts"), ("get", "/api/crm/meta"), ("get", "/api/crm/accounts/{a}"), ("get", "/api/crm/accounts/{a}/contacts"), ("get", "/api/crm/accounts/{a}/notes"), ("get", "/api/crm/accounts/{a}/history")
ADMIN_ONLY = ("post", "/api/crm/accounts/{a}/archive"), ("post", "/api/crm/accounts/{a}/restore"), ("post", "/api/crm/accounts/{a}/erase"), ("post", "/api/crm/contacts/{c}/erase")


def _call(client, method, url, a, c):
    url = url.format(a=a["id"], c=c["id"])
    return getattr(client, method)(url, **({"json": {"reason": "x", "confirm_name": "x"}} if method == "post" else {}))


@pytest.mark.parametrize("role", ["cliente", "digitador", "coordinador"])
def test_low_roles_get_403_everywhere(client, factory, crm_on, role):
    a, c = _seed(client, factory)
    client.cookies.clear()
    login(client, factory.staff(role, f"low_{role}").username)
    for method, url in READ + ADMIN_ONLY:
        assert _call(client, method, url, a, c).status_code == 403, (role, url)
    assert client.post("/api/crm/accounts", json={"name": "No"}).status_code == 403


def test_unauthenticated_is_401(client, factory, crm_on):
    assert client.get("/api/crm/accounts").status_code == 401


@pytest.mark.parametrize("role", ["comercial", "admin", "super_admin"])
def test_sales_and_admin_read_and_edit(client, factory, crm_on, role):
    staff_client(client, factory, role, f"ok_{role}")
    a = new_account(client, f"De {role}")
    for method, url in READ:
        assert _call(client, method, url, a, {"id": 0}).status_code == 200, (role, url)
    assert client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"first_name": "Ana"}).status_code == 200


def test_commercial_cannot_archive_or_erase(client, factory, crm_on):
    a, c = _seed(client, factory)
    client.cookies.clear()
    login(client, factory.staff("comercial", "com_x").username)
    for method, url in ADMIN_ONLY:
        assert _call(client, method, url, a, c).status_code == 403, url


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_can_archive_and_restore(client, factory, crm_on, role):
    staff_client(client, factory, role, f"adm_{role}")
    a = new_account(client)
    assert client.post(f"/api/crm/accounts/{a['id']}/archive").status_code == 200
    assert client.post(f"/api/crm/accounts/{a['id']}/restore").status_code == 200


def test_coordinator_with_commercial_as_second_role_enters(client, factory, crm_on):
    staff_client(client, factory, "coordinador", "coord_com", secondary_role="comercial")
    assert client.get("/api/crm/accounts").status_code == 200


def test_staff_limited_to_a_client_is_refused_when_isolation_is_on(client, factory, crm_on, monkeypatch):
    factory.tenant("acme")
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    staff_client(client, factory, "admin", "adm_acme", tenant_id="acme")
    assert client.get("/api/crm/accounts").status_code == 403 and client.post("/api/crm/accounts", json={"name": "No"}).status_code == 403


def test_only_the_author_or_an_admin_deletes_a_note(client, factory, crm_on):
    staff_client(client, factory, "comercial", "autor")
    a = new_account(client)
    n = client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "mía"}).json()
    client.cookies.clear()
    login(client, factory.staff("comercial", "intruso").username)
    assert client.delete(f"/api/crm/notes/{n['id']}").status_code == 403
    client.cookies.clear()
    login(client, factory.staff("admin", "jefe").username)
    assert client.delete(f"/api/crm/notes/{n['id']}").status_code == 200
