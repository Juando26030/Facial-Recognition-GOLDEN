"""CRM C1b-1: pruebas SIN base de datos (corren con `python3 -m pytest -q --noconftest tests/test_crm_c1b_texto.py`): reconocer a una persona en los campos de la cuenta, reparto de rutas
por servicio, despliegue (CRM_ENABLED por entorno, también en manual_deploy.sh) y reglas de código que no se pueden romper."""
import pathlib
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app import appmode
from app.crm.matching import identifiers, mentions, value_matches

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _contact(**kw):
    base = dict(first_name="Ana", last_name="Pérez", email="Ana.Perez@Empresa.com", phone="601 555 1234", mobile="+57 300 123 4567")
    base.update(kw)
    return SimpleNamespace(**base)


# ------------------------------------------------------------------ reconocer a la persona (supresión)
def test_identifiers_normalize_name_email_and_phones():
    ids = identifiers(_contact())
    assert ids["name"] == "ana perez" and ids["emails"] == {"ana.perez@empresa.com"} and ids["phones"] == {"6015551234", "573001234567"}


def test_short_phones_are_not_identifiers():
    assert identifiers(_contact(phone="123", mobile=None))["phones"] == set()


@pytest.mark.parametrize("field,value,expected", [
    ("billing_contact_name", "ANA PÉREZ", True), ("billing_contact_name", "Ana Pérez - Gerente", True), ("billing_contact_name", "Gerente: ana  perez", True),
    ("billing_contact_name", "Anabel Pérez", False), ("billing_contact_name", "Ana Gómez", False), ("billing_contact_name", None, False),
    ("email", "ana.perez@empresa.com", True), ("email", " ANA.PEREZ@EMPRESA.COM ", True), ("email", "otra@empresa.com", False),
    ("phone", "3001234567", True), ("phone", "+57 (300) 123-4567", True), ("phone", "555 1234", True), ("phone", "601 555 1234", True), ("phone", "300", False),
    ("billing_contact_phone", "573001234567", True), ("billing_contact_phone", "3109999999", False),
    ("description", "ana perez", False),          # el texto libre nunca se decide por valor: solo se avisa (mentions)
])
def test_value_matches_by_field(field, value, expected):
    assert value_matches(field, value, identifiers(_contact())) is expected


def test_a_single_given_name_only_matches_the_exact_field():
    ids = identifiers(_contact(last_name=None, email=None, phone=None, mobile=None))
    assert value_matches("billing_contact_name", "Ana", ids) is True
    assert value_matches("billing_contact_name", "Banana", ids) is False and value_matches("billing_contact_name", "Ana María", ids) is False


def test_mentions_in_free_text():
    ids = identifiers(_contact())
    assert mentions("Hablar con Ana Pérez el lunes", ids) and mentions("escribir a ana.perez@empresa.com", ids)
    assert not mentions("Hablar con Anabel Gómez", ids) and not mentions(None, ids) and not mentions("", ids)


# ------------------------------------------------------------------ reparto de rutas por servicio
@pytest.mark.parametrize("path", ["/api/crm/accounts", "/api/crm/accounts/5/contacts", "/api/crm/contacts/3/erase", "/crm", "/crm/cuentas/5"])
def test_crm_routes_belong_to_web_and_all_only(path):
    assert appmode.route_allowed(path, mode="web") and appmode.route_allowed(path, mode="all")
    assert not appmode.route_allowed(path, mode="publico") and not appmode.route_allowed(path, mode="biometria")


# ------------------------------------------------------------------ despliegue: CRM_ENABLED por entorno
def test_config_sh_staging_on_production_off_by_default():
    cfg = _read("deploy/gcp/config.sh")
    assert re.search(r'if \[ "\$GOLDEN_ENV" = production \]; then CRM_ENABLED="\$\{CRM_ENABLED:-0\}"; else CRM_ENABLED="\$\{CRM_ENABLED:-1\}"; fi', cfg)


def test_deploy_sh_writes_crm_enabled_only_to_the_web_service():
    dep = _read("deploy/gcp/deploy.sh")
    lines = [ln for ln in dep.splitlines() if '"CRM_ENABLED=$CRM_ENABLED"' in ln]
    assert len(lines) == 1 and lines[0].startswith("deploy_service web ")
    assert "CRM_ENABLED" not in _read("deploy/gcp/env/common.yaml")           # común a los tres servicios y a los Jobs: NO va ahí


def test_manual_deploy_goes_through_deploy_sh_and_shows_the_crm_switch():
    man = _read("deploy/gcp/manual_deploy.sh")
    assert 'bash deploy/gcp/deploy.sh "$ENV_NAME" "$IMAGE"' in man and 'source deploy/gcp/config.sh "$ENV_NAME"' in man
    assert 'echo "CRM_ENABLED=$CRM_ENABLED' in man and "ENCENDER el CRM en PRODUCCIÓN" in man
    assert man.index('source deploy/gcp/config.sh') < man.index('echo "CRM_ENABLED=')


@pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash")
@pytest.mark.parametrize("script", ["config.sh", "deploy.sh", "manual_deploy.sh"])
def test_deploy_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "gcp" / script)], capture_output=True).returncode == 0


# ------------------------------------------------------------------ reglas de código
def test_crm_router_has_no_async_endpoints_and_guards_every_route():
    src = _read("app/routers/crm.py")
    assert "async def" not in src
    assert 'dependencies=[Depends(_require_crm_enabled)]' in src          # apagado = 404 en TODAS las rutas
    routes = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"\)\ndef (\w+)\((.*?)\):\n', src, re.S)
    assert len(routes) >= 20
    for _method, path, name, args in routes:
        assert "view_staff" in args or "admin_staff" in args, f"{name} sin permiso"
    for name in ("archive_account", "restore_account", "erase_account_route", "erase_contact_route"):
        sig = re.search(rf"def {name}\((.*?)\):\n", src, re.S).group(1)
        assert "admin_staff" in sig and "view_staff" not in sig, f"{name} debe ser solo de admin+"


