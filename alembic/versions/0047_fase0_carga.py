"""Fase 0 de escalabilidad (docs/13): índices para los caminos calientes, versión de rostros por evento, identificador de ingreso
generado por el cliente (idempotencia) y llaves de cupo denormalizadas en las inscripciones.

Revision ID: 0047_fase0_carga
Revises: 0046_biometric_consent
Create Date: 2026-09-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0047_fase0_carga"
down_revision = "0046_biometric_consent"
branch_labels = None
depends_on = None

# Ya existian (0036, 0037, 0040): rate_limit_events (kind,key,created_at) y (kind,ip,created_at), bulk_jobs (event_id,status) y form_payments (form_id,status).
INDEXES = [
    # (nombre, tabla, columnas)
    ("ix_access_logs_event_user", "access_logs", ["event_id", "user_id"]),
    ("ix_access_logs_event_ts", "access_logs", ["event_id", "timestamp"]),
    ("ix_event_attendees_user", "event_attendees", ["user_id", "tenant_id"]),
    ("ix_print_logs_event_user", "print_logs", ["event_id", "user_id"]),
    ("ix_form_submissions_form_status", "form_submissions", ["form_id", "status", "is_test"]),
    ("ix_form_submissions_form_person", "form_submissions", ["form_id", "person_id"]),
    ("ix_form_submissions_form_sid", "form_submissions", ["form_id", "sid"]),
    ("ix_form_payments_submission", "form_payments", ["submission_id"]),
    ("ix_form_payments_status_created", "form_payments", ["status", "created_at"]),
    ("ix_form_events_form_kind_sid", "form_events", ["form_id", "kind", "sid"]),
    ("ix_rate_limit_created", "rate_limit_events", ["created_at"]),
]


def upgrade() -> None:
    op.add_column("events", sa.Column("faces_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("access_logs", sa.Column("client_id", sa.String(), nullable=True))
    op.add_column("form_submissions", sa.Column("quota_keys", sa.Text(), nullable=True))
    op.create_index("uq_access_log_client", "access_logs", ["event_id", "client_id"], unique=True, postgresql_where=sa.text("client_id IS NOT NULL"))
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_index("uq_access_log_client", table_name="access_logs")
    op.drop_column("form_submissions", "quota_keys")
    op.drop_column("access_logs", "client_id")
    op.drop_column("events", "faces_version")
