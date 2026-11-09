"""Gastos de infraestructura (Fase 9C): validación, moneda, reparto por evento, importación de Google, permisos y API."""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app import infra_costs as ic
from app.models import AccessLog, AuditAction, InfraCost
from tests.conftest import login


# ------------------------------------------------------------------ lógica pura
def test_clean_entry_cop_and_usd():
    e = ic.clean_entry({"month": "2026-11", "provider": "google", "concept": "  Cloud   Run ", "kind": "variable", "currency": "COP", "amount": "1.500,5".replace(".", "")})
    assert e["concept"] == "Cloud Run" and e["amount_cop"] == Decimal("1500.50") and e["trm"] is None
    u = ic.clean_entry({"month": "2026-11", "provider": "neon", "concept": "Neon", "currency": "usd", "amount": "19", "trm": "4100"})
    assert u["amount_cop"] == Decimal("77900.00") and u["trm"] == Decimal("4100.00")


@pytest.mark.parametrize("bad", [
    {"month": "2026-13", "provider": "google", "concept": "x", "amount": "1"},
    {"month": "2026-11", "provider": "aws", "concept": "x", "amount": "1"},
    {"month": "2026-11", "provider": "google", "concept": " ", "amount": "1"},
    {"month": "2026-11", "provider": "google", "concept": "x", "amount": "-5"},
    {"month": "2026-11", "provider": "google", "concept": "x", "amount": "abc"},
    {"month": "2026-11", "provider": "google", "concept": "x", "amount": "1", "currency": "USD"},
    {"month": "2026-11", "provider": "google", "concept": "x", "amount": "1", "kind": "raro"},
])
def test_clean_entry_rejects(bad):
    with pytest.raises(ic.InfraError):
        ic.clean_entry(bad)


def test_months_helpers():
    assert ic.month_add("2026-11", 2) == "2027-01" and ic.month_add("2026-01", -1) == "2025-12"
    assert ic.months_between("2026-10", "2026-12") == ["2026-10", "2026-11", "2026-12"]
    with pytest.raises(ic.InfraError):
        ic.months_between("2026-12", "2026-10")


def test_event_days_in_month():
    assert ic.event_days_in_month(date(2026, 10, 30), date(2026, 11, 2), "2026-10") == 2
    assert ic.event_days_in_month(date(2026, 10, 30), date(2026, 11, 2), "2026-11") == 2
    assert ic.event_days_in_month(date(2026, 11, 5), None, "2026-11") == 1
    assert ic.event_days_in_month(None, None, "2026-11") == 0
    assert ic.event_days_in_month(date(2026, 12, 1), date(2026, 12, 3), "2026-11") == 0


def test_allocate_auto_splits_variable_by_activity_and_fixed_by_days():
    costs = [{"month": "2026-11", "kind": "variable", "amount_cop": 1000}, {"month": "2026-11", "kind": "fixed", "amount_cop": 300}]
    r = ic.allocate(costs, {(1, "2026-11"): 30, (2, "2026-11"): 10}, {(1, "2026-11"): 1, (2, "2026-11"): 2}, "auto")
    assert r["events"][1]["variable"] == Decimal("750.00") and r["events"][2]["variable"] == Decimal("250.00")
    assert r["events"][1]["fixed"] == Decimal("100.00") and r["events"][2]["fixed"] == Decimal("200.00")
    assert sum(v["total"] for v in r["events"].values()) == Decimal("1300.00") and r["unassigned"] == {}


def test_allocate_bases_and_fallbacks():
    costs = [{"month": "2026-11", "kind": "fixed", "amount_cop": 100}, {"month": "2026-11", "kind": "variable", "amount_cop": 100}]
    only_days = ic.allocate(costs, {}, {(1, "2026-11"): 1, (2, "2026-11"): 1}, "auto")     # sin ingresos, lo variable cae a días
    assert only_days["events"][1]["total"] == Decimal("100.00") and not only_days["unassigned"]
    nothing = ic.allocate(costs, {}, {}, "auto")
    assert nothing["events"] == {} and nothing["unassigned"]["2026-11"] == Decimal(200)
    act = ic.allocate(costs, {(1, "2026-11"): 3, (2, "2026-11"): 1}, {(1, "2026-11"): 1, (2, "2026-11"): 9}, "activity")
    assert act["events"][1]["total"] == Decimal("150.00")
    days = ic.allocate(costs, {(1, "2026-11"): 3, (2, "2026-11"): 1}, {(1, "2026-11"): 1, (2, "2026-11"): 9}, "days")
    assert days["events"][2]["total"] == Decimal("180.00")


