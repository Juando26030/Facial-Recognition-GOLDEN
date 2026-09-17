"""Sprint 2.2 (Parámetros del Evento): EventFieldConfig — cómo debe comportarse un campo del alta
manual/edición para un evento (obligatorio o no, tipo de control, opciones si es lista
desplegable, y si debe generar estadística sola al entrar a Estadísticas y con qué gráfico).
Sin fila para un campo dado = valores por defecto, ver app/routers/parametros.py. Ver CLAUDE.md
y models.py para el detalle de cada campo.

Revision ID: 0014_event_field_configs
Revises: 0013_event_auto_register
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_event_field_configs"
down_revision = "0013_event_auto_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_field_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("field_key", sa.String(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("field_type", sa.String(), nullable=False, server_default="text_short"),
        sa.Column("options_json", sa.Text()),
        sa.Column("default_stat_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_chart_type", sa.String()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "field_key", name="uq_event_field_config"),
    )


def downgrade() -> None:
    op.drop_table("event_field_configs")
