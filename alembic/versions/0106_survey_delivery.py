"""Fase 5 (B): entrega al cliente con encuesta de satisfacción. Solo ADITIVA.

  event_delivery_links   enlace público /entrega/<token> por evento Facturado (hash del token; revocable; regenerable)
  survey_responses       una encuesta contestada por evento (NPS, promedio, versión); sin datos personales; NO se purga con la biometría
  survey_answers         una fila por pregunta con puntaje numérico, lista para la analítica de gerencia

Permisos: si existe el rol `golden_app`, se le dan los de las tablas nuevas y sus secuencias (como 0084, 0087 y 0088).

Revision ID: 0106_survey_delivery
Revises: 0104_pledge_health_flags
"""
from alembic import op

revision = "0106_survey_delivery"
down_revision = "0104_pledge_health_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_delivery_links (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            nonce VARCHAR(32) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            created_by_id INTEGER NULL REFERENCES staff_users(id) ON DELETE SET NULL,
            revoked_at TIMESTAMP NULL,
            last_opened_at TIMESTAMP NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_delivery_links_event_id ON event_delivery_links (event_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS survey_responses (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            tenant_id VARCHAR NOT NULL,
            survey_version INTEGER NOT NULL,
            submitted_at TIMESTAMP NOT NULL,
            nps_score INTEGER NULL,
            avg_score DOUBLE PRECISION NULL,
            delivery_link_id INTEGER NULL REFERENCES event_delivery_links(id) ON DELETE SET NULL,
            comment_count INTEGER NOT NULL DEFAULT 0,
            ip_hash VARCHAR(16) NULL
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_survey_responses_event ON survey_responses (event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_survey_responses_tenant_at ON survey_responses (tenant_id, submitted_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS survey_answers (
            id SERIAL PRIMARY KEY,
            response_id INTEGER NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
            event_id INTEGER NOT NULL,
            tenant_id VARCHAR NOT NULL,
            submitted_at TIMESTAMP NOT NULL,
            survey_version INTEGER NOT NULL,
            question_id VARCHAR(40) NOT NULL,
            score INTEGER NULL,
            choice_text VARCHAR(60) NULL,
            comment TEXT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_survey_answers_response_id ON survey_answers (response_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_survey_answers_question ON survey_answers (question_id, submitted_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_survey_answers_event ON survey_answers (event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_survey_answers_tenant_at ON survey_answers (tenant_id, submitted_at)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON event_delivery_links, survey_responses, survey_answers TO golden_app;
                GRANT USAGE, SELECT ON SEQUENCE event_delivery_links_id_seq, survey_responses_id_seq, survey_answers_id_seq TO golden_app;
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS survey_answers")
    op.execute("DROP TABLE IF EXISTS survey_responses")
    op.execute("DROP TABLE IF EXISTS event_delivery_links")
