"""Captura de contactos para expositores (Fase 8): tarjeta por persona, constancia de consentimiento (solo INSERT), expositores y sus contactos.

Revision ID: 0114_exhibitor_leads
Revises: 0113_public_slug
"""
from alembic import op
import sqlalchemy as sa

revision = "0114_exhibitor_leads"
down_revision = "0113_public_slug"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contact_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("share_token", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "tenant_id", "user_id", name="uq_contact_card_person"),
    )
    op.create_table(
        "audit_contact_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("cedula_hash", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("adult_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(), nullable=False),
    )
    op.create_index("ix_contact_share_person", "audit_contact_shares", ["event_id", "tenant_id", "user_id", "at"])
    op.create_table(
        "event_exhibitors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("card_token", sa.String(), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_exhibitor_event", "event_exhibitors", ["event_id"])
    op.create_table(
        "exhibitor_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exhibitor_id", sa.Integer(), sa.ForeignKey("event_exhibitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("exhibitor_id", "tenant_id", "user_id", name="uq_exhibitor_lead"),
    )


def downgrade():
    op.drop_table("exhibitor_leads")
    op.drop_index("ix_exhibitor_event", table_name="event_exhibitors")
    op.drop_table("event_exhibitors")
    op.drop_index("ix_contact_share_person", table_name="audit_contact_shares")
    op.drop_table("audit_contact_shares")
    op.drop_table("contact_cards")
