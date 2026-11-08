"""Fase 3, cierre de huecos de CRUD (estados de evento y plantillas de formulario). Solo ADITIVA.

  event_states / saved_form_templates:
    archived_at / archived_by_id   archivar = ocultar de listas y selectores (NULL = activo); se restaura; el borrado definitivo es de super_admin y solo de lo archivado.

Revision ID: 0094_crud_gaps
Revises: 0093_docs_expenses_archive
Create Date: 2026-11-07
"""
from alembic import op

revision = "0094_crud_gaps"
down_revision = "0093_docs_expenses_archive"
branch_labels = None
depends_on = None

TABLES = ("event_states", "saved_form_templates")


def upgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_by_id")
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_at")
