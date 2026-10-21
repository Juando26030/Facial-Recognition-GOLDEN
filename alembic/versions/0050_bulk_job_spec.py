"""Carga masiva como Cloud Run Job: la especificación de la carga (tokens de los archivos ya subidos, nombres de columnas, eventos de
origen, quién la lanzó) se guarda en la fila de la tarea, así el Job —otro contenedor— la puede ejecutar sin recibir nada más que el id.

Revision ID: 0050_bulk_job_spec
Revises: 0049_form_atomic_reserve
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0050_bulk_job_spec"
down_revision = "0049_form_atomic_reserve"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bulk_jobs", sa.Column("spec_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bulk_jobs", "spec_json")