def test_allocate_rounding_never_loses_cents():
    r = ic.allocate([{"month": "2026-11", "kind": "variable", "amount_cop": 100}], {(i, "2026-11"): 1 for i in range(3)}, {}, "auto")
    assert sum(v["total"] for v in r["events"].values()) == Decimal("100.00")


def test_map_gcp_rows():
    rows = [{"invoice_month": "202611", "service": "Cloud Run", "currency": "COP", "net_cost": 5000},
            {"invoice_month": "202611", "service": "Cloud Storage", "currency": "USD", "net_cost": 2},
            {"invoice_month": "202611", "service": "Credito", "currency": "COP", "net_cost": -3},
            {"invoice_month": "x", "service": "Malo", "currency": "COP", "net_cost": 1}]
    out, warns = ic.map_gcp_rows(rows, None)
    assert [o["concept"] for o in out] == ["Cloud Run"] and len(warns) == 1
    out2, _ = ic.map_gcp_rows(rows, Decimal("4000"))
    assert {o["concept"]: o["amount_cop"] for o in out2}["Cloud Storage"] == Decimal("8000.00")


def test_import_google_idempotent_and_keeps_manual(db, monkeypatch):
    monkeypatch.setenv("GCP_BILLING_EXPORT_TABLE", "proj.dataset.gcp_billing_export_v1_X")
    calls = {"n": 5000}

    def q(table, month):
        return [{"invoice_month": month.replace("-", ""), "service": "Cloud Run", "currency": "COP", "net_cost": calls["n"]}]
    r1 = ic.import_google(db, "2026-11", query=q)
    assert r1["imported"] == 1
    calls["n"] = 6000
    r2 = ic.import_google(db, "2026-11", query=q)
    assert (r2["imported"], r2["updated"]) == (0, 1)
    rows = db.query(InfraCost).all()
    assert len(rows) == 1 and rows[0].amount_cop == Decimal("6000.00") and rows[0].source == "gcp_export"


def test_import_google_off_without_env(db, monkeypatch):
    monkeypatch.delenv("GCP_BILLING_EXPORT_TABLE", raising=False)
    assert ic.import_google(db)["configured"] is False


def test_gcp_table_rejects_injection(monkeypatch):
    monkeypatch.setenv("GCP_BILLING_EXPORT_TABLE", "a.b.c`; DROP TABLE x; --")
    with pytest.raises(ic.InfraError):
        ic.gcp_table()


def test_neon_usage_without_key_and_with_fake(monkeypatch):
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    assert ic.neon_usage("2026-11")["available"] is False
    monkeypatch.setenv("NEON_API_KEY", "k")
    monkeypatch.setenv("NEON_ORG_ID", "org-1")
    fake = {"projects": [{"project_id": "p", "periods": [{"consumption": [{"compute_time_seconds": 7200}, {"compute_time_seconds": 3600}]}]}]}
    r = ic.neon_usage("2026-11", fetch=lambda url: fake)
    assert r["available"] and r["compute_hours"] == 3.0 and r["projects"] == 1

    def boom(url):
        raise OSError("sin red")
    assert ic.neon_usage("2026-11", fetch=boom)["available"] is False


# ------------------------------------------------------------------ API y permisos
def _body(**kw):
    d = {"month": "2026-11", "provider": "google", "concept": "Cloud Run", "kind": "variable", "currency": "COP", "amount": "100000"}
    d.update(kw)
    return d


@pytest.mark.parametrize("role", ["coordinador", "comercial", "digitador"])
def test_non_admin_forbidden(client, factory, role):
    factory.staff(role, username="u1")
    login(client, "u1")
    assert client.get("/api/gastos/infra/summary").status_code == 403
    assert client.post("/api/gastos/infra/costs", json=_body()).status_code == 403
    assert client.get("/gastos").status_code == 302


def test_page_for_admin_and_anonymous(client, factory):
    assert client.get("/gastos").status_code == 302
    factory.staff("admin", username="adm")
    login(client, "adm")
    r = client.get("/gastos")
    assert r.status_code == 200 and "Infraestructura" in r.text and 'href="/gastos"' in r.text


