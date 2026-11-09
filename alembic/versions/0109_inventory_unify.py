"""Unifica el campo «Inventario» de la plantilla de evento con el catálogo de inventario (Fase 5): pasa lo viejo al catálogo y retira el campo. Idempotente; no borra nada.

Revision ID: 0109_inventory_unify
Revises: 0108_event_change_log
"""
from alembic import op

from app import inventory_unify

revision = "0109_inventory_unify"
down_revision = "0108_event_change_log"
branch_labels = None
depends_on = None


def upgrade():
    inventory_unify.migrate(op.get_bind())


def downgrade():
    pass          # lo migrado queda en el catálogo; el campo viejo conserva sus valores en extra_json (se vuelve a activar desde la plantilla si hiciera falta)
