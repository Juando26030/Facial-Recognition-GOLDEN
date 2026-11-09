"""Compromiso digital del digitador por evento, sobre el motor de formularios web. Solo ADITIVA.

  events.pledge_enabled          el evento exige el compromiso (false = comportamiento de siempre)
  web_forms.kind                 'registration' (de siempre) | 'pledge' (el formulario del compromiso; su slug aleatorio es el enlace secreto)
  form_submissions.sensitive_json  respuestas de campos marcados `sensitive`, CIFRADAS por la aplicación (app/crypto.py); se borran por retención
  event_staff_pledges            evidencia por evento y persona: huella SHA-256, versión del texto, firma y documento en el almacenamiento, avisos booleanos sin detalle
                                 y marcas de historial (superseded_at) y de purga (health_purged_at)
  uq_pledge_active               un solo compromiso vigente por (evento, persona); una firma nueva marca la anterior como reemplazada

Sin SET de sesión, sin advisory locks; compatible con el pooler de Neon. El código anterior ignora lo nuevo. Bajar la migración lo quita.

Revision ID: 0101_event_staff_pledge
Revises: 0099_digital_badge_fields
Create Date: 2026-11-08
"""
from alembic import op

revision = "0101_event_staff_pledge"
down_revision = "0100_event_staff_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS pledge_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE web_forms ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'registration'")
    op.execute("ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS sensitive_json TEXT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_staff_pledges (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(id),
            staff_id INTEGER NOT NULL REFERENCES staff_users(id),
            submission_id INTEGER NOT NULL REFERENCES form_submissions(id),
            signed_at TIMESTAMP NOT NULL,
            source VARCHAR(10) NOT NULL DEFAULT 'link',
            text_version VARCHAR(40) NOT NULL,
            sensitive_auth_version VARCHAR(60) NULL,
            content_hash VARCHAR(64) NOT NULL,
            signature_key VARCHAR(300) NOT NULL,
            doc_key VARCHAR(300) NULL,
            attendance_confirmed BOOLEAN NOT NULL DEFAULT false,
            understands_terms BOOLEAN NOT NULL DEFAULT false,
            has_health_info BOOLEAN NOT NULL DEFAULT false,
            ip_masked VARCHAR(64) NULL,
            resign_allowed_at TIMESTAMP NULL,
            superseded_at TIMESTAMP NULL,
            health_purged_at TIMESTAMP NULL
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pledge_active ON event_staff_pledges (event_id, staff_id) WHERE superseded_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pledge_event ON event_staff_pledges (event_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_staff_pledges")
    op.execute("ALTER TABLE form_submissions DROP COLUMN IF EXISTS sensitive_json")
    op.execute("ALTER TABLE web_forms DROP COLUMN IF EXISTS kind")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS pledge_enabled")
