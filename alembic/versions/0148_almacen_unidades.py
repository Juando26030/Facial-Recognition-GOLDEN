"""Almacén, Pieza 1 (17-nov-2026): el catálogo de inventario gana tracking / fila del checklist / consumible / QR, y nace `inventory_units` (equipos con serial).

Solo AGREGA (columnas con valor por defecto y una tabla nueva): el código anterior las ignora, así que volver atrás de código no exige tocar la base.
Los productos que ya existen quedan con tracking 'cantidad' (como se comportaban).

Revision ID: 0148_almacen_unidades
Revises: 0147_legalizaciones_formato
"""
import sqlalchemy as sa
from alembic import op

revision = "0148_almacen_unidades"
down_revision = "0147_legalizaciones_formato"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory_products", sa.Column("tracking", sa.String(10), nullable=False, server_default="cantidad"))
    op.add_column("inventory_products", sa.Column("checklist_row", sa.String(40), nullable=True))
    op.add_column("inventory_products", sa.Column("is_consumable", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("inventory_products", sa.Column("qr_code", sa.String(12), nullable=True))
    op.create_unique_constraint("uq_inventory_products_qr_code", "inventory_products", ["qr_code"])
    op.create_table(
        "inventory_units",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("serial", sa.String(80), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="disponible"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.UniqueConstraint("code", name="uq_inventory_units_code"),
        sa.UniqueConstraint("product_id", "number", name="uq_inventory_unit_number"),
    )
    op.create_index("ix_inventory_units_product", "inventory_units", ["product_id"])


def downgrade():
    op.drop_index("ix_inventory_units_product", table_name="inventory_units")
    op.drop_table("inventory_units")
    op.drop_constraint("uq_inventory_products_qr_code", "inventory_products", type_="unique")
    op.drop_column("inventory_products", "qr_code")
    op.drop_column("inventory_products", "is_consumable")
    op.drop_column("inventory_products", "checklist_row")
    op.drop_column("inventory_products", "tracking")
