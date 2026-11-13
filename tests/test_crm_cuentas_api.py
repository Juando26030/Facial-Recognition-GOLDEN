"""CRM C1b-1: API de cuentas (alta, edición con control de versión, búsqueda sin tildes, filtros, archivar). Necesitan PostgreSQL."""
from app import models as m
from app.crm import normalize
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def test_everything_is_404_while_the_crm_is_off(client, factory, monkeypatch):
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    staff_client(client, factory, "admin")
    for method, url in (("get", "/api/crm/accounts"), ("get", "/api/crm/meta"), ("post", "/api/crm/accounts"), ("get", "/api/crm/accounts/1")):
        assert getattr(client, method)(url).status_code == 404


def test_create_assigns_consecutive_codes_and_normalized_name(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client, "Ingeniería Ñandú S.A.S.")
    b = new_account(client, "Otra Empresa")
    assert (a["code"], b["code"]) == (1001, 1002)
    row = db.get(m.CrmAccount, a["id"])
    assert row.name_norm == normalize("Ingeniería Ñandú S.A.S.") == "ingenieria nandu s.a.s." and row.status == "activo" and row.created_by_id is not None
    assert db.query(m.CrmChangeLog).count() == 0                                          # el alta no es un cambio


def test_a_failed_create_does_not_burn_a_number(client, factory, crm_on):
    staff_client(client, factory)
    assert client.post("/api/crm/accounts", json={"name": "  "}).status_code == 400
    assert client.post("/api/crm/accounts", json={"name": "Valida", "status": "raro"}).status_code == 400
    assert new_account(client, "Primera")["code"] == 1001


def test_counter_not_ready_gives_409(client, factory, monkeypatch, db):
    from tests.crm_helpers import seed_counters
    monkeypatch.setenv("CRM_ENABLED", "1")
    seed_counters(db, ready=False)
    staff_client(client, factory)
    r = client.post("/api/crm/accounts", json={"name": "Nueva"})
    assert r.status_code == 409 and "contador" in r.json()["detail"]


def test_duplicate_name_ignoring_accents_needs_confirmation(client, factory, crm_on):
    staff_client(client, factory)
    new_account(client, "Cámara de Comercio")
    r = client.post("/api/crm/accounts", json={"name": "CAMARA  de comercio"})
    assert r.status_code == 409 and "1001" in r.json()["detail"]
    assert client.post("/api/crm/accounts", json={"name": "CAMARA  de comercio", "confirm_duplicate": True}).json()["code"] == 1002


def test_validation_messages(client, factory, crm_on):
    staff_client(client, factory)
    for payload in ({"name": "X", "email": "no-es-correo"}, {"name": "X", "payment_days": 400}, {"name": "X", "payment_days": "abc"}, {"name": "X", "agency_percent": 101},
                    {"name": "X", "agency_percent": "mucho"}, {"name": "X", "owner_staff_id": 999999}, {"name": "X", "owner_staff_id": "abc"}, {"name": "x" * 201}):
        r = client.post("/api/crm/accounts", json=payload)
        assert r.status_code == 400 and isinstance(r.json()["detail"], str), payload          # SIEMPRE 400 con mensaje en español (nunca el 422 de FastAPI con lista en inglés)
    assert "días de plazo" in client.post("/api/crm/accounts", json={"name": "X", "payment_days": "abc"}).json()["detail"]
    assert "responsable" in client.post("/api/crm/accounts", json={"name": "X", "owner_staff_id": "abc"}).json()["detail"]
    ok = new_account(client, "Con datos", agency_percent=12.5, payment_days=30, nit="900.123.456-1", billing_city="Bogotá")
    assert ok["agency_percent"] == "12.50" and ok["payment_days"] == 30


def test_update_needs_the_version_and_detects_a_concurrent_edit(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client, "Original")
    assert client.put(f"/api/crm/accounts/{a['id']}", json={"name": "Sin versión"}).status_code == 400
    ok = client.put(f"/api/crm/accounts/{a['id']}", json={"name": "Cambiada", "billing_city": "Cali", "updated_at": a["updated_at"]})
    assert ok.status_code == 200 and ok.json()["name"] == "Cambiada" and ok.json()["updated_at"] != a["updated_at"]
    stale = client.put(f"/api/crm/accounts/{a['id']}", json={"name": "Pisada", "updated_at": a["updated_at"]})          # la versión vieja
    assert stale.status_code == 409 and "Recarga" in stale.json()["detail"]
    row = db.get(m.CrmAccount, a["id"])
    assert row.name == "Cambiada" and row.name_norm == "cambiada"
    log = {(r.field_key, r.old_value, r.new_value, r.source) for r in db.query(m.CrmChangeLog).filter_by(entity="account", entity_id=a["id"])}
    assert log == {("name", "Original", "Cambiada", "edit"), ("billing_city", None, "Cali", "edit")}
    assert all(r.changed_by_id is not None for r in db.query(m.CrmChangeLog))


