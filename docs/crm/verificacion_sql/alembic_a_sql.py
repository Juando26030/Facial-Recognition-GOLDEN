"""Verificación de migraciones SIN SQLAlchemy (el entorno de Claude no lo trae): un reemplazo mínimo de `alembic.op` y `sqlalchemy` que convierte `upgrade()`/`downgrade()` de una
migración ESCRITA A MANO en sentencias SQL de PostgreSQL. Así se prueba el archivo real de la migración, no una copia. Uso: python3 alembic_a_sql.py <archivo.py> upgrade|downgrade > salida.sql
Solo cubre lo que usan las migraciones del CRM (create_table, create_index, add_column, drop_*, execute, ForeignKey, UniqueConstraint, text, false/true)."""
import importlib.util
import sys
import types

OUT = []


class _T:
    def __init__(self, sql):
        self.sql = sql


def _type(name, fmt=None):
    def make(*a):
        return _T(fmt.format(*a) if fmt else name)
    return make


class _Text(str):
    pass


class Column:
    def __init__(self, name, type_, *cons, primary_key=False, nullable=True, server_default=None, autoincrement=False, **kw):
        self.name, self.type, self.cons, self.pk, self.nullable, self.default, self.auto = name, type_, cons, primary_key, nullable, server_default, autoincrement

    def ddl(self):
        t = self.type.sql if isinstance(self.type, _T) else self.type().sql
        if self.pk and self.auto and t == "INTEGER":
            t = "SERIAL"
        parts = [f'"{self.name}"', t]
        if self.pk:
            parts.append("PRIMARY KEY")
        if not self.nullable and not self.pk:
            parts.append("NOT NULL")
        if self.default is not None:
            d = self.default
            parts.append("DEFAULT " + (str(d) if isinstance(d, _Text) else (repr(d) if not isinstance(d, str) else "'" + d.replace("'", "''") + "'")))
        for c in self.cons:
            if isinstance(c, ForeignKey):
                parts.append(c.ddl())
        return " ".join(parts)


class ForeignKey:
    def __init__(self, target, ondelete=None):
        self.target, self.ondelete = target, ondelete

    def ddl(self):
        tbl, col = self.target.split(".")
        return f'REFERENCES "{tbl}" ("{col}")' + (f" ON DELETE {self.ondelete}" if self.ondelete else "")


class UniqueConstraint:
    def __init__(self, *cols, name=None):
        self.cols, self.name = cols, name

    def ddl(self):
        return f'CONSTRAINT "{self.name}" UNIQUE (' + ", ".join(f'"{c}"' for c in self.cols) + ")"


sa = types.ModuleType("sqlalchemy")
sa.Integer = _type("INTEGER")
sa.BigInteger = _type("BIGINT")
sa.Boolean = _type("BOOLEAN")
sa.DateTime = _type("TIMESTAMP")
sa.Date = _type("DATE")
sa.Text = _type("TEXT")
sa.String = lambda n=None: _T(f"VARCHAR({n})" if n else "VARCHAR")
sa.Numeric = lambda p, s: _T(f"NUMERIC({p},{s})")
sa.Column, sa.ForeignKey, sa.UniqueConstraint = Column, ForeignKey, UniqueConstraint
sa.text = lambda s: _Text(s)
sa.false = lambda: _Text("false")
sa.true = lambda: _Text("true")

op = types.ModuleType("alembic.op")


def create_table(name, *items):
    body = [i.ddl() for i in items]
    OUT.append(f'CREATE TABLE "{name}" (\n  ' + ",\n  ".join(body) + "\n);")


def create_index(name, table, cols, unique=False, postgresql_where=None, postgresql_ops=None):
    ops = postgresql_ops or {}
    c = ", ".join(f'"{x}"' + (f" {ops[x]}" if x in ops else "") for x in cols)
    OUT.append(f'CREATE {"UNIQUE " if unique else ""}INDEX "{name}" ON "{table}" ({c})' + (f" WHERE {postgresql_where}" if postgresql_where else "") + ";")


op.create_table, op.create_index = create_table, create_index
op.add_column = lambda table, col: OUT.append(f'ALTER TABLE "{table}" ADD COLUMN {col.ddl()};')
op.create_unique_constraint = lambda name, table, cols: OUT.append(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" UNIQUE (' + ", ".join(cols) + ");")
op.execute = lambda sql: OUT.append(str(sql).rstrip(";") + ";")
op.drop_table = lambda name: OUT.append(f'DROP TABLE "{name}";')
op.drop_index = lambda name, table_name=None: OUT.append(f'DROP INDEX "{name}";')
op.drop_column = lambda table, col: OUT.append(f'ALTER TABLE "{table}" DROP COLUMN "{col}";')
op.drop_constraint = lambda name, table, type_=None: OUT.append(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}";')

alembic = types.ModuleType("alembic")
alembic.op = op
sys.modules.update({"sqlalchemy": sa, "alembic": alembic, "alembic.op": op})

if __name__ == "__main__":
    path, direction = sys.argv[1], sys.argv[2]
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    getattr(mod, direction)()
    print("\n".join(OUT))
