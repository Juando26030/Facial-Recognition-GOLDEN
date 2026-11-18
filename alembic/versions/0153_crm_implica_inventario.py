"""CRM → inventario (19-nov-2026): lo que implica cada producto del CRM en elementos de Almacén, los productos del CRM de cada evento, el estado de sincronización y las alertas.

Solo AGREGA tablas nuevas: el código anterior las ignora, así que volver atrás de código no exige tocar la base.

Revision ID: 0153_crm_implica_inventario
Revises: 0152_almacen_novedades
"""
import sqlalchemy as sa
from alembic import op

revision = "0153_crm_implica_inventario"
down_revision = "0152_almacen_novedades"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_product_inventory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("crm_product_id", sa.Integer(), sa.ForeignKey("crm_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_product_id", sa.Integer(), sa.ForeignKey("inventory_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty_per_unit", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("crm_product_id", "inventory_product_id", name="uq_crm_product_inventory"),
    )
    op.create_table(
        "event_crm_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crm_product_id", sa.Integer(), sa.ForeignKey("crm_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("origin", sa.String(10), nullable=False, server_default="crm"),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_event_crm_products_event", "event_crm_products", ["event_id"])
    op.create_table(
        "event_crm_sync",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("source_quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("implied_json", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "event_inventory_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("diff_json", sa.Text(), nullable=False),
        sa.Column("snap_hash", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_event_inventory_alerts_event", "event_inventory_alerts", ["event_id", "status"])


def downgrade():
    op.drop_index("ix_event_inventory_alerts_event", table_name="event_inventory_alerts")
    op.drop_table("event_inventory_alerts")
    op.drop_table("event_crm_sync")
    op.drop_index("ix_event_crm_products_event", table_name="event_crm_products")
    op.drop_table("event_crm_products")
    op.drop_table("crm_product_inventory")
