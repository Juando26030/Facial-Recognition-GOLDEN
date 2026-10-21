"""Candado «sin biometría» por evento: con él el servidor no deja activar el rostro, guardar fotos ni encolar vectores.

Revision ID: 0063_biometrics_lock
Revises: 0062_person_changes
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0063_biometrics_lock"
down_revision = "0062_person_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("biometrics_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("events", "biometrics_locked")
