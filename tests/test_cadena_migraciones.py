"""Cadena de migraciones de Alembic: se verifica leyendo los archivos (sin base).

Una sola cabeza, cada down_revision existe, ids <= 32 caracteres, nada de SET de sesión ni
advisory locks (pooler de Neon en modo transacción), y toda migración tiene downgrade.
"""
import ast
import re
from pathlib import Path

# Migraciones de solo datos con downgrade nulo documentado (no borran nada al subir).
DATA_ONLY_NOOP_DOWNGRADE = {"0109_inventory_unify.py", "0141_merge_crm_subcat.py"}          # 0141 solo une dos cadenas: no cambia el esquema

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _read_revisions():
    revs = {}
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("revision", "down_revision"):
                    values[name] = ast.literal_eval(node.value)
        assert "revision" in values, f"{path.name} sin revision"
        revs[values["revision"]] = (path, values.get("down_revision"))
    return revs


def _parents(down):
    if down is None:
        return []
    if isinstance(down, (tuple, list)):
        return list(down)
    return [down]


def test_single_head_and_parents_exist():
    revs = _read_revisions()
    referenced = set()
    for rev, (path, down) in revs.items():
        for p in _parents(down):
            assert p in revs, f"{path.name}: down_revision {p!r} no existe"
            referenced.add(p)
    heads = sorted(set(revs) - referenced)
    assert len(heads) == 1, f"más de una cabeza: {heads}"
    roots = [r for r, (_, d) in revs.items() if d is None]
    assert len(roots) == 1, f"más de una raíz: {roots}"


def test_revision_ids_fit_alembic_version_column():
    for rev, (path, _) in _read_revisions().items():
        assert len(rev) <= 32, f"{path.name}: revision id de {len(rev)} caracteres"


def test_new_migrations_are_neon_pooler_safe_and_reversible():
    forbidden = re.compile(r"pg_advisory_lock|pg_try_advisory_lock\(|\bLISTEN\b|\bNOTIFY\b|CREATE\s+TEMP|"
                           r"\bSET\s+(SESSION|LOCAL|search_path|statement_timeout|lock_timeout|role)\b", re.I)
    for path in sorted(VERSIONS.glob("01[0-9][0-9]_*.py")):
        if int(path.name[:4]) < 105:
            continue
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path.name}: sentencia incompatible con el pooler de Neon"
        tree = ast.parse(text)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert "upgrade" in funcs and "downgrade" in funcs, f"{path.name} sin upgrade/downgrade"
        body = funcs["downgrade"].body
        if path.name in DATA_ONLY_NOOP_DOWNGRADE:
            continue
        assert not (len(body) == 1 and isinstance(body[0], ast.Pass)), f"{path.name}: downgrade vacío"


def test_new_not_null_columns_on_existing_tables_have_default():
    """add_column NOT NULL sobre tabla con datos necesita server_default (si no, falla en producción)."""
    for path in sorted(VERSIONS.glob("01[0-9][0-9]_*.py")):
        if int(path.name[:4]) < 105:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "op.add_column(" in line and "nullable=False" in line:
                assert "server_default" in line, f"{path.name}: NOT NULL sin server_default: {line.strip()}"
