"""Acta de novedades del evento (Fase 10): tabla event_acts (varias por evento, dos firmas).

Revision ID: 0126_event_acts
Revises: 0121_infra_costs

OJO al integrar: el orden global es A (0122, 0123) -> B (0124) -> D (0125 sin usar, 0126) -> E (0127); al juntar las ramas, `down_revision` pasa a ser la última migración de B.
"""
from alembic import op
import sqlalchemy as sa

revision = "0126_event_acts"
down_revision = "0124_payment_acct_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_acts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("format", sa.String(10), nullable=False, server_default="text"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("coordinator_sig_key", sa.String(300), nullable=True),
        sa.Column("coordinator_name", sa.String(160), nullable=True),
        sa.Column("coordinator_signed_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("coordinator_signed_at", sa.DateTime(), nullable=True),
        sa.Column("client_sig_key", sa.String(300), nullable=True),
        sa.Column("client_name", sa.String(160), nullable=True),
        sa.Column("client_signed_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_signed_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("pdf_key", sa.String(300), nullable=True),
        sa.Column("pdf_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_event_acts_event", "event_acts", ["event_id", "created_at"])


def downgrade():
    op.drop_index("ix_event_acts_event", table_name="event_acts")
    op.drop_table("event_acts")
