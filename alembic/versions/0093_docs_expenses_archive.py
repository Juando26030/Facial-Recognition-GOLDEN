"""Fase 3, oleada documentos y legalizaciones del evento. Solo ADITIVA.

  event_documents / event_expenses:
    archived_at / archived_by_id   archivar = ocultar de listas, ZIP y reporte (NULL = activo); se restaura; el archivo y el historial no se tocan.

Revision ID: 0093_docs_expenses_archive
Revises: 0092_catalogs_archive
Create Date: 2026-11-07
"""
from alembic import op

revision = "0093_docs_expenses_archive"
down_revision = "0092_catalogs_archive"
branch_labels = None
depends_on = None

TABLES = ("event_documents", "event_expenses")


def upgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_by_id")
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_at")
