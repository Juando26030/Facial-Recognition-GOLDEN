"""Color de marca por evento. Solo ADITIVA.

  events.brand_color   '#rrggbb' o NULL (= el dorado general de Golden). Misma idea que logo_mode/logo_path.

Revision ID: 0098_event_brand_color
Revises: 0095_super_events_archive
Create Date: 2026-11-08
"""
from alembic import op

revision = "0098_event_brand_color"
down_revision = "0096_decisiones_dueno"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS brand_color VARCHAR NULL")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS brand_color")
