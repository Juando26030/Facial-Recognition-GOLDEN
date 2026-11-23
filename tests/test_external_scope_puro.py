"""Cuentas de otra empresa (SaaS): sin CRM ni Estado del sistema (23-nov-2026). Pruebas puras, sin base de datos."""
from pathlib import Path

from app import external_scope as x

ROOT = Path(__file__).resolve().parent.parent


def test_paginas_cerradas():
    for p in ("/sistema", "/crm", "/crm/cuentas", "/plataforma", "/gastos", "/cuentas-de-cobro"):
        assert x.page_blocked(p), p
    for p in ("/", "/clientes", "/eventos", "/calendario", "/configuracion", "/sistemas-no", "/crmx"):
        assert not x.page_blocked(p), p


def test_api_cerrada():
    for p in ("/api/ops/status", "/api/crm/accounts", "/api/gastos/infra/summary", "/api/gastos/eventos/panel", "/api/system-alerts", "/api/platform/orgs", "/api/payment-accounts", "/api/payment-accounts-forms"):
        assert x.api_blocked(p), p
    for p in ("/api/events", "/api/ops/version", "/api/staff"):
        assert not x.api_blocked(p), p


def test_cableado():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "async def external_gate" in main and 'session.get("staff_external")' in main
    assert 'request.session["staff_external"] = True' in (ROOT / "app/routers/auth.py").read_text(encoding="utf-8")
    side = (ROOT / "templates/_sidebar.html").read_text(encoding="utf-8")
    assert "not eo and not ext" in side and "and not ext %}" in side and side.count("not eo and not ext") >= 3
