"""URL limpia de las inscripciones públicas (D2.5k): events.public_slug único global, web_forms.is_primary y slug_history.

Revision ID: 0113_public_slug
Revises: 0112_local_nodes
"""
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision = "0113_public_slug"
down_revision = "0112_local_nodes"
branch_labels = None
depends_on = None

_RESERVED = {"static", "api", "health", "ready", "healthz", "readyz", "webhooks", "f", "b", "c", "r", "login", "logout", "kiosk", "sistema", "admin", "privacidad", "terminos", "reembolsos",
             "inscripciones", "www", "app", "aceptar", "entrega", "internal", "ver", "dashboard", "eventos", "clientes", "calendario", "configuracion", "staff", "inventario", "sincronizacion",
             "servidor-local", "cambiar-contrasena", "reimpresion", "assets", "docs", "formularios", "formulario"}


def _slugify(text):
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _candidate(name, year):
    base = _slugify(name) or "evento"
    suffix = "-%s" % year if year and not re.search(r"(^|-)%s$" % year, base) else ""
    base = base[: 60 - len(suffix) - 4].strip("-")
    slug = (base + suffix).strip("-")
    if len(slug) < 3 or slug.isdigit() or slug in _RESERVED:
        slug = ("evento-" + slug).strip("-")[:60]
    return slug


def upgrade():
    op.add_column("events", sa.Column("public_slug", sa.String(), nullable=True))
    op.add_column("web_forms", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "slug_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hold_until", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_slug_history_slug", "slug_history", ["slug"])
    # Respaldo idempotente: cada evento SIN slug recibe «nombre + año» (con -2, -3… si choca). Solo toca los que están en NULL.
    conn = op.get_bind()
    taken = {r[0].lower() for r in conn.execute(sa.text("SELECT public_slug FROM events WHERE public_slug IS NOT NULL"))}
    rows = conn.execute(sa.text("SELECT id, name, start_date, created_at FROM events WHERE public_slug IS NULL ORDER BY id")).fetchall()
    for ev_id, name, start, created in rows:
        year = (start or created).year if (start or created) else None
        base = _candidate(name, year)
        slug, n = base, 2
        while slug in taken:
            tail = "-%d" % n
            slug, n = base[: 60 - len(tail)].rstrip("-") + tail, n + 1
        taken.add(slug)
        conn.execute(sa.text("UPDATE events SET public_slug = :s WHERE id = :i"), {"s": slug, "i": ev_id})
    op.execute("CREATE UNIQUE INDEX uq_events_public_slug ON events (lower(public_slug)) WHERE public_slug IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_events_public_slug")
    op.drop_index("ix_slug_history_slug", table_name="slug_history")
    op.drop_table("slug_history")
    op.drop_column("web_forms", "is_primary")
    op.drop_column("events", "public_slug")
