"""Fase 3, oleada 3 (eventos + L7). Solo ADITIVA.

  events.archived_at / archived_by_id   archivar un evento finalizado = oculto de listas y sin registro ni formularios (NULL = activo); se restaura; no se borra nada.
  events.data_archived_at   L7 (90 días): el Job archiva SOLO la base de datos del evento (el evento sigue en las listas); NULL = base abierta. Lo desarchiva un super_admin.

Revision ID: 0090_event_archive
Revises: 0089_staff_archive
Create Date: 2026-11-07
"""
from alembic import op

revision = "0090_event_archive"
down_revision = "0089_staff_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS data_archived_at TIMESTAMP NULL")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS data_archived_at")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS archived_by_id")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS archived_at")
