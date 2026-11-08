"""Decisiones del dueño (8-nov-2026), Fase 3. Solo ADITIVA, con valores por defecto que preservan el comportamiento actual.

  events.accept_no_birth_mode          D5: aceptación web cuando la base NO trae fecha de nacimiento: 'any' (hoy: cualquier fecha adulta escrita) | 'require_personal_link' (solo con el
                                       enlace personal del correo). Los eventos existentes quedan en 'any'; los nuevos nacen con 'require_personal_link' (lo pone la creación, no la base).
  inventory_items.allow_repeat_delivery  D7: «Permitir repetir la entrega a la misma persona». Los ítems existentes quedan permitiendo (true); los nuevos nacen sin permitir (lo pone el alta).

Revision ID: 0096_decisiones_dueno
Revises: 0095_super_events_archive
Create Date: 2026-11-08
"""
from alembic import op

revision = "0096_decisiones_dueno"
down_revision = "0095_super_events_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS accept_no_birth_mode VARCHAR NOT NULL DEFAULT 'any'")
    op.execute("ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS allow_repeat_delivery BOOLEAN NOT NULL DEFAULT true")


def downgrade():
    op.execute("ALTER TABLE inventory_items DROP COLUMN IF EXISTS allow_repeat_delivery")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS accept_no_birth_mode")
