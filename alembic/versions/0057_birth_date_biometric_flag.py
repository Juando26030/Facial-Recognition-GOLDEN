"""Menores de edad (L3): fecha de nacimiento de la persona y bandera `is_biometric_enabled` (False = sin captura biométrica: menor de 18 años; solo cédula/QR).

Revision ID: 0057_birth_date_biometric_flag
Revises: 0056_precalc_authorized
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_birth_date_biometric_flag"
down_revision = "0056_precalc_authorized"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("is_biometric_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("users", "is_biometric_enabled")
    op.drop_column("users", "birth_date")
