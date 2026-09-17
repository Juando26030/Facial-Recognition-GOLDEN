"""Sprint 2.4 Fase 15 (2026-09-17): StaffUser.secondary_role — el único doble rol permitido es
coordinador+comercial (en cualquier orden), asignado por admin+ desde Configuración > Staff.

Revision ID: 0022_staff_secondary_role
Revises: 0021_calendar_note_targets
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_staff_secondary_role"
down_revision = "0021_calendar_note_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.add_column(sa.Column("secondary_role", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.drop_column("secondary_role")
