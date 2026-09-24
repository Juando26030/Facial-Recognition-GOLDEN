"""Sprint 5: reembolsos de pagos de Formularios Web (anulación de tarjeta por API, o registro manual).

Revision ID: 0041_form_refunds
Revises: 0040_form_payments
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0041_form_refunds"
down_revision = "0040_form_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("form_payments", sa.Column("refunded_cents", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "form_refunds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("form_payments.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("cancel_registration", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("wompi_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_form_refunds_payment", "form_refunds", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_form_refunds_payment", table_name="form_refunds")
    op.drop_table("form_refunds")
    op.drop_column("form_payments", "refunded_cents")
