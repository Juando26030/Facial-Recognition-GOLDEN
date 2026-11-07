"""Fase 3, oleada 2 (usuarios del personal). Solo ADITIVA.

  staff_users.archived_at / archived_by_id   archivar una cuenta = no inicia sesión y no sale en listas ni selectores (NULL = normal); se restaura; no se borra nada.

Revision ID: 0089_staff_archive
Revises: 0088_archive_and_audit
Create Date: 2026-11-07
"""
from alembic import op

revision = "0089_staff_archive"
down_revision = "0088_archive_and_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
    op.execute("ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    op.execute("ALTER TABLE staff_users DROP COLUMN IF EXISTS archived_by_id")
    op.execute("ALTER TABLE staff_users DROP COLUMN IF EXISTS archived_at")
