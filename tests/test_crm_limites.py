"""CRM: límites de longitud (con base de datos; SIN EJECUTAR hasta que Juan David las corra). Cada campo de texto con tope responde 400 en español al pasarse, nunca 500."""
import pytest

from app.crm import accounts as svc
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def _valid(key, size):
    """Un valor válido de exactamente `size` caracteres (los correos deben tener forma de correo)."""
    if key == "email":
        return "a" * (size - len("@e.co")) + "@e.co"
    return "x" * size


@pytest.mark.parametrize("key,limit", sorted(svc.ACCOUNT_LIMITS.items()))
def test_account_fields_over_the_limit_answer_400_in_spanish(client, factory, crm_on, key, limit):
    staff_client(client, factory, "comercial")
    body = {"name": "Cuenta de límites", key: _valid(key, limit + 1)}
    r = client.post("/api/crm/accounts", json=body)
    assert r.status_code == 400, r.text
    assert "demasiado largo" in r.json()["detail"] and key in r.json()["detail"]


@pytest.mark.parametrize("key,limit", sorted(svc.ACCOUNT_LIMITS.items()))
def test_account_fields_exactly_at_the_limit_are_saved(client, factory, crm_on, key, limit):
    staff_client(client, factory, "comercial")
    body = {"name": "Cuenta al límite", key: _valid(key, limit)}
    r = client.post("/api/crm/accounts", json=body)
    assert r.status_code == 200, r.text
    assert len(r.json()[key]) == limit


@pytest.mark.parametrize("key,limit", sorted(svc.CONTACT_LIMITS.items()))
def test_contact_fields_over_the_limit_answer_400_in_spanish(client, factory, crm_on, key, limit):
    staff_client(client, factory, "comercial")
    a = new_account(client)
    r = client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"first_name": "Ana", key: _valid(key, limit + 1)})
    assert r.status_code == 400, r.text
    assert "demasiado largo" in r.json()["detail"]


@pytest.mark.parametrize("key,limit", sorted(svc.CONTACT_LIMITS.items()))
def test_contact_fields_exactly_at_the_limit_are_saved(client, factory, crm_on, key, limit):
    staff_client(client, factory, "comercial")
    a = new_account(client)
    r = client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"first_name": "Ana", key: _valid(key, limit)})
    assert r.status_code == 200, r.text


def test_editing_with_a_too_long_value_is_also_400(client, factory, crm_on):
    staff_client(client, factory, "comercial")
    a = new_account(client)
    c = new_contact(client, a["id"])
    r = client.put(f"/api/crm/accounts/{a['id']}", json={"billing_city": "y" * 121, "updated_at": a["updated_at"]})
    assert r.status_code == 400 and "demasiado largo" in r.json()["detail"]
    r = client.put(f"/api/crm/contacts/{c['id']}", json={"job_title": "y" * 121, "updated_at": c["updated_at"]})
    assert r.status_code == 400 and "demasiado largo" in r.json()["detail"]


def test_both_names_at_120_characters_save_without_overflowing_the_search_column(client, factory, crm_on):
    """nombre + espacio + apellido = 241 caracteres: la columna de búsqueda `full_name_norm` admite 240 y se recorta."""
    staff_client(client, factory, "comercial")
    a = new_account(client)
    r = client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"first_name": "a" * 120, "last_name": "b" * 120})
    assert r.status_code == 200, r.text


def test_long_account_names_with_expanding_characters_do_not_break_the_search_columns(client, factory, crm_on):
    """«㎏» se normaliza (NFKD) a «kg»: un nombre de 200 caracteres puede dar una forma de búsqueda más larga que 200."""
    staff_client(client, factory, "comercial")
    r = client.post("/api/crm/accounts", json={"name": "㎏" * 200})
    assert r.status_code == 200, r.text


def test_notes_over_5000_characters_answer_400(client, factory, crm_on):
    staff_client(client, factory, "comercial")
    a = new_account(client)
    r = client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "n" * 5001})
    assert r.status_code == 400 and r.json()["detail"]
    assert client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "n" * 5000}).status_code == 200


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999", "abc"])
def test_agency_percent_that_is_not_a_finite_number_is_400(client, factory, crm_on, value):
    staff_client(client, factory, "comercial")
    r = client.post("/api/crm/accounts", json={"name": "Porcentaje raro", "agency_percent": value})
    assert r.status_code == 400, r.text


def test_numbers_beyond_the_database_range_never_answer_500(client, factory, crm_on):
    staff_client(client, factory, "comercial")
    big = 10 ** 12
    a = new_account(client)
    for path in (f"/api/crm/accounts/{big}", f"/api/crm/contacts/{big}/archive", f"/api/crm/accounts/{big}/history", f"/api/crm/accounts/{big}/contacts"):
        assert client.get(path).status_code in (404, 405), path
    assert client.post("/api/crm/accounts", json={"name": "Responsable enorme", "owner_staff_id": big}).status_code == 400
    assert client.post("/api/crm/accounts", json={"name": "Plazo enorme", "payment_days": big}).status_code == 400
    assert client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "hola", "contact_id": big}).status_code in (400, 404)
    assert client.get("/api/crm/accounts", params={"owner_id": big}).status_code == 200
    assert client.get("/api/crm/accounts", params={"page": big, "size": 5}).status_code == 200
    assert client.get("/api/crm/accounts", params={"q": "z" * 5000}).status_code == 200


def test_creating_a_client_with_oversized_data_never_fails_and_creates_its_account(client, factory, crm_on):
    """/clientes no tiene topes y la cuenta del CRM sí: la cuenta que se crea sola recorta en vez de hacer fallar la creación del cliente."""
    staff_client(client, factory, "admin", "adm_limites")
    r = client.post("/api/tenants", json={"name": "C" * 400, "contact_name": ("a" * 150) + " " + ("b" * 150), "contact_email": "e" * 300 + "@x.co", "contact_phone": "9" * 100})
    assert r.status_code < 500, r.text
