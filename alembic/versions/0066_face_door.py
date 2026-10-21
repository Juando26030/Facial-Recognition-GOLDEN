"""B1: interruptor por evento de la entrada con rostro en autoservicio («Entrar con mi rostro»). Apagado por defecto.

Revision ID: 0066_face_door
Revises: 0065_accept_mail_log
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0066_face_door"
down_revision = "0065_accept_mail_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("face_door_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("events", "face_door_enabled")
