"""Contactos del cliente en cada evento (event_contacts): varios por evento, uno principal."""
import sqlalchemy as sa
from alembic import op

revision = "0145_event_contacts"
down_revision = "0144_crm_pdf_layout"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crm_contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(60), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_event_contacts_event", "event_contacts", ["event_id"])
    op.create_index("uq_event_contacts_primary", "event_contacts", ["event_id"], unique=True, postgresql_where=sa.text("is_primary"))


def downgrade():
    op.drop_index("uq_event_contacts_primary", table_name="event_contacts")
    op.drop_index("ix_event_contacts_event", table_name="event_contacts")
    op.drop_table("event_contacts")
