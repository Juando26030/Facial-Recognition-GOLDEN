"""Consentimiento y borrado de datos biométricos (Ley 1581 de 2012).

Revision ID: 0046_biometric_consent
Revises: 0045_event_logo_size
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0046_biometric_consent"
down_revision = "0045_event_logo_size"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("biometric_consent_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("biometric_consent_source", sa.String(), nullable=True))
    op.add_column("events", sa.Column("biometrics_purged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "biometrics_purged_at")
    op.drop_column("users", "biometric_consent_source")
    op.drop_column("users", "biometric_consent_at")
