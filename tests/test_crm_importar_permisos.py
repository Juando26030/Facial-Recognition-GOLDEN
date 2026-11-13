"""Importar de SuiteCRM: solo admin y super_admin (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
import pytest

from tests.crm_helpers import crm_on, staff_client  # noqa: F401

API = [("get", "/api/crm/import/runs"), ("get", "/api/crm/import/runs/1"), ("get", "/api/crm/import/runs/1/pairs"), ("post", "/api/crm/import/runs/1/cancel")]


@pytest.mark.parametrize("role", ["cliente", "digitador", "coordinador", "comercial"])
def test_lower_roles_get_403_on_the_page_and_every_import_route(client, factory, crm_on, role):
    staff_client(client, factory, role, f"{role}_imp")
    assert client.get("/crm/importar", follow_redirects=False).status_code in (403, 302) and client.get("/crm/importar", follow_redirects=False).status_code != 200
    for method, path in API:
        assert getattr(client, method)(path).status_code == 403, (role, path)
    assert client.post("/api/crm/import/runs", data={"mode": "sample"}, files={"accounts": ("a.csv", b"Nombre\nX\n")}).status_code == 403


def test_a_commercial_with_a_session_gets_403_not_a_redirect_on_the_page(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_imp403")
    assert client.get("/crm/importar", follow_redirects=False).status_code == 403


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admins_open_the_page_and_see_the_tab_last(client, factory, crm_on, role):
    staff_client(client, factory, role, f"{role}_imp_ok")
    r = client.get("/crm/importar")
    assert r.status_code == 200 and "Importar de SuiteCRM" in r.text
    tabs = [t for t in ("Buscar", "Mi día", "Tableros", "Cuentas", "Leads", "Oportunidades", "Cotizaciones", "Embudos", "Importar") if f">{t}</a>" in r.text]
    assert tabs == ["Buscar", "Mi día", "Tableros", "Cuentas", "Leads", "Oportunidades", "Cotizaciones", "Embudos", "Importar"]
    assert [i for i, t in enumerate(tabs) if t == "Importar"] == [len(tabs) - 1]


def test_other_roles_do_not_see_the_importar_or_embudos_tabs(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_tabs")
    html = client.get("/crm").text
    assert ">Importar</a>" not in html and ">Embudos</a>" not in html and ">Buscar</a>" in html
    assert html.index(">Buscar</a>") < html.index(">Mi día</a>") < html.index(">Tableros</a>") < html.index(">Cuentas</a>") < html.index(">Cotizaciones</a>")
