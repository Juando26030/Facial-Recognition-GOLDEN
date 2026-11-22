"""Inventario «lo define la base», base de dependientes y bloqueo de la configuración del digitador (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md). Solo ADITIVA.

events.inventory_mode           cómo se decide qué recibe cada persona: NULL/'choose' = la persona elige (lo de siempre) | 'assigned' = la base lo define
events.inventory_assign_json    columnas que mandan en el modo 'assigned': {"holder_product", "holder_qty", "dep_product", "dep_qty"} (claves de campo del evento / títulos de la base de dependientes)
events.areas_config_locked      la tableta del digitador queda fija en la zona y el movimiento elegidos (se desbloquea con la contraseña)
events.inventory_config_locked  la tableta del digitador queda fija en lo marcado para entregar
events.config_unlock_hash       contraseña de desbloqueo del evento (hash; nunca el texto)
events.dependents_badge         imprimir escarapela también a los dependientes (reservado: aún no se usa)
event_field_configs.show_in_card  mostrar el campo en la tarjeta de la persona de la pantalla de Registro sin abrir «Editar» (NULL = lo de fábrica: cédula, nombres y apellidos sí; lo demás no)
inventory_items.source_value    valor de la base (normalizado) que creó el producto en el modo 'assigned'; se puede cambiar el nombre visible sin romper el enlace
inventory_deliveries.assignment_key  qué asignación se entregó: 'h' (la del titular) o 'd<uid>' (la fila de un dependiente); NULL = entrega elegida (modo de siempre)
event_dependents                una fila por fila del archivo de dependientes (persona asociada a un titular, con sus columnas); `uid` no cambia al copiar el evento a un servidor local
Columnas nuevas NULL o con valor por defecto constante (instantáneo en PostgreSQL). Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0161_inventario_por_base
Revises: 0160_shared_local_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0161_inventario_por_base"
down_revision = "0160_shared_local_events"
branch_labels = None
depends_on = None


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    ev = _cols("events")
    if "inventory_mode" not in ev:
        op.add_column("events", sa.Column("inventory_mode", sa.String(10), nullable=True))
    if "inventory_assign_json" not in ev:
        op.add_column("events", sa.Column("inventory_assign_json", sa.Text(), nullable=True))
    if "areas_config_locked" not in ev:
        op.add_column("events", sa.Column("areas_config_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "inventory_config_locked" not in ev:
        op.add_column("events", sa.Column("inventory_config_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "config_unlock_hash" not in ev:
        op.add_column("events", sa.Column("config_unlock_hash", sa.String(), nullable=True))
    if "dependents_badge" not in ev:
        op.add_column("events", sa.Column("dependents_badge", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "show_in_card" not in _cols("event_field_configs"):
        op.add_column("event_field_configs", sa.Column("show_in_card", sa.Boolean(), nullable=True))
    if "source_value" not in _cols("inventory_items"):
        op.add_column("inventory_items", sa.Column("source_value", sa.String(), nullable=True))
    if "assignment_key" not in _cols("inventory_deliveries"):
        op.add_column("inventory_deliveries", sa.Column("assignment_key", sa.String(40), nullable=True))
    if "event_dependents" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "event_dependents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("uid", sa.String(32), nullable=False),
            sa.Column("holder_id", sa.String(), nullable=False),
            sa.Column("person_key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("doc_id", sa.String(), nullable=True),
            sa.Column("data_json", sa.Text(), nullable=True),
            sa.Column("row_num", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_event_dependents_holder", "event_dependents", ["event_id", "holder_id"])
        op.create_index("ix_event_dependents_doc", "event_dependents", ["event_id", "doc_id"])
        op.create_index("ix_event_dependents_uid", "event_dependents", ["event_id", "uid"])


def downgrade():
    op.drop_index("ix_event_dependents_uid", table_name="event_dependents")
    op.drop_index("ix_event_dependents_doc", table_name="event_dependents")
    op.drop_index("ix_event_dependents_holder", table_name="event_dependents")
    op.drop_table("event_dependents")
    op.drop_column("event_field_configs", "show_in_card")
    op.drop_column("inventory_deliveries", "assignment_key")
    op.drop_column("inventory_items", "source_value")
    for c in ("dependents_badge", "config_unlock_hash", "inventory_config_locked", "areas_config_locked", "inventory_assign_json", "inventory_mode"):
        op.drop_column("events", c)
