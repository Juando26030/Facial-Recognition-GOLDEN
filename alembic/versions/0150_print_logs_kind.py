"""Preimpresiones (18-nov-2026): `print_logs.kind` distingue una escarapela PREIMPRESA (antes de que la persona llegue) de una impresión normal.

Solo AGREGA una columna con valor por defecto 'normal': el código anterior la ignora, así que volver atrás de código no exige tocar la base.
Las impresiones que ya existen quedan como 'normal'.

Revision ID: 0150_print_logs_kind
Revises: 0148_almacen_unidades
"""
import sqlalchemy as sa
from alembic import op

revision = "0150_print_logs_kind"
down_revision = "0148_almacen_unidades"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("print_logs", sa.Column("kind", sa.String(10), nullable=False, server_default="normal"))


def downgrade():
    op.drop_column("print_logs", "kind")
