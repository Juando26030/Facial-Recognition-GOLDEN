"""Impresión compartida: estado explícito de impresión de cada equipo (docs/18…; problema B del 29-oct-2026). Solo ADITIVA: una columna nueva y vacía.

  print_devices.print_mode   «usb» (impresora abierta por WebUSB, lista), «dialog» (el equipo imprime con la ventana de Chrome, lo declara la persona) o «none»/NULL (sin impresora).
                             Solo usb y dialog pueden ser anfitrión de otros equipos.

El código anterior la ignora; bajar la migración quita solo la columna.

Revision ID: 0076_print_mode
Revises: 0075_transfer_jobs
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0076_print_mode"
down_revision = "0075_transfer_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("print_devices", sa.Column("print_mode", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("print_devices", "print_mode")
