"""Correo de la escarapela virtual editable por evento (asunto + cuerpo HTML).

Revision ID: 0044_digital_email_template
Revises: 0043_form_discount_codes
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0044_digital_email_template"
down_revision = "0043_form_discount_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("digital_email_subject", sa.String(), nullable=True))
    op.add_column("events", sa.Column("digital_email_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "digital_email_body")
    op.drop_column("events", "digital_email_subject")
