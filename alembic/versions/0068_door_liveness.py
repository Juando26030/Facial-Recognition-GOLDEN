"""Prueba de movimiento (prueba de vida) en la entrada con rostro: interruptor por evento, ENCENDIDO por defecto (requisito para usar el autoservicio en el piloto).

Revision ID: 0068_door_liveness
Revises: 0067_badge_bio_photo
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0068_door_liveness"
down_revision = "0067_badge_bio_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("face_door_liveness", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("events", "face_door_liveness")
