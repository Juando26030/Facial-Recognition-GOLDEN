"""Coordinador temporal del evento: staff_users.event_only (16-nov-2026).

Revision ID: 0146_event_only_staff
Revises: 0145_event_contacts
"""
import sqlalchemy as sa
from alembic import op

revision = "0146_event_only_staff"
down_revision = "0145_event_contacts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("staff_users", sa.Column("event_only", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("staff_users", "event_only")