def test_saving_without_changes_leaves_no_history_and_keeps_the_version(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client, "Igual", billing_city="Cali")
    r = client.put(f"/api/crm/accounts/{a['id']}", json={"name": "Igual", "billing_city": "Cali", "updated_at": a["updated_at"]})
    assert r.status_code == 200 and r.json()["updated_at"] == a["updated_at"] and db.query(m.CrmChangeLog).count() == 0


def test_search_without_accents_by_name_code_nit_and_contact(client, factory, crm_on):
    staff_client(client, factory)
    cam = new_account(client, "Cámara de Comercio de Bogotá", nit="900.123.456-1")
    new_account(client, "Bavaria S.A.")
    new_contact(client, cam["id"], "José", "Pérez", email="Jose.Perez@camara.org")

    def codes(q, **kw):
        return sorted(i["code"] for i in client.get("/api/crm/accounts", params={"q": q, **kw}).json()["items"])
    assert codes("camara") == codes("CÁMARA") == codes("  cámara   de comercio ") == [1001]
    assert codes("bogota") == [1001] and codes("zzz") == []
    assert codes("1002") == [1002] and codes("9001234561") == codes("900.123.456-1") == [1001]          # código exacto y NIT sin puntos ni guiones
    assert codes("perez") == codes("José pérez") == codes("jose.perez@camara") == [1001]               # por contacto
    assert codes("%") == [] and codes("_") == []                                                        # los comodines de LIKE no se cuelan
    assert codes("") == [1001, 1002]


def test_filters_pagination_and_archived(client, factory, crm_on):
    staff_client(client, factory, "admin")
    for i in range(7):
        new_account(client, f"Empresa {i:02d}", status="inactivo" if i % 2 else "activo", billing_city="Cali" if i < 3 else "Bogotá")
    page = client.get("/api/crm/accounts", params={"size": 3, "page": 3}).json()
    assert page["total"] == 7 and [i["name"] for i in page["items"]] == ["Empresa 06"] and page["size"] == 3
    assert client.get("/api/crm/accounts", params={"status": "inactivo"}).json()["total"] == 3
    assert client.get("/api/crm/accounts", params={"city": "Cali"}).json()["total"] == 3
    first = client.get("/api/crm/accounts", params={"size": 1}).json()["items"][0]
    assert client.post(f"/api/crm/accounts/{first['id']}/archive").status_code == 200
    assert client.get("/api/crm/accounts").json()["total"] == 6 and client.get("/api/crm/accounts", params={"archived": "true"}).json()["total"] == 1
    assert client.post(f"/api/crm/accounts/{first['id']}/archive").status_code == 400          # ya archivada
    assert client.post(f"/api/crm/accounts/{first['id']}/restore").status_code == 200 and client.get("/api/crm/accounts").json()["total"] == 7


def test_list_shows_the_primary_contact_and_client_flag(client, factory, crm_on):
    staff_client(client, factory)
    a = new_account(client, "Con contacto")
    new_contact(client, a["id"], "Ana", "Pérez")
    item = client.get("/api/crm/accounts").json()["items"][0]
    assert item["primary_contact"] == "Ana Pérez" and item["is_client"] is False


def test_meta_lists_statuses_owners_and_used_values(client, factory, crm_on):
    staff_client(client, factory)
    factory.staff("coordinador", "coord_no")
    new_account(client, "Una", billing_city="Cali", payment_term="30 días")
    meta = client.get("/api/crm/meta").json()
    assert meta["statuses"] == ["activo", "inactivo", "masivo"] and meta["cities"] == ["Cali"] and meta["payment_terms"] == ["30 días"]
    assert all(o["name"] for o in meta["owners"]) and len(meta["owners"]) == 1          # el coordinador no es responsable posible


def test_notes_and_history_endpoints(client, factory, crm_on):
    me = staff_client(client, factory)
    a = new_account(client, "Con notas")
    c = new_contact(client, a["id"])
    assert client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "  "}).status_code == 400
    n1 = client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "Primera llamada"}).json()
    n2 = client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "Sobre Ana", "contact_id": c["id"]}).json()
    assert [n["body"] for n in client.get(f"/api/crm/accounts/{a['id']}/notes").json()] == ["Sobre Ana", "Primera llamada"]
    other = new_account(client, "Otra")
    assert client.post(f"/api/crm/accounts/{other['id']}/notes", json={"body": "x", "contact_id": c["id"]}).status_code == 400          # el contacto es de otra cuenta
    assert client.delete(f"/api/crm/notes/{n1['id']}").status_code == 200
    assert client.delete(f"/api/crm/notes/{n2['id']}").status_code == 200
    client.put(f"/api/crm/accounts/{a['id']}", json={"billing_city": "Cali", "updated_at": a["updated_at"]})
    hist = client.get(f"/api/crm/accounts/{a['id']}/history").json()
    assert hist[0]["field"] == "billing_city" and hist[0]["new"] == "Cali" and hist[0]["by"] == me.full_name
    assert client.get("/api/crm/accounts/99999/history").status_code == 404