def test_roles_are_comercial_for_view_and_admin_for_dangerous_actions():
    src = _read("app/routers/crm.py")
    assert 'view_staff = require_platform_role("comercial")' in src and 'admin_staff = require_platform_role("admin")' in src


def test_normalized_columns_are_written_only_by_the_crm_door():
    allowed = {"app/crm/accounts.py", "app/routers/tenants.py", "app/models.py"}
    for path in (ROOT / "app").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\b(name_norm|full_name_norm|email_norm)\s*=", text) and rel not in allowed and not rel.startswith("app/crm/"):
            pytest.fail(f"{rel} escribe columnas normalizadas del CRM fuera de app/crm/accounts.py")


def test_tenants_router_keeps_the_crm_rules():
    src = _read("app/routers/tenants.py")
    assert "_create_crm_account(db, staff, tenant)" in src and "int(tenant.client_code)" in src          # D2: mismo número
    assert "tenant_contact_locked(db, tenant.id)" in src and "status_code=409" in src                    # D3
    assert src.index("if crm_enabled():") < src.index("_create_crm_account(db, staff, tenant)")


def test_erase_never_writes_history_with_personal_values():
    src = _read("app/crm/erase.py")
    assert "CrmChangeLog(" not in src and "history.record" not in src          # limpiar un campo NO deja el valor anterior en el historial
    assert "audit_actions" not in src                                          # la auditoría la escribe el router, solo con conteos


def test_no_inline_handlers_or_native_dialogs_in_crm_sources():
    for rel in ("app/routers/crm.py", "app/crm/accounts.py"):
        assert "alert(" not in _read(rel) and "onclick" not in _read(rel)


# ------------------------------------------------------------------ límites de longitud (sin base de datos)
def _column_lengths(cls_name):
    """{columna: N} de `Column(String(N))` dentro de la clase de app/models.py (las `Text` y `String` sin número no tienen tope)."""
    src = _read("app/models.py")
    start = src.index(f"class {cls_name}(")
    nxt = src.find("\nclass ", start + 5)
    body = src[start: nxt if nxt != -1 else len(src)]
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^\s+(\w+)\s*=\s*Column\(String\((\d+)\)", body, re.M)}


def _limits():
    """ACCOUNT_LIMITS, CONTACT_LIMITS y NORM_MAX leídos del código fuente (sin importar sqlalchemy, que estas pruebas no necesitan)."""
    import ast
    tree = ast.parse(_read("app/crm/accounts.py"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") in ("ACCOUNT_LIMITS", "CONTACT_LIMITS", "NORM_MAX"):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return SimpleNamespace(**found)


def test_api_limits_equal_the_column_lengths_of_the_models():
    svc = _limits()
    acc, con = _column_lengths("CrmAccount"), _column_lengths("CrmContact")
    for key, limit in svc.ACCOUNT_LIMITS.items():
        if key == "description":
            assert key not in acc                       # Text: sin tope en la base; la API lo limita a 20.000
            continue
        assert acc.get(key) == limit, f"CrmAccount.{key}: API {limit} vs columna {acc.get(key)}"
    for key, limit in svc.CONTACT_LIMITS.items():
        if key == "notes":
            assert key not in con
            continue
        assert con.get(key) == limit, f"CrmContact.{key}: API {limit} vs columna {con.get(key)}"


def test_every_bounded_column_that_a_person_can_type_has_an_api_limit():
    """Si alguien agrega una columna con tope a CrmAccount/CrmContact y se olvida de ponerla en ACCOUNT_LIMITS/CONTACT_LIMITS, esta prueba lo dice."""
    svc = _limits()
    internal_account = {"tenant_id", "status", "name_norm", "legacy_sugar_id"}
    internal_contact = {"full_name_norm", "email_norm", "legacy_sugar_id"}
    for col in set(_column_lengths("CrmAccount")) - internal_account:
        assert col in svc.ACCOUNT_LIMITS, f"CrmAccount.{col} tiene tope en la base pero no en la API"
    for col in set(_column_lengths("CrmContact")) - internal_contact:
        assert col in svc.CONTACT_LIMITS, f"CrmContact.{col} tiene tope en la base pero no en la API"


def test_search_columns_are_clipped_to_their_length():
    svc = _limits()
    acc, con = _column_lengths("CrmAccount"), _column_lengths("CrmContact")
    assert svc.NORM_MAX == {"name_norm": acc["name_norm"], "full_name_norm": con["full_name_norm"], "email_norm": con["email_norm"]}
    src = _read("app/crm/accounts.py")
    for key in svc.NORM_MAX:
        assert f'NORM_MAX["{key}"]' in src, f"{key} se escribe sin recortar"


def test_route_has_a_safety_net_for_database_data_errors():
    src = _read("app/routers/crm.py")
    assert "except DataError" in src and "status_code=400" in src.split("except DataError", 1)[1][:300]
    assert "_check_path_ids" in src


def test_tenant_to_crm_copy_clips_to_the_crm_columns():
    src = _read("app/routers/tenants.py")
    body = src[src.index("def _create_crm_account"):src.index("@router.patch")] if "@router.patch" in src else src[src.index("def _create_crm_account"):]
    assert "_clip(tenant.name, 200)" in body and "_clip(first, 120)" in body and "_clip(last, 120)" in body and "_clip(tenant.contact_phone, 60)" in body
