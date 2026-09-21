"""Reunión 2026-09-21, ítem 14: categorías del evento y escarapela por categoría.

- `events.categories` (JSON, lista de nombres) — las categorías que define ESE evento (ej. VIP, Prensa).
- `events.badge_per_category` — False = una plantilla para todas; True = una por categoría.
- `event_attendees.categories` (JSON) — la(s) categoría(s) de cada persona EN ESE evento.
- `badge_templates.category` — NULL = plantilla general; con nombre = la de esa categoría. Por eso se
  suelta el UNIQUE(event_id) (1:1) y queda UNIQUE(event_id, category).

Revision ID: 0028_event_categories
Revises: 0027_event_logo
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_event_categories"
down_revision = "0027_event_logo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("categories", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("badge_per_category", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.add_column(sa.Column("categories", sa.Text(), nullable=True))

    # El nombre del UNIQUE(event_id) lo puso Postgres al crear la tabla — se busca en vez de suponerlo.
    inspector = sa.inspect(op.get_bind())
    old_unique = [
        uc["name"] for uc in inspector.get_unique_constraints("badge_templates")
        if uc["column_names"] == ["event_id"] and uc.get("name")
    ]
    with op.batch_alter_table("badge_templates") as batch_op:
        for name in old_unique:
            batch_op.drop_constraint(name, type_="unique")
        batch_op.add_column(sa.Column("category", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_badge_template_event_category", ["event_id", "category"])


def downgrade() -> None:
    with op.batch_alter_table("badge_templates") as batch_op:
        batch_op.drop_constraint("uq_badge_template_event_category", type_="unique")
        batch_op.drop_column("category")
        batch_op.create_unique_constraint("badge_templates_event_id_key", ["event_id"])
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.drop_column("categories")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("badge_per_category")
        batch_op.drop_column("categories")
