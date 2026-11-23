"""Fase 4 (23-nov-2026): con ENFORCE_STAFF_TENANT=1, una cuenta de otra empresa no debe ver personal, servidores,
eventos/formularios ni alertas de Golden. Pruebas de texto (no necesitan base): confirman que cada lista lleva su filtro por cliente."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_coordinadores_y_comerciales_filtrados_por_cliente():
    s = _src("app/routers/staff.py")
    a = s.index("def list_coordinators")
    b = s.index("def list_commercials")
    c = s.index("def list_assignable_staff")
    assert "staff_tenant_enforced(staff)" in s[a:b] and "c.tenant_id == staff.tenant_id" in s[a:b]
    assert "staff_tenant_enforced(staff)" in s[b:c] and "StaffUser.tenant_id == staff.tenant_id" in s[b:c]


def test_servidores_locales_filtrados_por_cliente():
    s = _src("app/routers/nodes.py")
    a = s.index("def list_nodes")
    b = s.index('@router.post("/nodes")')
    assert "staff_tenant_enforced(staff)" in s[a:b] and "LocalNode.tenant_id == staff.tenant_id" in s[a:b]


def test_formularios_y_eventos_de_cuentas_de_pago_filtrados_por_cliente():
    s = _src("app/routers/payment_accounts.py")
    a = s.index("def forms_overview")
    body = s[a:a + 1800]
    assert body.count("Event.tenant_id == staff.tenant_id") == 2


def test_alertas_de_plataforma_cerradas_a_otras_empresas():
    s = _src("app/routers/system_alerts.py")
    assert "router = APIRouter(dependencies=[Depends(_solo_golden)])" in s
    assert "staff_tenant_enforced(staff)" in s[s.index("def _solo_golden"):s.index("router = APIRouter")]


def test_staging_enciende_el_aislamiento_y_produccion_no():
    d = _src("deploy/gcp/deploy.sh")
    assert 'if [ "$GOLDEN_ENV" = staging ]; then sed -i' in d and "ENFORCE_STAFF_TENANT" in d
    c = _src("deploy/gcp/env/common.yaml")
    assert 'ENFORCE_STAFF_TENANT: "0"' in c and 'ENFORCE_STAFF_EVENT_SCOPE: "0"' in c
