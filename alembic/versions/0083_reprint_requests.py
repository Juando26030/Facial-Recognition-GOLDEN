"""Fase 1B · reimpresión con permisos. Solo ADITIVA (docs/1B_reimpresion_permisos.md).

  events.reprint_disabled     BOOLEAN NOT NULL DEFAULT false: true = reimprimir a quien ya se imprimió exige permiso del coordinador del evento. Con DEFAULT constante en Postgres 11+ no reescribe la tabla.
  reprint_requests            una fila por solicitud de permiso (pending | approved | denied | expired | used | cancelled) con quién, cuándo y por qué canal (pantalla o correo).
  reprint_links               enlaces de correo de UN SOLO USO: solo se guarda el hash SHA-256 del token (nunca el token), ligado a una solicitud y a un destinatario.
  reprint_audit               cadena de auditoría de cada solicitud (solicitada, avisada, correo, aprobada, negada, vencida, usada): solo se agregan filas.

Sin SET de sesión, sin advisory locks; compatible con el pooler de Neon. El código anterior ignora todo esto. Permisos: si existe el rol `golden_app`, se le dan los de las tres tablas nuevas y sus secuencias (como 0077).
Bajar la migración quita las tablas y la columna.

Revision ID: 0083_reprint_requests
Revises: 0082_attendee_last_action
Create Date: 2026-11-05
"""
from alembic import op

revision = "0083_reprint_requests"
down_revision = "0082_attendee_last_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS reprint_disabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("""
        CREATE TABLE IF NOT EXISTS reprint_requests (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            tenant_id VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL,
            requested_by_staff_id INTEGER REFERENCES staff_users(id) ON DELETE SET NULL,
            approver_staff_id INTEGER REFERENCES staff_users(id) ON DELETE SET NULL,
            status VARCHAR(12) NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            screen_seen_at TIMESTAMP,
            email_sent_at TIMESTAMP,
            decided_at TIMESTAMP,
            decided_by_staff_id INTEGER REFERENCES staff_users(id) ON DELETE SET NULL,
            decided_channel VARCHAR(10),
            used_at TIMESTAMP,
            used_channel VARCHAR(12)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reprint_requests_event_status ON reprint_requests (event_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reprint_requests_requester ON reprint_requests (requested_by_staff_id, event_id, user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS reprint_links (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES reprint_requests(id) ON DELETE CASCADE,
            staff_id INTEGER REFERENCES staff_users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_reprint_links_token_hash ON reprint_links (token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reprint_links_request ON reprint_links (request_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS reprint_audit (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES reprint_requests(id) ON DELETE CASCADE,
            at TIMESTAMP NOT NULL,
            kind VARCHAR(16) NOT NULL,
            staff_id INTEGER REFERENCES staff_users(id) ON DELETE SET NULL,
            channel VARCHAR(12)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reprint_audit_request ON reprint_audit (request_id, id)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON reprint_requests, reprint_links, reprint_audit TO golden_app; "
               "GRANT USAGE, SELECT, UPDATE ON SEQUENCE reprint_requests_id_seq, reprint_links_id_seq, reprint_audit_id_seq TO golden_app; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reprint_audit")
    op.execute("DROP TABLE IF EXISTS reprint_links")
    op.execute("DROP TABLE IF EXISTS reprint_requests")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS reprint_disabled")
