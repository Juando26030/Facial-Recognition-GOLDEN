"""Registro de solicitudes de privacidad (consultas y reclamos de habeas data): radicado AÑO-CONSECUTIVO, fecha límite en días hábiles y la bandera «reclamo en trámite» sobre el dato de la persona.

Condición de la auditora para adoptar el manual de consultas y reclamos. Sin llaves foráneas hacia las personas (una supresión no borra el registro de la solicitud).

Revision ID: 0061_privacy_requests
Revises: 0060_biometric_setup
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0061_privacy_requests"
down_revision = "0060_biometric_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privacy_request_counters",
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("last", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("radicado", sa.String(16), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("holder_name", sa.String, nullable=False),
        sa.Column("cedula", sa.String, nullable=False),
        sa.Column("tenant_id", sa.String, nullable=True),
        sa.Column("event_id", sa.Integer, nullable=True),
        sa.Column("request_type", sa.String(24), nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="recibida"),
        sa.Column("claim_flag", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("claim_flag_due", sa.Date, nullable=True),
        sa.Column("history_json", sa.Text, nullable=True),
        sa.Column("created_by_staff_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_privacy_requests_cedula", "privacy_requests", ["cedula"])


def downgrade() -> None:
    op.drop_table("privacy_requests")
    op.drop_table("privacy_request_counters")
