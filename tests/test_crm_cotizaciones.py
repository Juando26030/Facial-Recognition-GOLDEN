"""CRM C3: productos, condiciones, cotizaciones, versiones, PDF, proformas y supresión (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from app.models import CrmChangeLog, CrmQuote
from app.storage import get_storage
from tests.crm_helpers import crm_on, new_account, new_contact, seed_counters, staff_client  # noqa: F401

LINES = [{"name": "Escarapelas", "qty": "400", "unit_price": "3500", "discount_percent": "5", "tax_percent": "19"}, {"name": "Cordones", "qty": "400", "unit_price": "800"}]


def _quote(client, account_id, **extra):
    r = client.post("/api/crm/quotes", json={"account_id": account_id, "title": "Congreso 2027", "lines": LINES, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_a_quote_numbers_it_and_computes_totals_on_the_server(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    a = _quote(client, acc["id"], subtotal="1", total="1")          # lo que mande el navegador se ignora
    b = _quote(client, acc["id"])
    assert (a["number"], b["number"]) == (1, 2) and a["version"] == 1 and a["stage"] == "borrador" and a["currency"] == "COP"
    assert a["subtotal"] == "1650000.00" and a["discount_total"] == "70000.00" and a["tax_total"] == "313500.00" and a["total"] == "1963500.00"
    assert [ln["line_total"] for ln in a["lines"]] == ["1330000.00", "320000.00"] and [ln["position"] for ln in a["lines"]] == [1, 2]


def test_a_missing_quote_counter_is_a_409_and_bad_input_is_a_400(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    for body in ({"title": "x"}, {"account_id": acc["id"]}, {"account_id": acc["id"], "title": "x", "lines": [{"name": ""}]}, {"account_id": acc["id"], "title": "x", "currency": "EUR"},
                 {"account_id": acc["id"], "title": "x", "contact_id": 999999}, {"account_id": 999999, "title": "x"}):
        assert client.post("/api/crm/quotes", json=body).status_code in (400, 404), body
    seed_counters(db, ready=False)
    assert client.post("/api/crm/quotes", json={"account_id": acc["id"], "title": "x"}).status_code == 409


def test_editing_lines_recomputes_and_a_stale_version_is_a_409(client, factory, crm_on):
    staff_client(client, factory)
    q = _quote(client, new_account(client)["id"])
    ok = client.put(f"/api/crm/quotes/{q['id']}", json={"lines": [{"name": "Solo uno", "qty": "1", "unit_price": "1000"}], "updated_at": q["updated_at"]})
    assert ok.status_code == 200 and ok.json()["total"] == "1190.00" and len(ok.json()["lines"]) == 1
    assert client.put(f"/api/crm/quotes/{q['id']}", json={"title": "Otro", "updated_at": q["updated_at"]}).status_code == 409
    assert client.put(f"/api/crm/quotes/{q['id']}", json={"title": "Otro"}).status_code == 400


def test_stage_flow_sets_sent_at_and_a_new_version_copies_the_lines(client, factory, crm_on):
    staff_client(client, factory)
    q = _quote(client, new_account(client)["id"])
    sent = client.post(f"/api/crm/quotes/{q['id']}/stage", json={"stage": "enviada"}).json()
    assert sent["stage"] == "enviada" and sent["sent_at"]
    assert client.post(f"/api/crm/quotes/{q['id']}/stage", json={"stage": "borrador"}).status_code == 400
    v2 = client.post(f"/api/crm/quotes/{q['id']}/new-version").json()
    assert v2["number"] == q["number"] and v2["version"] == 2 and v2["stage"] == "borrador" and v2["total"] == q["total"] and len(v2["lines"]) == 2
    assert [v["version"] for v in v2["versions"]] == [1, 2] and client.get(f"/api/crm/quotes/{q['id']}").json()["stage"] == "enviada"


def test_meeting_notes_stay_out_of_the_history(client, factory, crm_on, db):
    staff_client(client, factory)
    q = _quote(client, new_account(client)["id"])
    client.put(f"/api/crm/quotes/{q['id']}", json={"meeting_notes": "Habló con Pedro Gómez", "title": "Nuevo título", "updated_at": q["updated_at"]})
    rows = {r.field_key: r for r in db.query(CrmChangeLog).filter_by(entity="quote", entity_id=q["id"]).all()}
    assert set(rows) == {"meeting_notes", "title"} and rows["meeting_notes"].new_value is None and rows["title"].new_value == "Nuevo título"


def test_the_pdf_is_generated_stored_and_dropped_when_the_quote_changes(client, factory, crm_on, db):
    staff_client(client, factory)
    q = _quote(client, new_account(client)["id"])
    r = client.get(f"/api/crm/quotes/{q['id']}/pdf")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content.startswith(b"%PDF")
    key = db.get(CrmQuote, q["id"]).pdf_key
    assert key.startswith("crm/quotes/") and get_storage().exists(key)
    client.put(f"/api/crm/quotes/{q['id']}", json={"title": "Cambió", "updated_at": client.get(f"/api/crm/quotes/{q['id']}").json()["updated_at"]})
    db.expire_all()
    assert db.get(CrmQuote, q["id"]).pdf_key is None and not get_storage().exists(key)


def test_a_proforma_needs_a_sent_quote_and_has_its_own_number_and_pdf(client, factory, crm_on):
    staff_client(client, factory)
    q = _quote(client, new_account(client)["id"])
    assert client.post(f"/api/crm/quotes/{q['id']}/proforma", json={}).status_code == 400          # sigue en borrador
    client.post(f"/api/crm/quotes/{q['id']}/stage", json={"stage": "aprobada"})
    p = client.post(f"/api/crm/quotes/{q['id']}/proforma", json={"due_at": "2026-12-31"}).json()
    assert p["number"] == 1 and p["total"] == q["total"] and p["status"] == "no_pagado" and p["event_name"] == "Congreso 2027"
    assert client.get(f"/api/crm/proformas/{p['id']}/pdf").content.startswith(b"%PDF")
    assert client.put(f"/api/crm/proformas/{p['id']}", json={"status": "pagado", "updated_at": p["updated_at"]}).json()["status"] == "pagado"
    assert [x["number"] for x in client.get("/api/crm/proformas").json()["items"]] == [1]


def test_products_terms_and_templates_are_admin_only_to_edit(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_cat")
    assert client.post("/api/crm/products", json={"name": "Escarapela"}).status_code == 403 and client.get("/api/crm/products").status_code == 200
    client.post("/logout")
    staff_client(client, factory, "admin", "adm_cat")
    p = client.post("/api/crm/products", json={"name": "Escarapela", "sku": "ESC-1", "price": "3500"}).json()
    assert p["tax_percent"] == "19.00" and client.post("/api/crm/products", json={"name": "Otra", "sku": "ESC-1"}).status_code == 409
    assert client.get("/api/crm/products?q=escarap").json()["total"] == 1
    t = client.post("/api/crm/terms", json={"name": "Contado", "body": "Pago de contado."}).json()
    tpl = client.post("/api/crm/doc-templates", json={"kind": "quote", "name": "Estándar", "greeting_text": "Estimados:"}).json()
    assert tpl["is_default"] is True and client.get("/api/crm/quotes/meta").json()["terms"][0]["id"] == t["id"]


def test_erasing_a_contact_clears_the_contact_and_the_stored_pdf_of_their_quotes(client, factory, crm_on, db):
    staff_client(client, factory, "admin", "adm_q1")
    acc = new_account(client)
    contact = new_contact(client, acc["id"], first_name="Lucía", last_name="Ficticia", email="lucia@ejemplo.test")
    q = _quote(client, acc["id"], contact_id=contact["id"])
    client.get(f"/api/crm/quotes/{q['id']}/pdf")
    key = db.get(CrmQuote, q["id"]).pdf_key
    r = client.post(f"/api/crm/contacts/{contact['id']}/erase", json={"reason": "solicitud", "confirm_name": "Lucía Ficticia"})
    assert r.status_code == 200 and r.json()["counts"]["quotes"] == 1
    db.expire_all()
    row = db.get(CrmQuote, q["id"])
    assert row is not None and row.contact_id is None and row.pdf_key is None and not get_storage().exists(key)


def test_erasing_an_account_removes_quotes_proformas_pdfs_and_history(client, factory, crm_on, db):
    staff_client(client, factory, "admin", "adm_q2")
    acc = new_account(client)
    q = _quote(client, acc["id"])
    client.post(f"/api/crm/quotes/{q['id']}/stage", json={"stage": "aprobada"})
    client.post(f"/api/crm/quotes/{q['id']}/proforma", json={})
    client.get(f"/api/crm/quotes/{q['id']}/pdf")
    key = db.get(CrmQuote, q["id"]).pdf_key
    r = client.post(f"/api/crm/accounts/{acc['id']}/erase", json={"reason": "solicitud", "confirm_name": acc["name"]})
    assert r.status_code == 200 and r.json()["counts"]["quotes"] == 1 and r.json()["counts"]["proformas"] == 1
    assert db.query(CrmQuote).count() == 0 and not get_storage().exists(key)
    assert db.query(CrmChangeLog).filter_by(entity="quote").count() == 0


def test_a_coordinator_cannot_use_the_quote_api(client, factory, crm_on):
    staff_client(client, factory, "coordinador", "coord_q")
    assert client.get("/api/crm/quotes").status_code == 403 and client.get("/api/crm/products").status_code == 403


def test_global_search_needs_two_characters_and_finds_across_types_without_accents(client, factory, crm_on):
    staff_client(client, factory)
    acc = new_account(client, "Cámara Ficticia de Comercio")
    new_contact(client, acc["id"], first_name="Lucía", last_name="Ficticia", email="lucia@ejemplo.test")
    _quote(client, acc["id"], title="Feria Cámara 2027")
    assert client.get("/api/crm/search?q=a").status_code == 400 and client.get("/api/crm/search?q=" + "x" * 101).status_code == 400
    r = client.get("/api/crm/search?q=camara").json()
    assert [a["name"] for a in r["accounts"]] == ["Cámara Ficticia de Comercio"] and [q["title"] for q in r["quotes"]] == ["Feria Cámara 2027"]
    assert client.get("/api/crm/search?q=lucia").json()["contacts"][0]["name"] == "Lucía Ficticia"
    assert client.get(f"/api/crm/search?q={acc['code']}").json()["accounts"][0]["id"] == acc["id"]
    assert client.get("/api/crm/search?q=zzzz").json() == {"accounts": [], "contacts": [], "opportunities": [], "quotes": [], "leads": []}


def test_saved_filters_keep_no_free_text_and_belong_to_their_owner(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_f1")
    f = client.post("/api/crm/filters", json={"scope": "cuentas", "name": "Activas de Bogotá", "filters": {"q": "Lucía", "status": "activo", "city": "Bogotá"}}).json()
    assert f["filters"] == {"status": "activo", "city": "Bogotá"} and f["mine"] is True
    shared = client.post("/api/crm/filters", json={"scope": "cuentas", "name": "Compartido", "filters": {"status": "activo"}, "shared": True}).json()
    client.post("/logout")
    staff_client(client, factory, "comercial", "com_f2")
    names = [x["name"] for x in client.get("/api/crm/filters?scope=cuentas").json()["items"]]
    assert names == ["Compartido"]                                   # los ajenos no compartidos no se ven
    assert client.delete(f"/api/crm/filters/{f['id']}").status_code == 403 and client.delete(f"/api/crm/filters/{shared['id']}").status_code == 403
    assert client.post("/api/crm/filters", json={"scope": "otra", "name": "x"}).status_code == 400


def test_export_is_admin_only_neutralises_formulas_and_audits_only_the_count(client, factory, crm_on, db):
    staff_client(client, factory, "comercial", "com_exp")
    assert client.get("/api/crm/export/cuentas").status_code == 403
    client.post("/logout")
    staff_client(client, factory, "admin", "adm_exp")
    new_account(client, "=HYPERLINK(\"http://x\")")
    r = client.get("/api/crm/export/cuentas")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.content.startswith(b"\xef\xbb\xbf") and "no-store" in r.headers["cache-control"]
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("codigo;nombre") and "'=HYPERLINK" in text and ";=HYPERLINK" not in text
    from app.models import AuditAction
    row = db.query(AuditAction).filter_by(action="export").one()
    assert row.detail == "1 filas" and "HYPERLINK" not in (row.entity_name or "")
    assert client.get("/api/crm/export/todo").status_code == 400
