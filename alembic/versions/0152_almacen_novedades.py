"""Almacén, Pieza 3 (18-nov-2026): novedades (daños o problemas de un elemento) con texto, foto y resolución por almacén.

Solo AGREGA una tabla nueva: el código anterior la ignora, así que volver atrás de código no exige tocar la base.

Revision ID: 0152_almacen_novedades
Revises: 0151_merge_preimpresion
"""
import sqlalchemy as sa
from alembic import op

revision = "0152_almacen_novedades"
down_revision = "0151_merge_preimpresion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inventory_novelties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("inventory_units.id"), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("photo_key", sa.String(200), nullable=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("movement_id", sa.Integer(), sa.ForeignKey("inventory_movements.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
    )
    op.create_index("ix_inventory_novelties_product", "inventory_novelties", ["product_id", "resolved_at"])
    op.create_index("ix_inventory_novelties_unit", "inventory_novelties", ["unit_id"])


def downgrade():
    op.drop_index("ix_inventory_novelties_unit", table_name="inventory_novelties")
    op.drop_index("ix_inventory_novelties_product", table_name="inventory_novelties")
    op.drop_table("inventory_novelties")
