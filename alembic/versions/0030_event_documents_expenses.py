"""Reunión 2026-09-21, ítems 8 y 7: Documentos del Evento y Legalizaciones (gastos).

- `event_documents` — archivos generales del evento (nombre/referencia, descripción, archivo).
- `event_expenses` — un gasto por fila (categoría, responsable, descripción, a quién aplica, valor y
  foto de evidencia). El `amount` no estaba en la lista original del pedido, pero el reporte pide "el
  total de gastos" — sin un valor no hay total que sumar.

Revision ID: 0030_event_docs_expenses
Revises: 0029_final_report_email
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0030_event_docs_expenses"
down_revision = "0029_final_report_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("stored_path", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "event_expenses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("responsible", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("applies_to", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("evidence_path", sa.String(), nullable=True),
        sa.Column("evidence_name", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("event_expenses")
    op.drop_table("event_documents")
