"""Configuración de la autorización biométrica por evento (L1): quién es el Responsable (`controller_mode`: golden | tercero), los datos del organizador cuando es un tercero
y cada cuánto se pide la autorización (`consent_prompt_mode`: once | every_scan).

Revision ID: 0055_event_consent_config
Revises: 0054_audit_consent_logs
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_event_consent_config"
down_revision = "0054_audit_consent_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("controller_mode", sa.String(), nullable=False, server_default="golden"))
    op.add_column("events", sa.Column("organizer_name", sa.String(), nullable=True))
    op.add_column("events", sa.Column("organizer_nit", sa.String(), nullable=True))
    op.add_column("events", sa.Column("organizer_privacy_email", sa.String(), nullable=True))
    op.add_column("events", sa.Column("consent_prompt_mode", sa.String(), nullable=False, server_default="once"))


def downgrade() -> None:
    for c in ("consent_prompt_mode", "organizer_privacy_email", "organizer_nit", "organizer_name", "controller_mode"):
        op.drop_column("events", c)
