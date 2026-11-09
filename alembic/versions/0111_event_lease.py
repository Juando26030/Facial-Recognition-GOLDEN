"""Arrendamiento de un evento por un servidor local (Fase 6): la nube lo muestra en solo lectura mientras esté en local.

Revision ID: 0111_event_lease
Revises: 0110_notifications
"""
from alembic import op
import sqlalchemy as sa

revision = "0111_event_lease"
down_revision = "0110_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("local_node_name", sa.String(), nullable=True))
    op.add_column("events", sa.Column("local_since", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("local_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("events", sa.Column("local_last_upload_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("events", "local_last_upload_at")
    op.drop_column("events", "local_by_id")
    op.drop_column("events", "local_since")
    op.drop_column("events", "local_node_name")
