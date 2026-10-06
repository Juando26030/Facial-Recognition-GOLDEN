"""Estados de evento configurables con reglas (docs/18 §4).

`event_states` (nombre, estado base, color, orden, reglas) y `events.state_id`. Se siembran los tres estados de siempre con las reglas que reproducen EXACTAMENTE el comportamiento actual (cliente y
digitador temporal solo entran con el evento en proceso; solo se registra en proceso; los certificados solo finalizado) y cada evento queda apuntando al estado de su `status`.

Revision ID: 0052_event_states
Revises: 0051_biometric_retention
Create Date: 2026-10-05
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0052_event_states"
down_revision = "0051_biometric_retention"
branch_labels = None
depends_on = None

_RULES = {
    "creado": {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": True, "touch_registration": False,
               "areas": True, "inventory_control": True, "certificates": False},
    "en_proceso": {"client_access": True, "client_stats_download": True, "temp_digitadores_enter": True, "registration": True, "roulette": True, "touch_registration": True,
                   "areas": True, "inventory_control": True, "certificates": False},
    "finalizado": {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": False, "touch_registration": False,
                   "areas": True, "inventory_control": True, "certificates": True},
}
_STATES = (("Creado", "creado", "#0056b3", 0), ("En proceso", "en_proceso", "#1e7e34", 1), ("Finalizado", "finalizado", "#777777", 2))


def upgrade() -> None:
    op.create_table(
        "event_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("base_status", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("rules_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    table = sa.table("event_states", sa.column("name", sa.String), sa.column("base_status", sa.String), sa.column("color", sa.String), sa.column("position", sa.Integer),
                     sa.column("rules_json", sa.Text))
    op.bulk_insert(table, [{"name": n, "base_status": b, "color": c, "position": p, "rules_json": json.dumps(_RULES[b])} for n, b, c, p in _STATES])
    op.add_column("events", sa.Column("state_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_events_state_id", "events", "event_states", ["state_id"], ["id"])
    op.execute("UPDATE events SET state_id = (SELECT s.id FROM event_states s WHERE s.base_status = events.status ORDER BY s.position LIMIT 1)")


def downgrade() -> None:
    op.drop_constraint("fk_events_state_id", "events", type_="foreignkey")
    op.drop_column("events", "state_id")
    op.drop_table("event_states")
