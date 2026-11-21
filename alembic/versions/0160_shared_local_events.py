"""Evento COMPARTIDO entre varios servidores locales, con la nube como puente (20-nov-2026, docs/23_EVENTO_COMPARTIDO_NUBE.md). Solo ADITIVA.

Nube:
  events.local_shared        el evento acepta VARIOS servidores locales a la vez (lo enciende un administrador antes de descargarlo)
  event_local_nodes          qué servidores locales tienen el evento (además de events.local_node_name, que sigue siendo el «principal» para pantallas viejas)
Servidor local:
  events.peer_cursor         hasta dónde bajó los cambios de los OTROS servidores (JSON con los últimos ids de la nube)
  access_logs / print_logs / person_changes / event_attendees .from_peer
                             la fila llegó de otro servidor (vía nube): la subida NO la devuelve a la nube. NULL/false = hecha aquí.
Columnas nuevas sin valor por defecto (en PostgreSQL agregar una columna NULL es instantáneo, aunque la tabla sea grande).
Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0160_shared_local_events
Revises: 0159_node_disabled_at
"""
from alembic import op
import sqlalchemy as sa

revision = "0160_shared_local_events"
down_revision = "0159_node_disabled_at"
branch_labels = None
depends_on = None

PEER_TABLES = ("access_logs", "print_logs", "person_changes", "event_attendees")


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    ev = _cols("events")
    if "local_shared" not in ev:
        op.add_column("events", sa.Column("local_shared", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "peer_cursor" not in ev:
        op.add_column("events", sa.Column("peer_cursor", sa.Text(), nullable=True))
    for t in PEER_TABLES:
        if "from_peer" not in _cols(t):
            op.add_column(t, sa.Column("from_peer", sa.Boolean(), nullable=True))
    if "event_local_nodes" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "event_local_nodes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("node_name", sa.String(60), nullable=False),
            sa.Column("joined_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("event_id", "node_name", name="uq_event_local_node"),
        )


def downgrade():
    op.drop_table("event_local_nodes")
    for t in PEER_TABLES:
        op.drop_column(t, "from_peer")
    op.drop_column("events", "peer_cursor")
    op.drop_column("events", "local_shared")