def test_crud_flow_with_audit_and_attachment(client, factory, db):
    factory.staff("admin", username="adm")
    login(client, "adm")
    r = client.post("/api/gastos/infra/costs", json=_body(currency="USD", amount="10", trm="4000", kind="fixed"))
    assert r.status_code == 200 and r.json()["amount_cop"] == 40000
    cid = r.json()["id"]
    assert client.post("/api/gastos/infra/costs", json=_body(amount="x")).status_code == 400
    r = client.put(f"/api/gastos/infra/costs/{cid}", json=_body(amount="200000"))
    assert r.json()["amount_cop"] == 200000
    pdf = client.post(f"/api/gastos/infra/costs/{cid}/attachment", files={"file": ("f.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")})
    assert pdf.status_code == 200 and pdf.json()["has_attachment"]
    assert client.get(f"/api/gastos/infra/costs/{cid}/attachment").content.startswith(b"%PDF")
    assert client.post(f"/api/gastos/infra/costs/{cid}/attachment", files={"file": ("f.exe", io.BytesIO(b"MZ"), "application/octet-stream")}).status_code == 400
    assert client.post(f"/api/gastos/infra/costs/{cid}/attachment", files={"file": ("f.pdf", io.BytesIO(b"no es pdf"), "application/pdf")}).status_code == 400
    assert client.delete(f"/api/gastos/infra/costs/{cid}").json() == {"ok": True}
    assert client.get(f"/api/gastos/infra/costs/{cid}/attachment").status_code == 404
    actions = [a.action for a in db.query(AuditAction).filter_by(entity="infra_cost").order_by(AuditAction.id)]
    assert actions == ["create", "edit", "attach", "delete"]


def test_summary_allocates_by_event_and_ignores_test_person(client, factory, db):
    factory.staff("admin", username="adm")
    e1 = factory.event("finalizado", start_date=date(2026, 11, 3), end_date=date(2026, 11, 4))
    e2 = factory.event("finalizado", start_date=date(2026, 11, 10), end_date=date(2026, 11, 10))
    ts = datetime(2026, 11, 5, 15, 0)
    for i in range(3):
        db.add(AccessLog(tenant_id=e1.tenant_id, user_id=f"c{i}", timestamp=ts, event_id=e1.id))
    db.add(AccessLog(tenant_id=e2.tenant_id, user_id="d1", timestamp=ts, event_id=e2.id))
    for _ in range(50):
        db.add(AccessLog(tenant_id=e1.tenant_id, user_id="PRUEBA", timestamp=ts, event_id=e1.id))      # la persona de prueba no cuenta
    db.commit()
    login(client, "adm")
    client.post("/api/gastos/infra/costs", json=_body(amount="4000", kind="variable"))
    client.post("/api/gastos/infra/costs", json=_body(provider="domain", concept="Dominio", amount="300", kind="fixed"))
    s = client.get("/api/gastos/infra/summary?from=2026-10&to=2026-11").json()
    by = {e["event_id"]: e for e in s["events"]}
    assert by[e1.id]["variable"] == 3000 and by[e2.id]["variable"] == 1000          # 3 vs 1 ingresos
    assert by[e1.id]["fixed"] == 200 and by[e2.id]["fixed"] == 100                  # 2 vs 1 días
    assert s["grand_total"] == 4300 and s["unassigned"] == 0 and "formula" in s
    assert s["series"]["google"][-1] == 4000 and s["series"]["otros"][-1] == 300


def test_settings_and_export(client, factory):
    factory.staff("admin", username="adm")
    login(client, "adm")
    assert client.put("/api/gastos/infra/settings", json={"basis": "days", "trm_default": "4100"}).json() == {"basis": "days", "trm_default": 4100.0}
    assert client.put("/api/gastos/infra/settings", json={"basis": "otro"}).status_code == 400
    client.post("/api/gastos/infra/costs", json=_body(concept="=HYPERLINK(1)"))
    r = client.get("/api/gastos/infra/export.xlsx?from=2026-11&to=2026-11")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(r.content))["Gastos"]
    assert ws["C2"].value == "'=HYPERLINK(1)"
    assert client.get("/api/gastos/infra/summary?from=2026-12&to=2026-01").status_code == 400
