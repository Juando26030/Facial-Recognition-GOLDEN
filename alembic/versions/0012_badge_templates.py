"""Sprint 2, Épico 2 (Escarapelas): Event.auto_print_badge + BadgeTemplate (plantilla activa,
una por evento) + SavedBadgeTemplate (librería reusable por tenant). saved_badge_templates se
crea primero porque badge_templates tiene una FK opcional hacia ella (solo trazabilidad de
"importado desde"). Ver CLAUDE.md y models.py para el detalle de cada campo.

Revision ID: 0012_badge_templates
Revises: 0011_roster_uploaded_flag
Create Date: 2026-09-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_badge_templates"
down_revision = "0011_roster_uploaded_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("auto_print_badge", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "saved_badge_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("width_mm", sa.Float(), nullable=False),
        sa.Column("height_mm", sa.Float(), nullable=False),
        sa.Column("orientation", sa.String(), nullable=False, server_default="vertical"),
        sa.Column("background_type", sa.String(), nullable=False, server_default="color"),
        sa.Column("background_value", sa.String()),
        sa.Column("elements_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "badge_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False, server_default="Escarapela"),
        sa.Column("width_mm", sa.Float(), nullable=False, server_default="62.0"),
        sa.Column("height_mm", sa.Float(), nullable=False, server_default="100.0"),
        sa.Column("orientation", sa.String(), nullable=False, server_default="vertical"),
        sa.Column("background_type", sa.String(), nullable=False, server_default="color"),
        sa.Column("background_value", sa.String()),
        sa.Column("elements_json", sa.Text()),
        sa.Column("imported_from_saved_template_id", sa.Integer(), sa.ForeignKey("saved_badge_templates.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("badge_templates")
    op.drop_table("saved_badge_templates")
    op.drop_column("events", "auto_print_badge")
