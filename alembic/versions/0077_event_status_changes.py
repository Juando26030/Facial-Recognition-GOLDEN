"""Eventos en curso, pedido B: devolver un evento «en curso» a «creado». Solo ADITIVA.

  event_status_changes   bitácora de los retrocesos de estado (quién, cuándo, motivo opcional, cuántas personas e ingresos tenía). Solo INSERT, sin llaves foráneas ni datos personales.
  access_logs.doubtful_reason   «sin_hora_valida» en el ingreso que un quiosco sin red sincronizó tras el retroceso sin una hora válida (columna nueva y vacía; para revisarlos).

El código anterior las ignora; bajar la migración quita la tabla y la columna.

Revision ID: 0077_event_status_changes
Revises: 0076_print_mode
Create Date: 2026-11-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0077_event_status_changes"
down_revision = "0076_print_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_status_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("staff_username", sa.String(80), nullable=True),
        sa.Column("from_status", sa.String(12), nullable=False),
        sa.Column("to_status", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("attendees_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("access_logs_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_event_status_changes_event_id", "event_status_changes", ["event_id"])
    op.add_column("access_logs", sa.Column("doubtful_reason", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("access_logs", "doubtful_reason")
    op.drop_index("ix_event_status_changes_event_id", table_name="event_status_changes")
    op.drop_table("event_status_changes")
