"""Bloqueo por entorno de los scripts destructivos (app/script_guard.py, scripts/wipe_all_data.py). Pruebas sin base de datos: `python3 -m pytest -q --noconftest tests/test_script_guard_texto.py`."""
import pathlib

import pytest

from app.script_guard import destructive_block_reason, require_destructive_allowed

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("env", [{"DEPLOY_ENV": "production"}, {"ENVIRONMENT": "production"}, {"DEPLOY_ENV": " Production "}, {"ENVIRONMENT": "PRODUCTION"},
                                 {"DEPLOY_ENV": "staging", "ENVIRONMENT": "production"}, {"DEPLOY_ENV": "production", "ENVIRONMENT": "development"}])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "ep-algo.neon.tech", None])
def test_production_is_always_refused_even_with_a_local_host_or_staging(host, env):
    reason = destructive_block_reason(host, env)
    assert reason and "PRODUCCIÓN" in reason and reason.startswith("Se niega")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "LocalHost"])
def test_a_local_database_is_allowed_without_any_environment_or_in_development(host):
    assert destructive_block_reason(host, {}) is None
    assert destructive_block_reason(host, {"ENVIRONMENT": "development"}) is None


def test_staging_is_allowed_with_a_remote_database():
    assert destructive_block_reason("ep-staging.neon.tech", {"DEPLOY_ENV": "staging"}) is None
    assert destructive_block_reason("ep-staging.neon.tech", {"DEPLOY_ENV": " STAGING "}) is None


@pytest.mark.parametrize("host", ["ep-prod.neon.tech", "10.0.0.5", "", None, "localhost.evil.com", "127.0.0.2"])
@pytest.mark.parametrize("env", [{}, {"DEPLOY_ENV": "dev"}, {"DEPLOY_ENV": ""}, {"ENVIRONMENT": "staging"}])
def test_anything_else_is_refused_in_spanish(host, env):
    reason = destructive_block_reason(host, env)
    assert reason and reason.startswith("Se niega") and "no es local" in reason and "DEPLOY_ENV=staging" in reason


def test_require_exits_with_code_2_and_prints_the_reason_or_returns_quietly(capsys):
    with pytest.raises(SystemExit) as exc:
        require_destructive_allowed("ep-prod.neon.tech", {})
    assert exc.value.code == 2 and "Se niega" in capsys.readouterr().out
    assert require_destructive_allowed("localhost", {}) is None and capsys.readouterr().out == ""


def test_wipe_script_runs_the_guard_before_touching_the_database_and_keeps_the_name_confirmation():
    src = (ROOT / "scripts" / "wipe_all_data.py").read_text(encoding="utf-8")
    main = src[src.index("def main"):]
    assert "from app.script_guard import require_destructive_allowed" in src
    assert main.index("require_destructive_allowed(engine.url.host)") < main.index("engine.connect()") < main.index("input(") < main.index("TRUNCATE")
    assert "if typed != db_name" in main and "sys.exit(1)" in main                          # la confirmación escribiendo el nombre de la base sigue igual


def test_the_guard_module_has_no_database_dependency():
    src = (ROOT / "app" / "script_guard.py").read_text(encoding="utf-8")
    assert "sqlalchemy" not in src.lower() and "app.database" not in src and "app.models" not in src
