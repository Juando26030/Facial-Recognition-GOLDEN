"""Sprint 5: campo de pago (Wompi) en Formularios Web.

Revision ID: 0040_form_payments
Revises: 0039_web_forms
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0040_form_payments"
down_revision = "0039_web_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("form_submissions", sa.Column("status", sa.String(), nullable=False, server_default="confirmed"))
    op.create_table(
        "form_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("form_submissions.id"), nullable=True),
        sa.Column("reference", sa.String(), nullable=False, unique=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="COP"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transaction_id", sa.String(), nullable=True),
        sa.Column("payment_method", sa.String(), nullable=True),
        sa.Column("breakdown_json", sa.Text(), nullable=True),
        sa.Column("person_id", sa.String(), nullable=True),
        sa.Column("payer_email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_form_payments_form_status", "form_payments", ["form_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_form_payments_form_status", table_name="form_payments")
    op.drop_table("form_payments")
    op.drop_column("form_submissions", "status")
