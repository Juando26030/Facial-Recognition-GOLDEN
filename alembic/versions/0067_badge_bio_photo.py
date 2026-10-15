"""A1: interruptor de seguridad «Permitir imprimir la foto biométrica en la escarapela» (apagado por defecto; solo super_admin lo enciende).

Revision ID: 0067_badge_bio_photo
Revises: 0066_face_door
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0067_badge_bio_photo"
down_revision = "0066_face_door"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("badge_bio_photo_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("events", "badge_bio_photo_allowed")
