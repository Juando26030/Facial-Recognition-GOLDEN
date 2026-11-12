"""CRM: dibuja CADA pantalla con la app real (plantillas, macros, url_for). SIN EJECUTAR aquí; falla si alguna da 500 o le falta su título.
Nació de un error real de staging: las macros importadas sin «with context» no ven `request` y todas las pantallas nuevas daban 500."""
import pytest

from tests.crm_helpers import crm_on, new_account, staff_client  # noqa: F401

LINES = [{"name": "Servicio ficticio", "qty": "2", "unit_price": "100000"}]


def _data(client):
    acc = new_account(client, "Empresa Ficticia Pantallas")
    opp = client.post("/api/crm/opportunities", json={"account_id": acc["id"], "name": "Evento ficticio"}).json()
    quote = client.post("/api/crm/quotes", json={"account_id": acc["id"], "title": "Cotización ficticia", "lines": LINES}).json()
    return acc, opp, quote


def _pages(acc, opp, quote):
    return [("/crm", "Cuentas"), ("/crm/cuentas/nueva", "Nueva cuenta"), (f"/crm/cuentas/{acc['id']}", "Cargando"), ("/crm/oportunidades", "Oportunidades"),
            (f"/crm/oportunidades/{opp['id']}", "Cargando"), ("/crm/leads", "Leads"), ("/crm/cotizaciones", "Cotizaciones"), (f"/crm/cotizaciones/{quote['id']}", "qTitle"),
            ("/crm/productos", "Productos y plantillas"), ("/crm/buscar", "Buscar en el CRM"), ("/crm/mi-dia", "Mi día"), ("/crm/tableros", "Tableros"),
            ("/crm/embudos", "Embudos y etapas"), ("/crm/importar", "Importar de SuiteCRM")]


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_every_crm_page_renders_with_200_and_its_title(client, factory, crm_on, role):
    staff_client(client, factory, role, f"{role}_render")
    acc, opp, quote = _data(client)
    for path, title in _pages(acc, opp, quote):
        r = client.get(path)
        assert r.status_code == 200, f"{path} dio {r.status_code}"
        assert title in r.text, f"{path} no trae «{title}»"


def test_commercial_renders_the_pages_they_may_open_and_not_the_admin_ones(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_render")
    acc, opp, quote = _data(client)
    for path, title in _pages(acc, opp, quote):
        r = client.get(path, follow_redirects=False)
        if path in ("/crm/embudos", "/crm/importar", "/crm/productos"):
            assert r.status_code in (302, 403), path
        else:
            assert r.status_code == 200 and title in r.text, path
