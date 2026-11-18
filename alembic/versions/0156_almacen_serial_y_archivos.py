"""Almacén (18-nov-2026): el serial de una unidad pasa a ser el valor de su QR (un solo dato) y las novedades llevan archivos adjuntos (al reportar y al resolver).

- inventory_units.code: String(12) → String(32) (cabe un serial real); `serial` se iguala a `code` (en staging solo hay datos de prueba; Almacén sigue apagado en producción).
- Tabla nueva inventory_novelty_files (foto, PDF o video por novedad). Código viejo: ignora la tabla y lee `code` como siempre.

Revision ID: 0156_almacen_serial_y_archivos
Revises: 0155_legalizacion_orden
"""
import sqlalchemy as sa
from alembic import op

revision = "0156_almacen_serial_y_archivos"
down_revision = "0155_legalizacion_orden"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("inventory_units", "code", existing_type=sa.String(12), type_=sa.String(32), existing_nullable=False)
    op.execute("UPDATE inventory_units SET serial = code")
    op.create_table(
        "inventory_novelty_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("novelty_id", sa.Integer(), sa.ForeignKey("inventory_novelties.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("file_key", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("content_type", sa.String(60), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_inventory_novelty_files_novelty", "inventory_novelty_files", ["novelty_id"])


def downgrade():
    op.drop_index("ix_inventory_novelty_files_novelty", table_name="inventory_novelty_files")
    op.drop_table("inventory_novelty_files")
    # `code` queda en 32: reducirlo podría truncar seriales ya escritos.
