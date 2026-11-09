"""Catálogo de inventario (categorías y productos) y líneas de inventario por evento con cantidades y cuadre (Fase 5).

Revision ID: 0107_inventory_catalog
Revises: 0104_pledge_health_flags
"""
from alembic import op
import sqlalchemy as sa

revision = "0107_inventory_catalog"
down_revision = "0104_pledge_health_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inventory_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )
    op.create_table(
        "inventory_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("inventory_categories.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False, server_default="unidad"),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("fields_json", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )
    op.create_index("ix_inventory_products_category", "inventory_products", ["category_id"])
    op.create_table(
        "event_inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("qty_assigned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("attrs_json", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", "product_id", name="uq_event_inventory_product"),
    )
    op.create_index("ix_event_inventory_items_event", "event_inventory_items", ["event_id"])


def downgrade():
    op.drop_index("ix_event_inventory_items_event", table_name="event_inventory_items")
    op.drop_table("event_inventory_items")
    op.drop_index("ix_inventory_products_category", table_name="inventory_products")
    op.drop_table("inventory_products")
    op.drop_table("inventory_categories")
