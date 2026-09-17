"""Sprint 2.4 (2026-09-16): StaffUser.phone — nullable, para notificaciones por WhatsApp más
adelante (Fase 5/6 del sprint). No hace falta backfill, las cuentas existentes simplemente quedan
sin teléfono hasta que alguien lo agregue.

Revision ID: 0015_staff_phone
Revises: 0014_event_field_configs
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_staff_phone"
down_revision = "0014_event_field_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_users", sa.Column("phone", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_users", "phone")
