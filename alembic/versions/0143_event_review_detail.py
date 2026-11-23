"""Eventos: «Revisar el detalle» (aviso rojo en el calendario cuando la comercial pide leer el detalle)."""
import sqlalchemy as sa
from alembic import op

revision = "0143_event_review_detail"
down_revision = "0142_crm_legacy_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("review_detail", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("events", "review_detail")
