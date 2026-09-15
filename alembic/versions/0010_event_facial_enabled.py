"""Event.facial_enabled: reemplaza la elección manual de "método" (Facial vs Cédula, dos
pantallas separadas) por una sola pantalla de Registro unificada. Se enciende sola (nunca se
apaga sola) la primera vez que se sube un roster con zip de fotos para ese evento — ver
bulk_register en routers/api.py y CLAUDE.md.

Revision ID: 0010_event_facial_enabled
Revises: 0009_optional_fields
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_event_facial_enabled"
down_revision = "0009_optional_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("facial_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("events", "facial_enabled")
