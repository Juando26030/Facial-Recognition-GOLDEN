"""Reunión 2026-09-21, ítem 6: informe final del evento (PDF) y correo de la comercial.

- `events.report_pdf_path` / `events.report_uploaded_at` — el PDF del informe y cuándo se subió
  (NULL = pendiente → bombillo naranja; con valor = enviado → verde).
- `staff_users.email` — a dónde se le manda el informe a la comercial (y futuras notificaciones).
  Opcional: las cuentas existentes no lo tienen hasta que un admin lo complete.

Revision ID: 0029_final_report_email
Revises: 0028_event_categories
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_final_report_email"
down_revision = "0028_event_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("report_pdf_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("report_uploaded_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.drop_column("email")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("report_uploaded_at")
        batch_op.drop_column("report_pdf_path")
