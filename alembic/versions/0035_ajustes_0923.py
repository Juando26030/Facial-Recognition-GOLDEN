"""Ajustes 2026-09-23.

- `saved_colors`: librería de colores de pañoleta (nombre + hex, global). El evento sigue guardando su propia
  copia (`bandana_color`/`bandana_color_name`), así que borrar un color no cambia los eventos que ya lo usaron.
- `events.certificates_token`: enlace secreto (/c/<token>) para que cada persona descargue su certificado.

Revision ID: 0035_ajustes_0923
Revises: 0034_digital_badge
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_ajustes_0923"
down_revision = "0034_digital_badge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_colors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hex", sa.String(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("name", name="uq_saved_color_name"),
    )
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("certificates_token", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_event_certificates_token", ["certificates_token"])


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("uq_event_certificates_token", type_="unique")
        batch_op.drop_column("certificates_token")
    op.drop_table("saved_colors")
