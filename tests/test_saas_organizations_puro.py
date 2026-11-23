"""SaaS, pieza 1 (0162, docs/27_SAAS_EMPRESAS.md): pruebas PURAS y de texto, sin base (`python3 -m pytest --noconftest -q tests/test_saas_organizations_puro.py`).
Planes y límites (app/orgs.py), la migración, y que la pantalla respete las reglas del frontend (sin scripts en línea, sin alert, solo tokens)."""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _org(plan="basico", own=None, status="active", id=7):
    return SimpleNamespace(id=id, slug="x", name="X", plan=plan, entitlements_json=json.dumps(own) if own is not None else None, status=status)


# ------------------------------- planes y límites -------------------------------
def test_golden_is_never_limited_whatever_its_row_says():
    from app import orgs
    for golden in (None, _org(plan="basico", own={"events_per_month": 0}, status="suspended", id=1), SimpleNamespace(id=None)):
        assert orgs.is_internal(golden)
        assert orgs.entitlement(golden, "events_per_month") is None and orgs.entitlement(golden, "facial") is True
        assert orgs.check_limit(None, golden, "events_per_month", 10 ** 6) == (True, "")


def test_plan_defaults_and_own_overrides():
    from app import orgs
    assert orgs.entitlement(_org("basico"), "events_per_month") == 1
    assert orgs.entitlement(_org("pro"), "events_per_month") == 4 and orgs.entitlement(_org("pro"), "users") == 15
    assert orgs.entitlement(_org("empresa"), "events_per_month") is None
    assert orgs.entitlement(_org("basico", {"events_per_month": 3}), "events_per_month") == 3
    assert orgs.entitlement(_org("basico", {"events_per_month": None}), "events_per_month") is None          # clave en null = sin límite (no «lo del plan»)
    assert orgs.entitlement(_org("basico", {"facial": True}), "facial") is True
    assert orgs.entitlement(_org("plan-que-no-existe"), "users") == orgs.PLANS["basico"]["users"]
    with pytest.raises(KeyError):
        orgs.entitlement(_org(), "no_existe")
    assert set(orgs.entitlements(_org())) == set(orgs.KEYS)
    assert set(orgs.PLANS) == {"interno", "basico", "pro", "empresa"} and "interno" not in orgs.SELLABLE_PLANS
    for plan in orgs.PLANS.values():
        assert set(orgs.KEYS) <= set(plan)


def test_check_limit_messages_are_in_spanish_and_say_what_to_do():
    from app import orgs
    assert orgs.check_limit(None, _org("pro"), "events_per_month", 3) == (True, "")
    ok, msg = orgs.check_limit(None, _org("pro"), "events_per_month", 4)
    assert not ok and msg == "Tu plan permite 4 eventos por mes; contacta a soporte"
    assert orgs.check_limit(None, _org("basico"), "events_per_month", 1)[1] == "Tu plan permite 1 evento por mes; contacta a soporte"
    ok, msg = orgs.check_limit(None, _org("basico"), "users", 9)
    assert not ok and msg == "Tu plan permite 5 usuarios; contacta a soporte"
    assert orgs.check_limit(None, _org("empresa"), "events_per_month", 999) == (True, "")
    ok, msg = orgs.check_limit(None, _org("basico"), "facial")
    assert not ok and "no incluye reconocimiento facial" in msg and "contacta a soporte" in msg
    assert orgs.check_limit(None, _org("pro"), "facial") == (True, "")
    ok, msg = orgs.check_limit(None, _org("empresa", status="suspended"), "events_per_month", 0)
    assert not ok and "suspendida" in msg


def test_broken_or_odd_entitlements_fall_back_to_the_plan():
    from app import orgs
    for raw in ("", "no es json", "[1, 2]", "42", None):
        org = SimpleNamespace(id=7, plan="pro", entitlements_json=raw, status="active")
        assert orgs.entitlement(org, "events_per_month") == 4


def test_clean_entitlements_accepts_only_known_keys_and_sane_values():
    from app import orgs
    assert orgs.clean_entitlements({"events_per_month": "6", "users": None, "facial": True, "attendees_per_event": ""}) == {"events_per_month": 6, "users": None, "facial": True, "attendees_per_event": None}
    assert orgs.clean_entitlements(None) == {}
    for bad in ({"otra": 1}, {"users": -1}, {"users": "muchos"}, {"users": True}, {"users": 1.5}, {"facial": "si"}, {"facial": 1}):
        with pytest.raises(ValueError):
            orgs.clean_entitlements(bad)


