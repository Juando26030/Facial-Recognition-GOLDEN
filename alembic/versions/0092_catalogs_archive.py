"""Fase 3, oleada catálogos (áreas, inventario, librería de colores y de plantillas de escarapela). Solo ADITIVA.

  event_areas / inventory_items / saved_colors / saved_badge_templates:
    archived_at / archived_by_id   archivar = ocultar de listas y selectores (NULL = activo); se restaura; el historial (movimientos, entregas) no se toca.

Revision ID: 0092_catalogs_archive
Revises: 0091_people_forms_archive
Create Date: 2026-11-07
"""
from alembic import op

revision = "0092_catalogs_archive"
down_revision = "0091_people_forms_archive"
branch_labels = None
depends_on = None

TABLES = ("event_areas", "inventory_items", "saved_colors", "saved_badge_templates")


def upgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_by_id")
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS archived_at")
