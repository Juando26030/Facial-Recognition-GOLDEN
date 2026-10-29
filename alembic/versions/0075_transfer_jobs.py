"""Exportar / importar eventos: seguimiento de los trabajos en segundo plano (docs/18_EXPORTAR_EVENTOS.md, F4). Solo ADITIVA: columnas nuevas y vacías en una tabla que hoy solo guarda bitácora.

  event_transfer_log.stage        etapa que se está haciendo («Tabla access_logs»…)
  event_transfer_log.progress     porcentaje 0-100
  event_transfer_log.result_json  informe final (conteos y avisos; sin datos personales) o el mensaje de error
  event_transfer_log.file_key     el .zip generado en el almacenamiento (se borra a las 24 h)
  event_transfer_log.finished_at  cuándo terminó

Revision ID: 0075_transfer_jobs
Revises: 0074_event_transfer
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0075_transfer_jobs"
down_revision = "0074_event_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_transfer_log", sa.Column("stage", sa.String(60), nullable=True))
    op.add_column("event_transfer_log", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("event_transfer_log", sa.Column("result_json", sa.Text(), nullable=True))
    op.add_column("event_transfer_log", sa.Column("file_key", sa.String(300), nullable=True))
    op.add_column("event_transfer_log", sa.Column("finished_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in ("finished_at", "file_key", "result_json", "progress", "stage"):
        op.drop_column("event_transfer_log", col)
