"""Alertas del sistema (Fase 9-A): destinatarios, historial y registro de borrados grandes.

Revision ID: 0119_system_alerts
Revises: 0118_payment_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0119_system_alerts"
down_revision = "0118_payment_accounts"
branch_labels = None
depends_on = None

SEED = ("juando02603@gmail.com", "callcenter@goldenlogisticas.com")


def upgrade():
    recipients = op.create_table(
        "alert_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "system_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(120), nullable=True),
        sa.Column("dedupe_key", sa.String(160), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "mass_delete_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_mass_delete_log_created_at", "mass_delete_log", ["created_at"])
    op.bulk_insert(recipients, [{"kind": "email", "email": e, "active": True} for e in SEED])


def downgrade():
    op.drop_index("ix_mass_delete_log_created_at", table_name="mass_delete_log")
    op.drop_table("mass_delete_log")
    op.drop_table("system_alerts")
    op.drop_table("alert_recipients")
