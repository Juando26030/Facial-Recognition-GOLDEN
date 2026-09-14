"""Agrega staff_users, events, event_staff_authorizations, y columnas de auditoría en access_logs.

Revision ID: 0002_auth_roles_events
Revises: 0001_baseline
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth_roles_events"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String()),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String()),
        sa.Column("start_date", sa.DateTime()),
        sa.Column("end_date", sa.DateTime()),
        sa.Column("status", sa.String(), nullable=False, server_default="activo"),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "event_staff_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column("authorized_by_id", sa.Integer(), sa.ForeignKey("staff_users.id")),
        sa.Column("authorized_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "staff_user_id", name="uq_event_staff"),
    )

    op.add_column("access_logs", sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True))
    op.add_column(
        "access_logs",
        sa.Column("registered_by_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("access_logs", "registered_by_staff_id")
    op.drop_column("access_logs", "event_id")
    op.drop_table("event_staff_authorizations")
    op.drop_table("events")
    op.drop_table("staff_users")
