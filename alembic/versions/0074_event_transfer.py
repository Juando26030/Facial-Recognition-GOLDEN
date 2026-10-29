"""Exportar / importar eventos entre entornos (docs/18_EXPORTAR_EVENTOS.md). Solo ADITIVA: no toca ni reescribe datos existentes.

  event_transfer_log     bitácora de exportaciones e importaciones (quién, cuándo, evento, conteos, huella del paquete; sin datos personales)
  event_import_actors    nombre de usuario (texto) de quien hizo un registro en el entorno de origen cuando esa cuenta no existe en el destino
  form_payments.origin   «importado» = pago histórico traído de otro entorno

El código anterior ignora lo nuevo; bajar la migración quita solo lo nuevo.

Revision ID: 0074_event_transfer
Revises: 0073_attendee_origin
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0074_event_transfer"
down_revision = "0073_attendee_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_transfer_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("staff_username", sa.String(80), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("event_code", sa.String(80), nullable=True),
        sa.Column("package_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("counts_json", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("state_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "event_import_actors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("event_transfer_log.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(40), nullable=False),
        sa.Column("row_ref", sa.String(160), nullable=False),
        sa.Column("column_name", sa.String(40), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
    )
    op.create_index("ix_event_import_actors_import_id", "event_import_actors", ["import_id"])
    op.add_column("form_payments", sa.Column("origin", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("form_payments", "origin")
    op.drop_index("ix_event_import_actors_import_id", table_name="event_import_actors")
    op.drop_table("event_import_actors")
    op.drop_table("event_transfer_log")
