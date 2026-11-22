"""Modelo de legalizaciones (migración 0147): el modelo y la migración dicen lo mismo, y la tabla nueva está
en el traslado de eventos y en el borrado. No usa base de datos ni importa SQLAlchemy: lee el código fuente."""
import ast
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
MIG = ROOT / "alembic" / "versions" / "0147_legalizaciones_formato.py"
MODELS = ROOT / "app" / "models.py"
ANTES = {"id", "event_id", "category", "responsible", "description", "applies_to", "amount", "evidence_path", "evidence_name",
         "created_by_id", "created_at", "archived_at", "archived_by_id"}


def _class_columns(name: str) -> dict:
    """{columna: texto de su Column(...)} de una clase de models.py."""
    src = MODELS.read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.targets[0].id: ast.get_source_segment(src, n.value) for n in cls.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", "") == "Column"}


def _constant(name: str):
    src = MODELS.read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)
    return ast.literal_eval(node.value)


def test_columnas_nuevas_del_gasto_coinciden_con_la_migracion():
    ns = {}
    with patch.dict(sys.modules, {"alembic": MagicMock(), "sqlalchemy": MagicMock()}):      # solo se lee ALL_NEW; no hace falta Alembic
        exec(compile(MIG.read_text(encoding="utf-8"), str(MIG), "exec"), ns)
    assert set(_class_columns("EventExpense")) - ANTES - {"position"} == set(ns["ALL_NEW"])          # position: 0156, "el modelo y la migración 0147 no coinciden"


def test_tabla_del_encabezado_coincide_con_la_migracion():
    texto = MIG.read_text(encoding="utf-8")
    en_migracion = set(re.findall(r'sa\.Column\("(\w+)"', texto.split('"event_legalizations"', 1)[1]))
    assert en_migracion == set(_class_columns("EventLegalization"))


def test_el_gasto_viejo_queda_en_otros_gastos_y_el_resto_es_opcional():
    cols = _class_columns("EventExpense")
    assert "server_default='otro'" in cols["kind"] and "nullable=False" in cols["kind"]
    for name in set(cols) - ANTES - {"kind"}:
        assert "nullable=True" in cols[name], f"{name} debe ser opcional (los gastos que ya existen no lo tienen)"
    mig = MIG.read_text(encoding="utf-8")
    assert 'sa.Column("kind", sa.String(20), nullable=False, server_default="otro")' in mig


def test_tipos_de_gasto_son_los_del_generador_de_excel():
    from app import legalization_xlsx as L
    assert _constant("EXPENSE_KINDS") == L.KINDS
    assert _constant("LEGALIZATION_STATUSES") == ("borrador", "enviada", "aprobada", "devuelta")


def test_la_cabecera_es_una_por_evento():
    assert "unique=True" in _class_columns("EventLegalization")["event_id"]


def test_traslado_y_borrado_de_eventos_conocen_la_tabla_nueva():
    transfer = (ROOT / "app" / "event_transfer.py").read_text(encoding="utf-8")
    assert '"name": "event_legalizations"' in transfer
    assert '"event_legalizations"' in transfer.split("OPTIONAL_TABLES =", 1)[1].split("\n", 1)[0]          # 0161 agregó event_dependents después
    assert '"approved_by_id"' in transfer
    docs = (ROOT / "app" / "routers" / "event_docs.py").read_text(encoding="utf-8")
    assert "EventLegalization.event_id == event_id).delete()" in docs


def test_nombre_de_las_copias_de_un_gasto():
    """«Hotel X» → «Hotel X (copia)», después «(copia 1)», «(copia 2)»…; copiar una copia no anida el sufijo."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "app" / "legalization_svc.py").read_text(encoding="utf8")
    ns = {"re": __import__("re")}
    exec(compile(src[src.index("_COPY_RE ="):src.index("def _f(v):")], "copy_name", "exec"), ns)
    copy_name = ns["copy_name"]
    assert copy_name("Hotel X", ["Hotel X"]) == "Hotel X (copia)"
    assert copy_name("Hotel X", ["Hotel X", "Hotel X (copia)"]) == "Hotel X (copia 1)"
    assert copy_name("Hotel X (copia)", ["Hotel X", "Hotel X (copia)", "Hotel X (copia 1)"]) == "Hotel X (copia 2)"
    assert copy_name("Hotel X (copia 2)", ["Hotel X", "Hotel X (copia)", "Hotel X (copia 1)", "Hotel X (copia 2)"]) == "Hotel X (copia 3)"
    assert copy_name("Hotel Y", ["Hotel X", "Hotel X (copia)"]) == "Hotel Y (copia)" and copy_name("", []) == "(copia)" and copy_name(None, []) == "(copia)"
    assert copy_name("A" * 200, [], 200).endswith(" (copia)") and len(copy_name("A" * 200, [], 200)) <= 200
