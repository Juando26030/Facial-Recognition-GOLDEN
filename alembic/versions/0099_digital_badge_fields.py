"""Escarapela digital: datos visibles elegibles por evento. Solo ADITIVA.

  events.digital_badge_fields   lista JSON de claves de datos de la persona que muestra /b/<token>; NULL = comportamiento de siempre (solo lo que usa la plantilla)

Revision ID: 0099_digital_badge_fields
Revises: 0095_super_events_archive
Create Date: 2026-11-08
"""
from alembic import op

revision = "0099_digital_badge_fields"
down_revision = "0095_super_events_archive"      # temporal: el integrador la reencadena
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS digital_badge_fields TEXT NULL")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS digital_badge_fields")
