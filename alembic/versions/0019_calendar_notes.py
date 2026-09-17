"""Sprint 2.4 Fase 8 (2026-09-16): calendar_notes — recordatorios libres sobre un día del
Calendario, compartidos entre el equipo (coordinador+), no atados a ningún evento en particular.

Revision ID: 0019_calendar_notes
Revises: 0018_event_commercial
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_calendar_notes"
down_revision = "0018_event_commercial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("calendar_notes")
