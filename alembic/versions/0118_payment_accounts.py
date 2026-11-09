"""Cuentas de cobro de Wompi de terceros (Fase 8): llaves cifradas, asignación por formulario y cuenta usada en cada pago.

Revision ID: 0118_payment_accounts
Revises: 0113_public_slug
"""
from alembic import op
import sqlalchemy as sa

revision = "0118_payment_accounts"
down_revision = "0113_public_slug"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ref", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("holder", sa.String(), nullable=True),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("private_enc", sa.Text(), nullable=True),
        sa.Column("integrity_enc", sa.Text(), nullable=False),
        sa.Column("events_enc", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column("web_forms", sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("payment_accounts.id", ondelete="SET NULL"), nullable=True))
    op.add_column("form_payments", sa.Column("account_id", sa.Integer(), sa.ForeignKey("payment_accounts.id", ondelete="SET NULL"), nullable=True))


def downgrade():
    op.drop_column("form_payments", "account_id")
    op.drop_column("web_forms", "payment_account_id")
    op.drop_table("payment_accounts")
