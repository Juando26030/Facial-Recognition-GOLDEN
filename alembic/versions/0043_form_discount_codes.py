"""Sprint 5: códigos de descuento de los Formularios Web (un código con N usos, o N códigos de un solo uso).

Revision ID: 0043_form_discount_codes
Revises: 0042_roulette_authorize
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0043_form_discount_codes"
down_revision = "0042_roulette_authorize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "form_discount_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("discount_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("form_id", "code", name="uq_form_discount_code"),
    )
    op.add_column("form_submissions", sa.Column("discount_code_id", sa.Integer(), sa.ForeignKey("form_discount_codes.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("form_submissions", "discount_code_id")
    op.drop_table("form_discount_codes")
