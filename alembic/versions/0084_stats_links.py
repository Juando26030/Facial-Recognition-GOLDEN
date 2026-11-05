"""Enlaces de solo lectura a las estadísticas (evento o formulario). Solo ADITIVA.

  stats_links   una fila por enlace: solo el hash SHA-256 del token, alcance (evento o formulario), vencimiento y revocación. El enlace muestra agregados, nada de personas.

Sin SET de sesión, sin advisory locks; compatible con el pooler de Neon. El código anterior ignora la tabla. Permisos: si existe el rol `golden_app`, se le dan los de la tabla.
Bajar la migración quita la tabla.

Revision ID: 0084_stats_links
Revises: 0083_reprint_requests
Create Date: 2026-11-05
"""
from alembic import op

revision = "0084_stats_links"
down_revision = "0083_reprint_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS stats_links (
            id SERIAL PRIMARY KEY,
            token_hash VARCHAR(64) NOT NULL,
            scope VARCHAR(6) NOT NULL,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            form_id INTEGER REFERENCES web_forms(id) ON DELETE CASCADE,
            tenant_id VARCHAR NOT NULL,
            label VARCHAR(80),
            created_by_staff_id INTEGER REFERENCES staff_users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            revoked_at TIMESTAMP,
            last_seen_at TIMESTAMP
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_stats_links_token_hash ON stats_links (token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stats_links_event ON stats_links (event_id, scope)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON stats_links TO golden_app; "
               "GRANT USAGE, SELECT, UPDATE ON SEQUENCE stats_links_id_seq TO golden_app; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stats_links")
