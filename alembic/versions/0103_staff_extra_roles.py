"""Roles extra por cuenta: varios roles para una misma persona (8-nov-2026).

Revision ID: 0103_staff_extra_roles
Revises: 0102_pledge_staff_nullable
"""
from alembic import op
import sqlalchemy as sa

revision = "0103_staff_extra_roles"
down_revision = "0102_pledge_staff_nullable"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("staff_users", sa.Column("extra_roles", sa.String(), nullable=True))


def downgrade():
    op.drop_column("staff_users", "extra_roles")
