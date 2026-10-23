"""Impresión compartida de escarapelas (orden del 22-oct-2026): interruptor por evento APAGADO por defecto, dispositivos que reportan su impresora USB,
a qué equipo imprime cada usuario y la cola de trabajos de impresión. Solo ADITIVA: no toca ni reescribe datos existentes.

Revision ID: 0069_shared_print
Revises: 0068_door_liveness
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0069_shared_print"
down_revision = "0068_door_liveness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("shared_print_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table(
        "print_devices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("platform", sa.String(40), nullable=True),
        sa.Column("browser", sa.String(40), nullable=True),
        sa.Column("printer_connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("printer_name", sa.String(80), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "staff_user_id", name="uq_print_device_event_staff"),
    )
    op.create_table(
        "print_routes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("printer_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=True),
        sa.UniqueConstraint("event_id", "staff_user_id", name="uq_print_route_event_staff"),
    )
    op.create_table(
        "print_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attendee_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("printer_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("request_id", name="uq_print_job_request"),
    )
    op.create_index("ix_print_jobs_printer_status", "print_jobs", ["event_id", "printer_staff_id", "status", "created_at"])
    op.create_index("ix_print_jobs_requester", "print_jobs", ["event_id", "requested_by_staff_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_print_jobs_requester", table_name="print_jobs")
    op.drop_index("ix_print_jobs_printer_status", table_name="print_jobs")
    op.drop_table("print_jobs")
    op.drop_table("print_routes")
    op.drop_table("print_devices")
    op.drop_column("events", "shared_print_enabled")
