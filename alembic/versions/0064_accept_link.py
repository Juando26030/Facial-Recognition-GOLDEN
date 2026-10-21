"""Enlace personal de autorización por correo (B2a): token por persona y evento, si es confiable (listado del organizador) y cuándo se envió; interruptor del evento; y cómo se verificó una aceptación web.

Revision ID: 0064_accept_link
Revises: 0063_biometrics_lock
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0064_accept_link"
down_revision = "0063_biometrics_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_attendees", sa.Column("accept_token", sa.String(), nullable=True))
    op.create_unique_constraint("uq_event_attendees_accept_token", "event_attendees", ["accept_token"])
    op.add_column("event_attendees", sa.Column("accept_trusted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("event_attendees", sa.Column("accept_sent_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("accept_link_email", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("web_acceptances", sa.Column("verified_via", sa.String(12), nullable=True))


def downgrade() -> None:
    op.drop_column("web_acceptances", "verified_via")
    op.drop_column("events", "accept_link_email")
    op.drop_column("event_attendees", "accept_sent_at")
    op.drop_column("event_attendees", "accept_trusted")
    op.drop_constraint("uq_event_attendees_accept_token", "event_attendees", type_="unique")
    op.drop_column("event_attendees", "accept_token")
