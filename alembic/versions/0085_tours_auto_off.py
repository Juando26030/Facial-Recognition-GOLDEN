"""Preferencia por cuenta: «deshabilitar demos automáticas». Solo ADITIVA.

  staff_users.tours_auto_off   verdadero = las guías (demos paso a paso) no arrancan solas al entrar a una pantalla, en NINGÚN dispositivo de esa cuenta.
                               El botón «Guía» sigue funcionando a mano. Se copia a la sesión al iniciar sesión.

Sin SET de sesión, sin advisory locks; compatible con el pooler de Neon. El código anterior ignora la columna. Bajar la migración la quita.

Revision ID: 0085_tours_auto_off
Revises: 0084_stats_links
Create Date: 2026-11-06
"""
from alembic import op

revision = "0085_tours_auto_off"
down_revision = "0084_stats_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS tours_auto_off BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE staff_users DROP COLUMN IF EXISTS tours_auto_off")
