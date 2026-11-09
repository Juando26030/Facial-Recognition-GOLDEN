"""Gastos de infraestructura (Fase 9C): tabla infra_costs (solo admin).

Revision ID: 0121_infra_costs
Revises: 0116_queue_turns
"""
from alembic import op
import sqlalchemy as sa

revision = "0121_infra_costs"
down_revision = "0116_queue_turns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "infra_costs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("concept", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="variable"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("trm", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_cop", sa.Numeric(14, 2), nullable=False),
        sa.Column("source", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("source_key", sa.String(160), nullable=True, unique=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("attachment_key", sa.String(300), nullable=True),
        sa.Column("attachment_name", sa.String(160), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_infra_costs_month", "infra_costs", ["month"])


def downgrade():
    op.drop_index("ix_infra_costs_month", table_name="infra_costs")
    op.drop_table("infra_costs")
