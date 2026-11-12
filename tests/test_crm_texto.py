"""CRM C1a, pruebas «de texto» (leen el código fuente): corren SIN base de datos (`python3 -m pytest -q --noconftest tests/test_crm_texto.py`)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _t(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_migration_0130_chain_id_length_and_hand_written():
    mig = _t("alembic/versions/0130_crm_cuentas_base.py")
    rev = re.search(r'^revision = "([^"]+)"', mig, re.M).group(1)
    assert rev == "0130_crm_cuentas_base" and len(rev) <= 32
    assert 'down_revision = "0129_staff_client_temp"' in mig
    code = mig[mig.index("def upgrade"):]                                       # solo el código (el docstring lo menciona para explicarlo)
    assert "SET " not in code.replace("SET NULL", "").replace("UPDATE tenants SET client_code", "")          # nada de SET de sesión (pooler de Neon, modo transacción)
    assert "LISTEN" not in code and "advisory" not in code.lower() and "TEMP" not in code.upper().replace("TEMPLATE", "")


def test_there_is_a_single_alembic_head_after_0129():
    revs = {}
    for p in (ROOT / "alembic" / "versions").glob("*.py"):
        s = p.read_text(encoding="utf-8")
        r = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', s, re.M)
        d = re.search(r'^down_revision\s*=\s*["\']([^"\']+)["\']', s, re.M)
        if r:
            revs[r.group(1)] = d.group(1) if d else None
    parents = {d for d in revs.values() if d}
    assert [r for r in revs if r not in parents] == ["0130_crm_cuentas_base"]          # una sola cadena, sin ramas


def test_downgrade_restores_the_hex_code_before_dropping_the_column_and_drops_everything():
    mig = _t("alembic/versions/0130_crm_cuentas_base.py")
    down = mig[mig.index("def downgrade"):]
    assert down.index("UPDATE tenants SET client_code = legacy_client_code") < down.index('drop_column("tenants", "legacy_client_code")')
    for table in ("crm_change_log", "crm_notes", "crm_contacts", "crm_accounts", "crm_counters"):
        assert f'op.drop_table("{table}")' in down
        assert f'op.create_table(\n        "{table}"' in mig


def test_account_status_has_no_check_constraint_and_is_validated_in_code():
    mig = _t("alembic/versions/0130_crm_cuentas_base.py")
    models = _t("app/models.py")
    assert "CheckConstraint" not in mig and "ck_crm" not in mig
    crm_models = models[models.index("class CrmCounter"):]
    assert "CheckConstraint" not in crm_models                                               # la lista de estados se edita en app/crm/__init__.py sin migración
    from app.crm import ACCOUNT_STATUSES, validate_status
    assert ACCOUNT_STATUSES == ("activo", "inactivo", "masivo")
    assert validate_status(" Activo ") == "activo" and validate_status("MASIVO") == "masivo"
    for bad in ("", None, "borrado"):
        try:
            validate_status(bad)
        except ValueError as exc:
            assert "Estado de cuenta no válido" in str(exc)
        else:
            raise AssertionError(f"{bad!r} debió rechazarse")


def test_crm_is_off_by_default_and_the_flag_reads_the_environment(monkeypatch):
    from app.crm import crm_enabled
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    assert crm_enabled() is False
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("CRM_ENABLED", v)
        assert crm_enabled() is True
    for v in ("0", "", "no", "false"):
        monkeypatch.setenv("CRM_ENABLED", v)
        assert crm_enabled() is False
    assert "# CRM_ENABLED=0" in _t(".env.example")


def test_normalize_drops_accents_case_and_extra_spaces():
    from app.crm import normalize
    assert normalize("  Compañía   ÁNDES  S.A.S. ") == "compania andes s.a.s." and normalize(None) == ""


def test_next_code_uses_one_atomic_statement_and_no_session_features():
    src = _t("app/crm/codes.py")
    body = src[src.index("def next_code"):src.index("def counter_state")]          # solo el código de las funciones (el docstring del módulo explica lo que NO se usa)
    assert "UPDATE crm_counters SET value = value + 1" in body and "RETURNING value" in body and "AND ready" in body
    for banned in ("advisory", "SET LOCAL", "SET SESSION", "LISTEN", "NOTIFY", "CREATE TEMP", "nextval"):
        assert banned.lower() not in body.lower()


def test_create_tenant_keeps_hex_unless_crm_is_enabled():
    src = _t("app/routers/tenants.py")
    gen = src[src.index("def _generate_client_code"):src.index("def _serialize")]
    assert gen.index("if crm_enabled()") < gen.index("secrets.token_hex(4)")          # el hexadecimal de hoy queda como camino por defecto
    assert "CodeCounterNotReady" in gen and "status_code=409" in gen


def test_account_sync_and_transfer_carry_the_legacy_alias():
    assert '"legacy_client_code"' in _t("app/account_sync.py")
    et = _t("app/event_transfer.py")
    assert '"legacy_client_code": tenant.legacy_client_code' in et and "m.Tenant.legacy_client_code == client_code" in et


def test_system_page_warns_when_crm_is_on_without_a_ready_counter():
    ops = _t("app/ops.py")
    assert "def check_crm" in ops and "encendido sin contador" in ops and "if crm_enabled():" in ops and "checks.append(lambda: check_crm(db))" in ops


def test_counter_script_is_a_dry_run_by_default():
    s = _t("scripts/crm_set_counter.py")
    assert 'add_argument("--apply"' in s and "if not args.apply" in s and "SIMULACRO" in s


def test_docs_describe_the_switch_on_order_and_the_staging_criteria():
    codes = _t("docs/crm/CODIGOS.md")
    assert codes.index("crm_set_counter.py") < codes.index("CRM_ENABLED=1")          # primero el contador, después el interruptor
    staging = _t("docs/crm/STAGING_C1A.md")
    assert "respaldo" in staging.lower() and "Criterios de éxito" in staging and "0130_crm_cuentas_base" in staging
    assert "Solicitudes de supresión" in _t("docs/crm/README.md") and "Preguntas abiertas de C1b" in _t("docs/crm/README.md")
