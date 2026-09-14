"""Baseline: esquema tal como existía antes de introducir migraciones (tenants, users, access_logs).

En un entorno NUEVO (base vacía), esta migración crea las tres tablas desde cero.
En la VM de producción y en cualquier entorno donde ya existan estas tablas (creadas antes vía
Base.metadata.create_all), NO se corre esta migración directamente: se marca como ya aplicada con
`alembic stamp 0001_baseline` y de ahí en adelante solo se aplican las migraciones nuevas.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("first_name", sa.String()),
        sa.Column("last_name", sa.String()),
        sa.Column("role", sa.String()),
        sa.Column("company", sa.String()),
        sa.Column("phone", sa.String()),
        sa.Column("email", sa.String()),
        sa.Column("opt_1", sa.String()),
        sa.Column("opt_2", sa.String()),
        sa.Column("face_encoding", sa.Text()),
    )

    op.create_table(
        "access_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id")),
        sa.Column("user_id", sa.String()),
        sa.Column("timestamp", sa.DateTime()),
        sa.Column("record_type", sa.String()),
        sa.ForeignKeyConstraint(["user_id", "tenant_id"], ["users.id", "users.tenant_id"]),
    )


def downgrade() -> None:
    op.drop_table("access_logs")
    op.drop_table("users")
    op.drop_table("tenants")
