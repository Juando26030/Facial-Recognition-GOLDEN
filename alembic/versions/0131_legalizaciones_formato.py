"""Legalizaciones en el formato oficial de Golden (14-nov-2026). Solo ADITIVA.

  event_expenses: kind (default 'otro', así los gastos que ya existen quedan en «Otros gastos») y los campos de cada hoja del Excel
    (fecha, NIT/cédula, nombre, dirección, teléfono, correo, origen, destino, concepto, placa, vehículo, IVA, soporte S/N, comidas,
    valor unitario, observación, aprobado y quién/cuándo lo aprobó).
  event_legalizations: encabezado de la legalización de cada evento (responsable, CC, anticipo en pesos, fecha, etapa y quién envió/revisó).

Escrita a mano; sin SET de sesión (pooler de Neon). Ids ≤ 32 caracteres.

Revision ID: 0131_legalizaciones_formato
Revises: 0129_staff_client_temp
"""
from alembic import op
import sqlalchemy as sa

revision = "0131_legalizaciones_formato"
down_revision = "0129_staff_client_temp"
branch_labels = None
depends_on = None

TEXT_COLS = ("tax_id", "vendor_name", "address", "phone", "email", "origin", "destination", "concept", "plate")
MONEY_COLS = ("iva", "breakfast", "lunch", "dinner", "snack", "unit_value")
ALL_NEW = ("kind", "expense_date", *TEXT_COLS, "vehicle", *MONEY_COLS, "has_support", "observation", "approved", "approved_by_id", "approved_at")


def upgrade():
    op.add_column("event_expenses", sa.Column("kind", sa.String(20), nullable=False, server_default="otro"))
    op.add_column("event_expenses", sa.Column("expense_date", sa.Date(), nullable=True))
    for c in TEXT_COLS:
        op.add_column("event_expenses", sa.Column(c, sa.String(), nullable=True))
    op.add_column("event_expenses", sa.Column("vehicle", sa.String(10), nullable=True))
    for c in MONEY_COLS:
        op.add_column("event_expenses", sa.Column(c, sa.Numeric(14, 2), nullable=True))
    op.add_column("event_expenses", sa.Column("has_support", sa.Boolean(), nullable=True))
    op.add_column("event_expenses", sa.Column("observation", sa.Text(), nullable=True))
    op.add_column("event_expenses", sa.Column("approved", sa.Boolean(), nullable=True))
    op.add_column("event_expenses", sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True))
    op.add_column("event_expenses", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.create_index("ix_event_expenses_event_kind", "event_expenses", ["event_id", "kind"])

    op.create_table(
        "event_legalizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column("responsible_name", sa.String(), nullable=True),
        sa.Column("responsible_cc", sa.String(), nullable=True),
        sa.Column("advance_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("legalization_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="borrador"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("event_legalizations")
    op.drop_index("ix_event_expenses_event_kind", table_name="event_expenses")
    for c in reversed(ALL_NEW):
        op.drop_column("event_expenses", c)
