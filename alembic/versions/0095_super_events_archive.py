"""Fase 3: super eventos (archivar / restaurar). Solo ADITIVA.

  super_events.archived_at / archived_by_id   archivar = sacarlo de listas y selectores (NULL = activo); se restaura; sus eventos no se tocan.

Revision ID: 0095_super_events_archive
Revises: 0094_crud_gaps
Create Date: 2026-11-07
"""
from alembic import op

revision = "0095_super_events_archive"
down_revision = "0094_crud_gaps"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE super_events ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
    op.execute("ALTER TABLE super_events ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    op.execute("ALTER TABLE super_events DROP COLUMN IF EXISTS archived_by_id")
    op.execute("ALTER TABLE super_events DROP COLUMN IF EXISTS archived_at")
