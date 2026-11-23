"""Correcciones de la revisión de la Fase 5 (23-nov-2026): A5 foto pendiente, E2 catálogo CRM, E3 revocar servidor, L2 candado de la baja local, cotización 204."""
from pathlib import Path

R = Path(__file__).resolve().parent.parent
T = lambda p: (R / p).read_text(encoding="utf-8-sig")


def test_a5_foto_nueva_borra_pendiente():
    assert "pending_photo_key(event.tenant_id, uid)" in T("app/routers/consents.py")
    api = T("app/routers/api.py")
    assert api.count("enroll_mod.pending_photo_key(") >= 2


def test_e2_e3_cuentas_externas():
    assert "staff_tenant_enforced(staff)" in T("app/routers/crm_inventory.py").split("def _guard")[1][:300]
    rv = T("app/routers/nodes.py").split("def revoke_node")[1][:500]
    assert "staff_tenant_enforced(staff) and node.tenant_id != staff.tenant_id" in rv


def test_l2_autodestruir_tiene_candado_antes_de_borrar():
    s = T("deploy/windows/autodestruir.ps1")
    llamada = s.index("& (Join-Path $ScriptsDir 'borrar-datos.ps1')")
    assert s.index("$envChk['SERVER_DISABLED']") < llamada and "exit 0" in s[:llamada]


def test_cotizacion_204_sin_cuerpo():
    q = T("app/routers/quote_request.py").split("def quote_preflight")[1][:400]
    assert "Response(status_code=" in q and "JSONResponse({}" not in q