def test_slug_temp_password_and_month_start():
    from datetime import datetime
    from app import orgs
    assert orgs.slugify("Eventos del Caribe S.A.S.") == "eventos-del-caribe-s-a-s"
    assert orgs.slugify("  Ñandú & Cía  ") == "nandu-cia"
    assert orgs.SLUG_RE.fullmatch("eventos-del-caribe") and not orgs.SLUG_RE.fullmatch("Con Espacios") and not orgs.SLUG_RE.fullmatch("-x")
    seen = {orgs.temp_password() for _ in range(50)}
    assert len(seen) == 50
    for value in seen:
        assert len(value) == 14 and any(c.isdigit() for c in value) and any(c.islower() for c in value) and any(c.isupper() for c in value)          # (con las reglas reales: prueba con base)
    assert orgs.month_start(datetime(2026, 11, 22, 15, 30)) == datetime(2026, 11, 1)


def test_external_accounts_need_the_isolation_switch(monkeypatch):
    from app import orgs
    monkeypatch.delenv("ENFORCE_STAFF_TENANT", raising=False)
    assert orgs.external_accounts_ready() is False and orgs.catalog()["external_accounts_ready"] is False
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    assert orgs.external_accounts_ready() is True
    cat = orgs.catalog()
    assert [k["key"] for k in cat["keys"]] == list(orgs.KEYS) and all(k["help"] and k["label"] for k in cat["keys"])


def test_current_org_without_org_id_is_golden_without_a_database():
    from app import orgs
    for user in (SimpleNamespace(org_id=None), SimpleNamespace(org_id=1), SimpleNamespace()):
        assert orgs.is_internal(orgs.current_org(user))
    assert orgs.is_internal(orgs.org_for_tenant(None, SimpleNamespace(org_id=None)))          # db=None: Golden no consulta nada


# ------------------------------- migración y modelos (texto) -------------------------------
def test_migration_is_additive_short_id_and_pooler_safe():
    src = _read("alembic/versions/0162_organizations.py")
    tree = ast.parse(src)
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("revision", "down_revision")}
    assert values == {"revision": "0162_organizations", "down_revision": "0161_inventario_por_base"} and len(values["revision"]) <= 32
    code = "\n".join(line for line in src.split('"""', 2)[2].splitlines())
    assert not re.search(r"\bSET\s+(SESSION|search_path|LOCAL)\b|pg_advisory|LISTEN|NOTIFY|TEMP(ORARY)?\s+TABLE", code, re.I)
    assert "drop_column" not in code.split("def downgrade")[0] and "drop_table" not in code.split("def downgrade")[0]
    assert "'golden'" in code and "'interno'" in code and 'server_default="1"' in code
    assert 'for table in ("tenants", "staff_users")' in code          # SOLO esas dos tablas en esta pieza
    assert "def downgrade" in code and "drop_table" in code.split("def downgrade")[1]


def test_models_carry_org_id_only_on_tenants_and_staff_users():
    src = _read("app/models.py")
    assert "class Organization(Base):" in src and "__tablename__ = 'organizations'" in src
    assert src.count("org_id = Column(Integer, nullable=True, default=1, server_default='1', index=True)") == 2
    org = src.split("class Organization(Base):")[1].split("\nclass ")[0]
    for col in ("id", "slug", "name", "legal_name", "nit", "contact_email", "contact_phone", "plan", "entitlements_json", "status", "created_at", "notes"):
        assert re.search(rf"^    {col} = Column\(", org, re.M), col
    assert "ForeignKey('organizations" not in src          # sin llave foránea en esta pieza (la base de pruebas vacía `organizations` en cada prueba)


def test_pure_logic_imports_without_sqlalchemy():
    head = _read("app/orgs.py").split("# ------------------------------- consultas")[0]
    assert not re.search(r"^(from|import) (sqlalchemy|app\.models)", head, re.M)


