"""CRM etapa C1c–C4, Paso 0 (SIN base de datos: corre con `python3 -m pytest -q --noconftest tests/test_crm_etapa_texto.py`): migraciones 0131–0132 encadenadas y reversibles, modelos al día con las
migraciones, historial y componentes compartidos listos para las piezas."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _mig(name):
    return _read(f"alembic/versions/{name}.py")


def test_migrations_0131_and_0132_are_chained_short_and_reversible():
    chain = [("0130_crm_cuentas_base", None), ("0131_crm_pipeline_leads", "0130_crm_cuentas_base"), ("0132_crm_import_runs", "0131_crm_pipeline_leads")]
    for rev, parent in chain[1:]:
        src = _mig(rev)
        assert re.search(rf'^revision = "{rev}"', src, re.M) and re.search(rf'^down_revision = "{parent}"', src, re.M), rev
        assert len(rev) <= 32
        assert "def downgrade" in src and "SET " not in src.replace("SET NULL", "")          # sin SET de sesión (pooler de Neon)
        code = src.split('"""', 2)[2]          # sin el texto de la descripción
        assert "TEMP TABLE" not in code.upper() and "TEMPORARY" not in code.upper() and "advisory" not in code.lower()
    up, down = _mig("0131_crm_pipeline_leads").split("def downgrade")
    created = re.findall(r'op\.create_table\(\s*"(\w+)"', up)
    dropped = re.findall(r'op\.drop_table\("(\w+)"\)', down)
    assert sorted(created) == sorted(dropped) == sorted(["crm_pipelines", "crm_stages", "crm_leads", "crm_opportunities", "crm_activities"])
    assert dropped.index("crm_activities") < dropped.index("crm_opportunities") < dropped.index("crm_leads") < dropped.index("crm_stages") < dropped.index("crm_pipelines")          # primero lo que depende
    up, down = _mig("0132_crm_import_runs").split("def downgrade")
    assert re.findall(r'op\.create_table\(\s*"(\w+)"', up) == ["crm_import_runs", "crm_import_pairs"] and re.findall(r'op\.drop_table\("(\w+)"\)', down) == ["crm_import_pairs", "crm_import_runs"]


def test_models_match_the_migrations_table_by_table():
    models = _read("app/models.py")
    for table in ("crm_pipelines", "crm_stages", "crm_leads", "crm_opportunities", "crm_activities", "crm_import_runs", "crm_import_pairs"):
        assert f"__tablename__ = '{table}'" in models, table
    tree = ast.parse(models)
    cols = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            table = next((n.value.value for n in node.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__tablename__"), None)
            if table and table.startswith("crm_"):
                cols[table] = {n.targets[0].id for n in node.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "Column"}
    for rev, tables in (("0131_crm_pipeline_leads", ["crm_pipelines", "crm_stages", "crm_leads", "crm_opportunities", "crm_activities"]), ("0132_crm_import_runs", ["crm_import_runs", "crm_import_pairs"])):
        src = _mig(rev).split("def downgrade")[0]
        for table in tables:
            body = src[src.index(f'op.create_table(\n        "{table}"'):]
            body = body.split("op.create_table(", 2)[1] if body.count("op.create_table(") > 1 else body
            body = body[:body.index("op.create_index") if "op.create_index" in body else len(body)]
            migrated = set(re.findall(r'sa\.Column\("(\w+)"', body))
            assert migrated == cols[table], f"{table}: migración {sorted(migrated ^ cols[table])}"


def test_the_default_pipeline_is_seeded_and_has_one_won_and_one_lost_stage():
    src = _mig("0131_crm_pipeline_leads")
    assert "'Eventos', 0, true" in src
    kinds = re.findall(r'\("[^"]+", \d+, "(open|won|lost)"\)', src)
    assert kinds.count("won") == 1 and kinds.count("lost") == 1 and kinds.count("open") == 5
    for _name, prob in re.findall(r'\("([^"]+)", (\d+), "', src):
        assert 0 <= int(prob) <= 100


def test_history_knows_the_new_entities_and_keeps_free_text_out():
    from_src = _read("app/crm/history.py")
    for entity in ("lead", "opportunity", "quote"):
        assert f'"{entity}":' in from_src.split("FIELDS = {", 1)[1].split("\n", 1)[0], entity
    free = from_src.split("FREE_TEXT = {", 1)[1].split("}", 1)[0]
    for needle in ('"lead": ("description",)', '"opportunity": ("description", "next_step")', '"quote": ("meeting_notes",)'):
        assert needle in free, needle
    # ningún campo de texto libre se registra con su valor: record() usa FREE_TEXT para todas las entidades
    assert "keep = f not in FREE_TEXT.get(entity, ())" in from_src
    assert "entity" in _read("app/models.py").split("class CrmChangeLog")[1].split("String(16)")[0]          # entity admite hasta 16 caracteres: «opportunity» (11) cabe


def test_schema_verification_script_covers_every_new_migration():
    sh = _read("docs/crm/verificacion_sql/correr_etapa.sh")
    assert "013[1-9]_*.py" in sh and "alembic_a_sql.py" in sh and "SEGUNDA SUBIDA" in sh and "tablas_crm_que_quedan" in sh
    sql = _read("docs/crm/verificacion_sql/06_pruebas_etapa.sql")
    for needle in ("RESTRICT", "unique_violation", "cascada", "índice parcial"):
        assert needle in sql, needle


def test_navigation_bar_lists_only_built_sections_and_hides_admin_ones():
    src = _read("app/crm/__init__.py")
    assert "SECTIONS_BUILT" in src and "def sections(" in src
    nav = _read("templates/_crm_nav.html")
    assert 'aria-current="page"' in nav and "onclick" not in nav and "style=" not in nav
    for page in ("templates/crm_cuentas.html", "templates/crm_cuenta.html"):
        assert '_crm_nav.html' in _read(page)
    assert 'context["crm_nav"] = crm_pkg.sections(' in _read("app/main.py")


def test_kanban_and_stage_bar_components_are_shared_before_any_screen_uses_them():
    css, guide = _read("static/css/design-system.css"), _read("docs/ux/guia_visual.html")
    for cls in (".gw-kanban", ".gw-kcard", ".gw-stagebar", ".gw-crm-nav"):
        assert cls in css, cls
    assert "gw-kanban" in guide and "gw-stagebar" in guide
    assert "14." in _read("docs/ux/ESTANDARES_VISUALES.md") and "gw-kanban" in _read("docs/ux/ESTANDARES_VISUALES.md")


def test_harness_loads_extension_modules_per_piece():
    assert "pages_*.py" in _read("scripts/visual_harness/pages.py") and "mocks_*.py" in _read("scripts/visual_harness/mocks.py")
