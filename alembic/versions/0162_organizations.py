"""Capa «empresa» del SaaS, primera pieza (22-nov-2026, docs/27_SAAS_EMPRESAS.md). Solo ADITIVA.

organizations             la empresa que usa la plataforma (Golden = fila 1, slug 'golden', plan 'interno'); un nivel POR ENCIMA de `tenants` (los clientes de esa empresa)
organizations.plan        'interno' | 'basico' | 'pro' | 'empresa' (los valores de fábrica de cada plan viven en app/orgs.py)
organizations.entitlements_json  límites propios de ESA empresa que pisan los del plan (JSON; una clave en null = sin límite). NULL = solo lo del plan
organizations.status      'active' | 'suspended'
tenants.org_id            a qué empresa pertenece el cliente (NULL o 1 = Golden)
staff_users.org_id        a qué empresa pertenece la cuenta del personal (NULL o 1 = Golden)
Columnas nuevas NULL con valor por defecto constante 1 (instantáneo en PostgreSQL): todo lo que ya existe queda en Golden. SIN llave foránea todavía (la pone la pieza que quite el valor por
defecto, cuando todas las tablas tengan su org_id; docs/revision_2026-11-22/01, anexo A.3). Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0162_organizations
Revises: 0161_inventario_por_base
"""
from alembic import op
import sqlalchemy as sa

revision = "0162_organizations"
down_revision = "0161_inventario_por_base"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade():
    insp = _insp()
    if "organizations" not in insp.get_table_names():
        op.create_table(
            "organizations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("slug", sa.String(60), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("legal_name", sa.String(200), nullable=True),
            sa.Column("nit", sa.String(40), nullable=True),
            sa.Column("contact_email", sa.String(200), nullable=True),
            sa.Column("contact_phone", sa.String(40), nullable=True),
            sa.Column("plan", sa.String(20), nullable=False, server_default="basico"),
            sa.Column("entitlements_json", sa.Text(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        )
    bind = op.get_bind()
    if not bind.execute(sa.text("SELECT 1 FROM organizations WHERE id = 1")).first():
        bind.execute(sa.text(
            "INSERT INTO organizations (id, slug, name, legal_name, plan, status, created_at) "
            "VALUES (1, 'golden', 'Golden', 'Golden Eventos y Logística S.A.S.', 'interno', 'active', CURRENT_TIMESTAMP)"))
        if bind.dialect.name == "postgresql":          # la fila 1 se insertó con id explícito: la secuencia sigue desde ahí
            bind.execute(sa.text("SELECT setval(pg_get_serial_sequence('organizations', 'id'), (SELECT MAX(id) FROM organizations))"))
    for table in ("tenants", "staff_users"):
        if "org_id" not in {c["name"] for c in _insp().get_columns(table)}:
            op.add_column(table, sa.Column("org_id", sa.Integer(), nullable=True, server_default="1"))
        if f"ix_{table}_org_id" not in {i["name"] for i in _insp().get_indexes(table)}:
            op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def downgrade():
    for table in ("staff_users", "tenants"):
        if f"ix_{table}_org_id" in {i["name"] for i in _insp().get_indexes(table)}:
            op.drop_index(f"ix_{table}_org_id", table_name=table)
        if "org_id" in {c["name"] for c in _insp().get_columns(table)}:
            op.drop_column(table, "org_id")
    if "organizations" in _insp().get_table_names():
        op.drop_table("organizations")