# ------------------------------- rutas, pantalla y configuración (texto) -------------------------------
def test_platform_routes_are_sync_and_super_admin_only():
    src = _read("app/routers/platform.py")
    assert "async def" not in src and 'APIRouter(prefix="/api/platform")' in src
    tree = ast.parse(src)
    routes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(isinstance(d, ast.Call) and getattr(d.func, "value", None) is not None and getattr(d.func.value, "id", "") == "router" for d in n.decorator_list)]
    assert len(routes) >= 7
    for fn in routes:
        assert "require_super_admin" in ast.unparse(fn.args), fn.name
    main = _read("app/main.py")
    assert "_include(platform_router.router)" in main
    page = main.split('@app.get("/plataforma")')[1].split("@app.get(")[0]
    assert '_require_page_role(request, "super_admin")' in page and 'name="plataforma.html"' in page


def test_install_route_was_retired():
    """/instalar se retiró el 22-nov-2026 (decisión de Juan David): el primer super_admin se crea con scripts/create_staff_user.py."""
    assert "/instalar" not in _read("app/routers/platform.py").replace("(/instalar) se retiró", "") and "platform_router.pages" not in _read("app/main.py")
    assert not (ROOT / "templates/instalar.html").exists() and not (ROOT / "static/js/instalar.js").exists()


def test_event_creation_checks_the_monthly_limit_before_creating_anything():
    src = _read("app/routers/events.py")
    body = src.split("def create_event(")[1].split("\n@router.")[0]
    check = body.index('orgs.check_limit(db, orgs.org_for_tenant(db, tenant_row), "events_per_month")')
    assert check < body.index("event_codes.next_code(db)") and "status_code=403, detail=limit_message" in body


@pytest.mark.parametrize("template", ["templates/plataforma.html"])
def test_pages_follow_the_frontend_rules(template):
    html = _read(template)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "sin scripts en línea (CSP)"
    assert not re.search(r"\son[a-z]+\s*=", html), "sin manejadores en línea"
    assert "<style" not in html and "style=" not in html, "nada de estilos sueltos: solo clases .gw-*"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b(?![^<]*</use>)", re.sub(r"#i-[a-z-]+", "", html)), "nada de colores sueltos"
    assert 'src="/static' not in html and 'href="/static' not in html          # siempre url_for('static', …)
    assert html.count("{% call ayuda(") >= 4 and "data-gw-help-btn" in html          # principio «dummy»: ayuda ⓘ en cada opción
    for field in re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html):
        assert f'for="{field}"' in html, f"el campo {field} no tiene etiqueta"


@pytest.mark.parametrize("script", ["static/js/plataforma.js"])
def test_scripts_use_toast_helpers_and_never_innerhtml(script):
    js = _read(script)
    assert not re.search(r"\b(alert|confirm|prompt)\s*\(", re.sub(r"show(Confirm|Prompt)\s*\(", "", js))
    assert "showToast(" in js and "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert not re.search(r"#[0-9a-fA-F]{6}\b", js)


def test_org_form_does_not_close_on_outside_click_and_password_shows_once():
    js = _read("static/js/plataforma.js")
    assert "gw-modal-backdrop')" in js and not re.search(r"e\.target\s*===\s*(orgModal|adminModal|passModal)", js)          # se cierra solo con sus botones
    assert "getElementById('passValue').textContent = ''" in js and "showConfirm(" in js
    assert "localStorage" not in js and "sessionStorage" not in js


def test_sidebar_entry_only_for_super_admin_in_the_cloud():
    line = next(ln for ln in _read("templates/_sidebar.html").splitlines() if "Empresas (SaaS)" in ln)
    assert 'href="/plataforma"' in line and 'staff_role == "super_admin"' in line and "not eo and not local_server" in line


def test_isolation_switches_are_written_down_as_off_with_the_warning():
    yaml = _read("deploy/gcp/env/common.yaml")
    assert re.search(r'^ENFORCE_STAFF_TENANT: "0"$', yaml, re.M) and re.search(r'^ENFORCE_STAFF_EVENT_SCOPE: "0"$', yaml, re.M)
    env = _read(".env.example")
    assert re.search(r"^ENFORCE_STAFF_TENANT=0$", env, re.M) and re.search(r"^ENFORCE_STAFF_EVENT_SCOPE=0$", env, re.M)
    for text in (yaml, env):
        assert re.search(r"DEBEN ir en \"?1\"? ANTES de dar una cuenta a OTRA empresa", text)


def test_the_event_only_coordinator_cannot_call_the_platform_api():
    """La lista de rutas PERMITIDAS del coordinador temporal (app/event_only.py) no incluye nada de la plataforma; la página /plataforma la cierra su propia regla de super_admin."""
    src = _read("app/event_only.py")
    assert "/api/platform" not in src and "/instalar" not in src
