"""CRM C1b-2: rutas de página (con base de datos; SIN EJECUTAR hasta que Juan David las corra, procedimiento en docs/crm/)."""
import pytest

from tests.crm_helpers import crm_on, staff_client  # noqa: F401

PAGES = ["/crm", "/crm/cuentas/nueva", "/crm/cuentas/1"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_are_404_when_crm_is_off(client, factory, monkeypatch, path):
    monkeypatch.setenv("CRM_ENABLED", "0")
    staff_client(client, factory, "admin")
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", PAGES)
def test_pure_coordinator_is_sent_home(client, factory, crm_on, path):
    staff_client(client, factory, "coordinador")
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"


@pytest.mark.parametrize("role", ["comercial", "admin", "super_admin"])
@pytest.mark.parametrize("path", PAGES)
def test_sales_and_admin_see_the_pages(client, factory, crm_on, role, path):
    staff_client(client, factory, role)
    r = client.get(path)
    assert r.status_code == 200 and "CRM" in r.text


def test_menu_link_follows_the_role(client, factory, crm_on):
    staff_client(client, factory, "comercial")
    assert 'href="/crm"' in client.get("/crm").text


def test_history_names_the_contact(client, factory, crm_on):
    from tests.crm_helpers import new_account, new_contact
    staff_client(client, factory, "admin", "adm_hist")
    a = new_account(client)
    new_contact(client, a["id"], "Ana", "Pérez")
    rows = client.get(f"/api/crm/accounts/{a['id']}/history").json()
    assert any(r["entity"] == "contact" and r["contact"] == "Ana Pérez" for r in rows)
    assert all(r["contact"] is None for r in rows if r["entity"] == "account")
