"""Coordinador asignado al evento (FK a staff_users) y horarios como pares de hora
(event_time_start/end, setup_time_start/end) en vez de texto libre.

Revision ID: 0004_event_extras
Revises: 0003_tenant_event_fields
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_event_extras"
down_revision = "0003_tenant_event_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("coordinator_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True))
    op.add_column("events", sa.Column("event_time_start", sa.String(), nullable=True))
    op.add_column("events", sa.Column("event_time_end", sa.String(), nullable=True))
    op.add_column("events", sa.Column("setup_time_start", sa.String(), nullable=True))
    op.add_column("events", sa.Column("setup_time_end", sa.String(), nullable=True))
    op.drop_column("events", "event_schedule")
    op.drop_column("events", "setup_schedule")


def downgrade() -> None:
    op.add_column("events", sa.Column("event_schedule", sa.String(), nullable=True))
    op.add_column("events", sa.Column("setup_schedule", sa.String(), nullable=True))
    op.drop_column("events", "setup_time_end")
    op.drop_column("events", "setup_time_start")
    op.drop_column("events", "event_time_end")
    op.drop_column("events", "event_time_start")
    op.drop_column("events", "coordinator_staff_id")
