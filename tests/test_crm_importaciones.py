"""Que ningún módulo nuevo del CRM deje de importar. Sin base de datos."""
import ast
import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NEW = ["app/crm/sqlfold.py", "app/crm/won.py", "app/crm/today.py", "app/routers/crm_today.py", "app/crm/importer/more.py", "app/crm/importer/parsing.py",
       "app/crm/importer/formats.py", "app/crm/importer/runner.py", "app/routers/crm_import.py", "app/crm/tools.py", "app/crm/quotes.py", "app/crm/opportunities.py"]


def _defined(path: Path) -> set:
    tree, names = ast.parse(path.read_text(encoding="utf-8")), set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


@pytest.mark.parametrize("rel", NEW)
def test_every_app_import_resolves_statically(rel):
    """Cada `from app.x import y` apunta a un módulo que existe y que define `y` (se ve aunque no haya SQLAlchemy)."""
    for n in ast.walk(ast.parse((ROOT / rel).read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
            base = ROOT / n.module.replace(".", "/")
            subs = [a for a in n.names if (base / (a.name + ".py")).exists() or (base / a.name).is_dir()]
            rest = [a for a in n.names if a not in subs]
            if not rest:
                continue                                             # todo son submódulos (paquete sin __init__ también vale)
            mod = base.with_suffix(".py") if base.with_suffix(".py").exists() else base / "__init__.py"
            assert mod.exists(), f"{rel}: no existe {n.module}"
            for a in rest:
                assert a.name in _defined(mod), f"{rel}: {n.module} no define {a.name}"


def test_pure_modules_really_import():
    for name in ("app.crm.sqlfold", "app.crm.importer.parsing", "app.crm.importer.formats"):
        importlib.import_module(name)


def test_the_whole_app_imports():
    """Con las dependencias instaladas (FastAPI, SQLAlchemy) importa la aplicación entera: un error de importación nunca más llega a la corrida con base."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    import app.main  # noqa: F401
    for name in ("app.crm.won", "app.crm.today", "app.routers.crm_today", "app.crm.importer.more", "app.crm.importer.runner", "app.routers.crm_import", "app.crm.sqlfold"):
        importlib.import_module(name)


def test_mi_dia_route_exists_exactly_once():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert len(re.findall(r'@app\.get\("/crm/mi-dia"\)', src)) == 1 and '"crm_midia.html"' in src


def test_crm_macro_imports_pass_the_context():
    """Jinja no pasa el contexto a las macros importadas: las que usan url_for (vía _url_for → request) necesitan «with context»."""
    for f in sorted((ROOT / "templates").glob("*.html")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.search(r"\{%\s*(from|import)\s+[\"']_crm_macros\.html[\"']", line):
                assert "with context" in line, f"{f.name}: {line.strip()}"
